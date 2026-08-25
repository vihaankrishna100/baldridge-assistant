from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request

import audit
from config import settings
from deps import current_user
from models import ROLES
from repo import get_repo
from repo.base import EmailTaken, InviteRecord, UserRecord, utcnow
from schemas import (
    AcceptInviteRequest,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    TotpSetupResponse,
    TwoFactorRequest,
    UserOut,
)
from security import (
    create_session_token,
    decode_token,
    hash_invite_token,
    hash_password,
    needs_rehash,
    new_totp_secret,
    password_problems,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15

# Returned for both "no such user" and "wrong password" so the endpoint can't
# be used to enumerate who works here.
BAD_CREDENTIALS = "Email or password is incorrect."


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request):
    store = get_repo()
    user = store.get_user_by_email(payload.email)
    now = utcnow()

    if user is None:
        audit.log("login_failed", target=payload.email, detail="unknown account", request=request)
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)

    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            status_code=423,
            detail="Too many failed attempts. This account is locked for a few minutes.",
        )

    if not user.is_active:
        audit.log("login_failed", user=user, detail="account disabled", request=request)
        raise HTTPException(status_code=403, detail="This account has been disabled.")

    if not verify_password(payload.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_logins = 0
            audit.log("account_locked", user=user, request=request)
        store.save_user(user)
        audit.log("login_failed", user=user, detail="bad password", request=request)
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)

    # Only write when there is something to change. A successful login on a
    # clean account previously cost a Firestore write for no reason.
    dirty = False
    if user.failed_logins or user.locked_until:
        user.failed_logins = 0
        user.locked_until = None
        dirty = True
    if needs_rehash(user.password_hash):
        # The plaintext is only available here, so this is the one moment the
        # stored hash can be re-costed without asking anyone to reset.
        user.password_hash = hash_password(payload.password)
        dirty = True
    if dirty:
        store.save_user(user)

    # An allowlisted account signs in on password alone. Everyone else goes
    # through the second factor, whether or not they've enrolled yet.
    if settings.is_2fa_exempt(user.email):
        audit.log(
            "login_2fa_bypassed", user=user,
            detail="account is on TWOFA_EXEMPT_EMAILS", request=request,
        )
        return _finalize_login(user, request)

    if settings.require_2fa:
        scope = "2fa" if user.totp_confirmed else "2fa_setup"
        challenge = create_session_token(user.id, user.token_epoch, scope=scope)
        audit.log("login_password_ok", user=user, request=request)
        return LoginResponse(
            status="2fa_required" if user.totp_confirmed else "2fa_setup_required",
            challenge_token=challenge,
        )

    return _finalize_login(user, request)


def _finalize_login(user: UserRecord, request: Request) -> LoginResponse:
    user.last_login_at = utcnow()
    get_repo().save_user(user)
    audit.log("login_success", user=user, request=request)
    return LoginResponse(
        status="ok",
        access_token=create_session_token(user.id, user.token_epoch),
        user=UserOut.model_validate(user),
    )


def _user_from_challenge(token: str, expected_scope: str) -> UserRecord:
    payload = decode_token(token)
    if not payload or payload.get("scope") != expected_scope:
        raise HTTPException(status_code=401, detail="This sign-in step expired. Start over.")
    user = get_repo().get_user(payload.get("sub", ""))
    if user is None or not user.is_active or payload.get("epoch") != user.token_epoch:
        raise HTTPException(status_code=401, detail="This sign-in step is no longer valid.")
    return user


@router.post("/2fa/setup", response_model=TotpSetupResponse)
def start_2fa_setup(payload: dict):
    user = _user_from_challenge(payload.get("challenge_token", ""), "2fa_setup")

    secret = new_totp_secret()
    user.totp_secret = secret
    user.totp_confirmed = False
    get_repo().save_user(user)

    uri = totp_uri(secret, user.email)
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    return TotpSetupResponse(secret=secret, otpauth_uri=uri, qr_svg=buf.getvalue().decode())


@router.post("/2fa/confirm", response_model=LoginResponse)
def confirm_2fa(payload: TwoFactorRequest, request: Request):
    user = _user_from_challenge(payload.challenge_token, "2fa_setup")
    if not verify_totp(user.totp_secret or "", payload.code):
        raise HTTPException(status_code=401, detail="That code didn't match. Try the next one.")
    user.totp_confirmed = True
    get_repo().save_user(user)
    audit.log("2fa_enrolled", user=user, request=request)
    return _finalize_login(user, request)


@router.post("/2fa/verify", response_model=LoginResponse)
def verify_2fa(payload: TwoFactorRequest, request: Request):
    user = _user_from_challenge(payload.challenge_token, "2fa")
    if not verify_totp(user.totp_secret or "", payload.code):
        audit.log("2fa_failed", user=user, request=request)
        raise HTTPException(status_code=401, detail="That code didn't match. Try the next one.")
    return _finalize_login(user, request)


@router.get("/invite/{token}")
def check_invite(token: str):
    invite = _load_invite(token)
    return {"email": invite.email, "role": invite.role, "org_name": settings.org_name}


def _load_invite(token: str) -> InviteRecord:
    invite = get_repo().get_invite_by_token_hash(hash_invite_token(token))
    now = utcnow()
    if invite is None or invite.accepted_at is not None or invite.expires_at < now:
        raise HTTPException(
            status_code=404,
            detail="This invitation is invalid or has expired. Ask an administrator for a new one.",
        )
    return invite


@router.post("/invite/accept", response_model=LoginResponse)
def accept_invite(payload: AcceptInviteRequest, request: Request):
    store = get_repo()
    invite = _load_invite(payload.token)

    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(status_code=400, detail="Password " + ", ".join(problems) + ".")

    user = UserRecord(
        email=invite.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=invite.role if invite.role in ROLES else "staff",
    )
    try:
        store.create_user(user)
    except EmailTaken:
        raise HTTPException(status_code=409, detail="An account already exists for this email.")

    invite.accepted_at = utcnow()
    store.save_invite(invite)

    audit.log("invite_accepted", user=user, request=request)

    if settings.require_2fa and not settings.is_2fa_exempt(user.email):
        return LoginResponse(
            status="2fa_setup_required",
            challenge_token=create_session_token(
                user.id, user.token_epoch, scope="2fa_setup"
            ),
        )
    return _finalize_login(user, request)


@router.get("/me", response_model=UserOut)
def me(user: UserRecord = Depends(current_user)):
    return UserOut.model_validate(user)


@router.post("/password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: UserRecord = Depends(current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    problems = password_problems(payload.new_password)
    if problems:
        raise HTTPException(status_code=400, detail="New password " + ", ".join(problems) + ".")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_epoch += 1  # every existing session token stops working
    get_repo().save_user(user)
    audit.log("password_changed", user=user, request=request)
    return {"ok": True, "message": "Password updated. Please sign in again."}


@router.post("/logout")
def logout(request: Request, user: UserRecord = Depends(current_user)):
    audit.log("logout", user=user, request=request)
    return {"ok": True}

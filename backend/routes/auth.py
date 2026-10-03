from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

import audit
from config import settings
from deps import bearer, current_user, revoke
from models import ROLE_TEAM, ROLES
from repo import get_repo
from mailer import MailError, send_sign_in_code
from repo.base import EMAIL_2FA, EmailTaken, InviteRecord, UserRecord, utcnow
from schemas import (
    AcceptInviteRequest,
    ChallengeRequest,
    ChangePasswordRequest,
    EnrollConfirmRequest,
    EnrollRequest,
    LoginRequest,
    LoginResponse,
    TotpSetupResponse,
    TwoFactorRequest,
    UserOut,
)
from security import (
    check_email_code,
    create_session_token,
    decode_token,
    hash_invite_token,
    hash_password,
    needs_rehash,
    new_email_code,
    new_totp_secret,
    password_problems,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Wrong passwords lock out the address they came from, not the account: on a
# shared login, one person's typos must not sign out everyone everywhere.
# Failures are counted in 5-minute buckets over the last 15 minutes.
LOCKOUT_THRESHOLD = 5
# Backstop for guessing spread across many addresses, which a per-address
# limit alone would never stop. Far above anything typos produce.
ACCOUNT_LOCKOUT_THRESHOLD = 50
_BUCKET_MINUTES = 5
_WINDOW_BUCKETS = 3

# Returned for both "no such user" and "wrong password" so the endpoint can't
# be used to enumerate who works here.
BAD_CREDENTIALS = "Email or password is incorrect."
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")
LOCKED = "Too many failed attempts from this device. Try again in about 15 minutes."


def _buckets() -> list[str]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now.replace(minute=now.minute - now.minute % _BUCKET_MINUTES)
    return [
        (start - timedelta(minutes=_BUCKET_MINUTES * i)).strftime("%Y-%m-%dT%H:%M")
        for i in range(_WINDOW_BUCKETS)
    ]


def _failure_keys(user: UserRecord, ip: str) -> tuple[str, str]:
    # Stored in query_counters, whose key column is 32 characters.
    per_ip = "lf:" + hashlib.sha256(f"{user.id}|{ip}".encode()).hexdigest()[:29]
    per_account = "la:" + user.id[:29]
    return per_ip, per_account


def _is_locked(user: UserRecord, ip: str) -> bool:
    store = get_repo()
    per_ip, per_account = _failure_keys(user, ip)
    buckets = _buckets()
    ip_failures = sum(store.get_query_counter(per_ip, b) for b in buckets)
    if ip_failures >= LOCKOUT_THRESHOLD:
        return True
    return sum(store.get_query_counter(per_account, b) for b in buckets) >= ACCOUNT_LOCKOUT_THRESHOLD


def _record_failure(user: UserRecord, ip: str) -> None:
    store = get_repo()
    bucket = _buckets()[0]
    for key in _failure_keys(user, ip):
        store.bump_query_counter(key, bucket, 10**9)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request):
    store = get_repo()
    user = store.get_user_by_email(payload.email)
    ip = audit.client_ip(request)

    if user is None:
        # Same bcrypt cost as a real check, so response time doesn't reveal
        # which emails have accounts.
        verify_password(payload.password, _DUMMY_HASH)
        audit.log("login_failed", target=payload.email, detail="unknown account", request=request)
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)

    if _is_locked(user, ip):
        raise HTTPException(status_code=423, detail=LOCKED)

    if not user.is_active:
        audit.log("login_failed", user=user, detail="account disabled", request=request)
        raise HTTPException(status_code=403, detail="This account has been disabled.")

    if not verify_password(payload.password, user.password_hash):
        _record_failure(user, ip)
        audit.log("login_failed", user=user, detail="bad password", request=request)
        if _is_locked(user, ip):
            audit.log("login_locked", user=user, detail=f"ip {ip}", request=request)
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)

    # Only write when there is something to change. A successful login on a
    # clean account previously cost a Firestore write for no reason. The
    # fields cleared here belong to the old account-wide lockout.
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

    # Anyone who has set up a second step uses it — including an allowlisted
    # account that chose to, which is how an exempt admin turns it on.
    if user.totp_confirmed:
        return _second_step(user, request)

    # An allowlisted account signs in on password alone. Everyone else goes
    # through the second factor, whether or not they've enrolled yet.
    if settings.is_2fa_exempt(user.email):
        audit.log(
            "login_2fa_bypassed", user=user,
            detail="account is on TWOFA_EXEMPT_EMAILS", request=request,
        )
        return _finalize_login(user, request)
    # A shared login cannot have one person's authenticator app behind it.
    if user.role == ROLE_TEAM:
        return _finalize_login(user, request)

    if settings.require_2fa:
        challenge = create_session_token(user.id, user.token_epoch, scope="2fa_setup")
        audit.log("login_password_ok", user=user, request=request)
        return LoginResponse(status="2fa_setup_required", challenge_token=challenge)

    return _finalize_login(user, request)


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'•' * max(2, len(name) - 1)}@{domain}"


def _send_email_code(user: UserRecord) -> dict:
    """Emails a fresh code; returns the claims that let us check it."""
    code, claims = new_email_code()
    try:
        send_sign_in_code(user.email, code)
    except MailError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "We couldn't send the email code just now. Try again in a minute, or ask "
                "an administrator to reset your two-step sign-in."
            ),
        ) from exc
    return claims


def _second_step(user: UserRecord, request: Request) -> LoginResponse:
    audit.log("login_password_ok", user=user, request=request)
    if user.twofa_method == "email":
        claims = _send_email_code(user)
        token = create_session_token(
            user.id, user.token_epoch, scope="2fa", extra=claims, ttl_minutes=10
        )
        return LoginResponse(
            status="2fa_required", challenge_token=token, method="email", sent_to=_mask(user.email)
        )
    token = create_session_token(user.id, user.token_epoch, scope="2fa")
    return LoginResponse(status="2fa_required", challenge_token=token, method="app")


def _spend_attempt(claims: dict) -> None:
    """Five tries per code. Without this a 6-digit code falls to guessing."""
    key = "2a:" + hashlib.sha256((claims.get("n") or claims.get("jti", "")).encode()).hexdigest()[:29]
    if not get_repo().bump_query_counter(key, "attempts", 5):
        raise HTTPException(
            status_code=429, detail="Too many wrong codes. Start over to get a new one."
        )


def _finalize_login(user: UserRecord, request: Request) -> LoginResponse:
    user.last_login_at = utcnow()
    get_repo().save_user(user)
    audit.log("login_success", user=user, request=request)
    return LoginResponse(
        status="ok",
        access_token=create_session_token(user.id, user.token_epoch),
        user=UserOut.model_validate(user),
    )


def _challenge(token: str, expected_scope: str) -> tuple[UserRecord, dict]:
    payload = decode_token(token)
    if not payload or payload.get("scope") != expected_scope:
        raise HTTPException(status_code=401, detail="This sign-in step expired. Start over.")
    user = get_repo().get_user(payload.get("sub", ""))
    if user is None or not user.is_active or payload.get("epoch") != user.token_epoch:
        raise HTTPException(status_code=401, detail="This sign-in step is no longer valid.")
    return user, payload


def _user_from_challenge(token: str, expected_scope: str) -> UserRecord:
    return _challenge(token, expected_scope)[0]


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
    user, claims = _challenge(payload.challenge_token, "2fa_setup")
    _spend_attempt(claims)
    if not verify_totp(user.totp_secret or "", payload.code):
        raise HTTPException(status_code=401, detail="That code didn't match. Try the next one.")
    user.totp_confirmed = True
    get_repo().save_user(user)
    audit.log("2fa_enrolled", user=user, detail="app", request=request)
    return _finalize_login(user, request)


@router.post("/2fa/verify", response_model=LoginResponse)
def verify_2fa(payload: TwoFactorRequest, request: Request):
    user, claims = _challenge(payload.challenge_token, "2fa")
    _spend_attempt(claims)
    if claims.get("m") == "email":
        ok = check_email_code(claims, payload.code)
    else:
        ok = verify_totp(user.totp_secret or "", payload.code)
    if not ok:
        audit.log("2fa_failed", user=user, request=request)
        raise HTTPException(status_code=401, detail="That code didn't match. Check it and try again.")
    return _finalize_login(user, request)


@router.post("/2fa/resend", response_model=LoginResponse)
def resend_email_code(payload: ChallengeRequest, request: Request):
    user, _ = _challenge(payload.challenge_token, "2fa")
    if user.twofa_method != "email":
        raise HTTPException(status_code=400, detail="This account uses an authenticator app.")
    key = "rs:" + user.id[:29]
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    if not get_repo().bump_query_counter(key, bucket, 5):
        raise HTTPException(status_code=429, detail="Too many codes sent. Try again later.")
    return _second_step(user, request)


# ---------------------------------------------- setting up two-step sign-in
# For someone already signed in — typically an account that was allowed to
# skip it and now wants it on. Nothing changes until a code is confirmed, so
# abandoning halfway leaves the account exactly as it was.


@router.get("/2fa/options")
def two_step_options(user: UserRecord = Depends(current_user)):
    return {"method": user.twofa_method, "email_available": settings.email_codes_available}


@router.post("/2fa/enroll")
def start_enroll(payload: EnrollRequest, user: UserRecord = Depends(current_user)):
    if user.role == ROLE_TEAM:
        raise HTTPException(
            status_code=403, detail="The shared team login can't have its own second step."
        )
    if payload.method == "app":
        secret = new_totp_secret()
        uri = totp_uri(secret, user.email)
        buf = io.BytesIO()
        qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buf)
        token = create_session_token(
            user.id, user.token_epoch, scope="2fa_enroll",
            extra={"m": "app", "s": secret}, ttl_minutes=10,
        )
        return {"enroll_token": token, "secret": secret, "otpauth_uri": uri, "qr_svg": buf.getvalue().decode()}
    if payload.method == "email":
        if not settings.email_codes_available:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Email codes aren't switched on for this assistant yet. Use an "
                    "authenticator app, or ask whoever set it up to connect an email service."
                ),
            )
        claims = _send_email_code(user)
        token = create_session_token(
            user.id, user.token_epoch, scope="2fa_enroll", extra=claims, ttl_minutes=10
        )
        return {"enroll_token": token, "sent_to": _mask(user.email)}
    raise HTTPException(status_code=400, detail="Choose an authenticator app or email.")


@router.post("/2fa/enroll/confirm")
def confirm_enroll(
    payload: EnrollConfirmRequest,
    request: Request,
    user: UserRecord = Depends(current_user),
):
    enrollee, claims = _challenge(payload.enroll_token, "2fa_enroll")
    if enrollee.id != user.id:
        raise HTTPException(status_code=401, detail="This setup step expired. Start over.")
    _spend_attempt(claims)
    if claims.get("m") == "app":
        ok = verify_totp(claims.get("s", ""), payload.code)
        secret = claims.get("s", "")
    else:
        ok = check_email_code(claims, payload.code)
        secret = EMAIL_2FA
    if not ok:
        raise HTTPException(status_code=401, detail="That code didn't match. Check it and try again.")
    user.totp_secret = secret
    user.totp_confirmed = True
    get_repo().save_user(user)
    audit.log("2fa_enrolled", user=user, detail=user.twofa_method, request=request)
    return {"ok": True, "method": user.twofa_method}


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
    if user.role == ROLE_TEAM:
        # Changing it here would sign every coworker out with a password they
        # were never given.
        raise HTTPException(
            status_code=403, detail="The team password is managed by an administrator."
        )
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
def logout(
    request: Request,
    user: UserRecord = Depends(current_user),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    # Clearing the token in the browser isn't enough on a shared computer: a
    # copied token would stay valid until it expired. Revoke this one now.
    payload = decode_token(creds.credentials) if creds else None
    if payload:
        revoke(payload)
    audit.log("logout", user=user, request=request)
    return {"ok": True}

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

import audit
from config import settings
from deps import require_admin
from models import ROLES
from rag.index import index
from repo import get_repo
from repo.base import InviteRecord, UserRecord, utcnow
from schemas import AuditOut, InviteCreate, InviteOut, UserOut
from security import new_invite_token

router = APIRouter(prefix="/admin", tags=["admin"])

INVITE_TTL_DAYS = 7


@router.get("/users", response_model=list[UserOut])
def list_users(_: UserRecord = Depends(require_admin)):
    return [UserOut.model_validate(u) for u in get_repo().list_users()]


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(
    payload: InviteCreate,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    email = payload.email.lower()
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if store.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="That email already has an account.")

    raw, token_hash = new_invite_token()
    invite = store.create_invite(
        InviteRecord(
            email=email,
            role=payload.role,
            token_hash=token_hash,
            created_by=admin.id,
            expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
        )
    )

    audit.log("invite_created", user=admin, target=email, detail=payload.role, request=request)

    origin = settings.cors_origin_list[0] if settings.cors_origin_list else ""
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        # Shown once. The plaintext token is never stored, so it cannot be
        # recovered later — the admin re-invites instead.
        invite_url=f"{origin}/invite/{raw}",
        expires_at=invite.expires_at,
    )


@router.get("/invites")
def list_invites(_: UserRecord = Depends(require_admin)):
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "expires_at": i.expires_at.isoformat(),
            "created_at": i.created_at.isoformat(),
        }
        for i in get_repo().list_open_invites()
    ]


@router.delete("/invites/{invite_id}")
def revoke_invite(
    invite_id: str,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    invite = store.get_invite(invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    store.delete_invite(invite_id)
    audit.log("invite_revoked", user=admin, target=invite.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    target.is_active = False
    target.token_epoch += 1  # kills any session they currently hold
    store.save_user(target)
    audit.log("user_deactivated", user=admin, target=target.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.is_active = True
    target.failed_logins = 0
    target.locked_until = None
    store.save_user(target)
    audit.log("user_activated", user=admin, target=target.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/reset-2fa")
def reset_2fa(
    user_id: str,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.totp_secret = None
    target.totp_confirmed = False
    target.token_epoch += 1
    store.save_user(target)
    audit.log("2fa_reset", user=admin, target=target.email, request=request)
    return {"ok": True, "message": f"{target.email} will re-enrol on next sign-in."}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: str,
    payload: dict,
    request: Request,
    admin: UserRecord = Depends(require_admin),
):
    store = get_repo()
    role = payload.get("role", "")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id and role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own admin access.")

    previous = target.role
    target.role = role
    store.save_user(target)
    audit.log(
        "role_changed", user=admin, target=target.email,
        detail=f"{previous} -> {role}", request=request,
    )
    return {"ok": True}


@router.get("/audit", response_model=list[AuditOut])
def audit_trail(
    limit: int = 200,
    action: str = "",
    _: UserRecord = Depends(require_admin),
):
    return [
        AuditOut.model_validate(r)
        for r in get_repo().list_audit(limit=min(limit, 1000), action=action)
    ]


@router.get("/stats")
def stats(_: UserRecord = Depends(require_admin)):
    store = get_repo()
    since = utcnow() - timedelta(days=30)
    answered = store.count_messages_since(since, escalated=False)
    escalated = store.count_messages_since(since, escalated=True)
    total = answered + escalated

    return {
        "users": store.count_active_users(),
        "documents": store.count_active_documents(),
        "questions_30d": total,
        "answered_30d": answered,
        "escalated_30d": escalated,
        "answer_rate": round(answered / total, 3) if total else 0.0,
        "index": index.stats(),
        "storage": (
            {
                "used_bytes": store.storage_bytes(),
                "limit_bytes": settings.storage_limit_mb * 1024 * 1024,
            }
            if hasattr(store, "storage_bytes")
            else None
        ),
        # The most valuable admin view: what staff keep asking that the
        # document library does not yet cover.
        "coverage_gaps": [
            {"question": q, "count": n} for q, n in store.coverage_gaps(since)
        ],
    }


@router.get("/settings")
def read_settings(_: UserRecord = Depends(require_admin)):
    from docstore import get_docstore

    return {
        "org_name": settings.org_name,
        "org_phone": settings.org_phone,
        "org_email": settings.org_email,
        "contact_name": settings.org_fallback_contact_name,
        "contact_configured": bool(settings.org_phone or settings.org_email),
        "require_2fa": settings.require_2fa,
        "twofa_exempt": settings.twofa_exempt_list,
        "model": settings.assistant_model,
        "effort": settings.assistant_effort,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_score": settings.retrieval_min_score,
        "max_queries_per_hour": settings.max_queries_per_hour,
        "max_upload_mb": settings.max_upload_mb,
        "storage": type(get_docstore()).__name__,
        "repo": type(get_repo()).__name__,
    }

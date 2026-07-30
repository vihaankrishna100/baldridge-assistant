from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

import audit
from config import settings
from database import get_db
from deps import require_admin
from models import ROLES, AuditLog, Document, Invite, Message, User
from rag.index import index
from schemas import AuditOut, InviteCreate, InviteOut, UserOut
from security import new_invite_token

router = APIRouter(prefix="/admin", tags=["admin"])

INVITE_TTL_DAYS = 7


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at).all()
    return [UserOut.model_validate(u) for u in users]


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(
    payload: InviteCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = payload.email.lower()
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if db.query(User).filter(User.email == email).one_or_none():
        raise HTTPException(status_code=409, detail="That email already has an account.")

    raw, token_hash = new_invite_token()
    invite = Invite(
        email=email,
        role=payload.role,
        token_hash=token_hash,
        created_by=admin.id,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.commit()

    audit.log(db, "invite_created", user=admin, target=email, detail=payload.role, request=request)

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
def list_invites(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(Invite)
        .filter(Invite.accepted_at.is_(None))
        .order_by(Invite.created_at.desc())
        .all()
    )
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "expires_at": i.expires_at.isoformat(),
            "created_at": i.created_at.isoformat(),
        }
        for i in rows
    ]


@router.delete("/invites/{invite_id}")
def revoke_invite(
    invite_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    email = invite.email
    db.delete(invite)
    db.commit()
    audit.log(db, "invite_revoked", user=admin, target=email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    target.is_active = False
    target.token_epoch += 1  # kills any session they currently hold
    db.commit()
    audit.log(db, "user_deactivated", user=admin, target=target.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.is_active = True
    target.failed_logins = 0
    target.locked_until = None
    db.commit()
    audit.log(db, "user_activated", user=admin, target=target.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/reset-2fa")
def reset_2fa(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.totp_secret = None
    target.totp_confirmed = False
    target.token_epoch += 1
    db.commit()
    audit.log(db, "2fa_reset", user=admin, target=target.email, request=request)
    return {"ok": True, "message": f"{target.email} will re-enrol on next sign-in."}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: str,
    payload: dict,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    role = payload.get("role", "")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id and role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own admin access.")

    previous = target.role
    target.role = role
    db.commit()
    audit.log(
        db, "role_changed", user=admin, target=target.email,
        detail=f"{previous} -> {role}", request=request,
    )
    return {"ok": True}


@router.get("/audit", response_model=list[AuditOut])
def audit_trail(
    limit: int = 200,
    action: str = "",
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.at.desc()).limit(min(limit, 1000)).all()
    return [AuditOut.model_validate(r) for r in rows]


@router.get("/stats")
def stats(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    answered = (
        db.query(func.count(Message.id))
        .filter(Message.role == "assistant", Message.escalated.is_(False), Message.created_at >= since)
        .scalar()
        or 0
    )
    escalated = (
        db.query(func.count(Message.id))
        .filter(Message.role == "assistant", Message.escalated.is_(True), Message.created_at >= since)
        .scalar()
        or 0
    )
    total = answered + escalated

    # Only genuine "the documents don't cover this" escalations belong here.
    # Blocked prompt-extraction attempts and API outages are not gaps in the
    # library, and listing them would send someone off writing the wrong policy.
    gaps = (
        db.query(AuditLog.target, func.count(AuditLog.id).label("n"))
        .filter(
            AuditLog.action == "question_escalated",
            AuditLog.at >= since,
            AuditLog.detail.notlike("%meta_query%"),
            AuditLog.detail.notlike("%error%"),
            AuditLog.detail.notlike("%safety_refusal%"),
        )
        .group_by(AuditLog.target)
        .order_by(func.count(AuditLog.id).desc())
        .limit(15)
        .all()
    )

    return {
        "users": db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0,
        "documents": db.query(func.count(Document.id)).filter(Document.is_active.is_(True)).scalar() or 0,
        "questions_30d": total,
        "answered_30d": answered,
        "escalated_30d": escalated,
        "answer_rate": round(answered / total, 3) if total else 0.0,
        "index": index.stats(),
        # The most valuable admin view: what staff keep asking that the
        # document library does not yet cover.
        "coverage_gaps": [{"question": t, "count": n} for t, n in gaps if t],
    }


@router.get("/settings")
def read_settings(_: User = Depends(require_admin)):
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
    }

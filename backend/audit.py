from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from models import AuditLog, User


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:60]
    return (request.client.host if request.client else "")[:60]


def log(
    db: Session,
    action: str,
    *,
    user: User | None = None,
    target: str = "",
    detail: str = "",
    request: Request | None = None,
    commit: bool = True,
) -> None:
    """Append-only audit trail.

    Every authenticated action writes a row here. `detail` should describe what
    happened, never the document text itself — the log is queryable by admins
    and should not become a second copy of the corpus.
    """
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else "",
        action=action,
        target=target[:300],
        detail=detail[:2000],
        ip=client_ip(request),
    )
    db.add(entry)
    if commit:
        db.commit()

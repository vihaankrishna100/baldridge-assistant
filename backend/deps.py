from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import ROLE_ADMIN, ROLE_LEADERSHIP, QueryCounter, User
from security import decode_token

bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise _unauthorized()
    payload = decode_token(creds.credentials)
    if not payload or payload.get("scope") != "session":
        raise _unauthorized("Session expired or invalid")

    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise _unauthorized("Account is disabled")
    # Password changes and admin-forced logouts bump token_epoch, which
    # retroactively invalidates every token issued before the change.
    if payload.get("epoch") != user.token_epoch:
        raise _unauthorized("Session has been revoked — please sign in again")
    if (
        settings.require_2fa
        and not user.totp_confirmed
        and not settings.is_2fa_exempt(user.email)
    ):
        raise HTTPException(status_code=403, detail="Two-factor setup is required")
    return user


def require_leadership(user: User = Depends(current_user)) -> User:
    if user.role not in (ROLE_LEADERSHIP, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Leadership access required")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def enforce_rate_limit(db: Session, user: User) -> None:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    row = (
        db.query(QueryCounter)
        .filter(QueryCounter.user_id == user.id, QueryCounter.hour_bucket == bucket)
        .one_or_none()
    )
    if row is None:
        row = QueryCounter(user_id=user.id, hour_bucket=bucket, count=0)
        db.add(row)
    if row.count >= settings.max_queries_per_hour:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've reached the limit of {settings.max_queries_per_hour} "
                "questions this hour. Try again shortly."
            ),
        )
    row.count += 1
    db.commit()


def get_request(request: Request) -> Request:
    return request

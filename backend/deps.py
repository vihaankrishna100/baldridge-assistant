from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from models import ROLE_ADMIN, ROLE_LEADERSHIP, ROLE_TEAM
from repo import get_repo
from repo.base import UserRecord
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
) -> UserRecord:
    if creds is None:
        raise _unauthorized()
    payload = decode_token(creds.credentials)
    if not payload or payload.get("scope") != "session":
        raise _unauthorized("Session expired or invalid")

    user = get_repo().get_user(payload.get("sub", ""))
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
        and user.role != ROLE_TEAM
    ):
        raise HTTPException(status_code=403, detail="Two-factor setup is required")
    return user


def require_leadership(user: UserRecord = Depends(current_user)) -> UserRecord:
    if user.role not in (ROLE_LEADERSHIP, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Leadership access required")
    return user


def require_admin(user: UserRecord = Depends(current_user)) -> UserRecord:
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def enforce_rate_limit(user: UserRecord) -> None:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    limit = (
        settings.team_queries_per_hour if user.role == ROLE_TEAM else settings.max_queries_per_hour
    )
    allowed = get_repo().bump_query_counter(user.id, bucket, limit)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"You've reached the limit of {limit} questions this hour. Try again shortly.",
        )


def get_request(request: Request) -> Request:
    return request

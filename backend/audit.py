from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor

from fastapi import Request

from repo import get_repo
from repo.base import AuditEntry, UserRecord

# The trail is append-only and nothing reads it during a request, so writing it
# inline just made every caller wait on a Firestore round trip. Two workers is
# enough to keep up and bounded enough not to pile up under load.
_writer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit")


def _write(entry: AuditEntry) -> None:
    try:
        get_repo().append_audit(entry)
    except Exception as exc:  # noqa: BLE001 - a failed audit must not 500 a request
        print(f"[audit] write failed: {type(exc).__name__}: {exc}")


def submit(entry: AuditEntry) -> None:
    """Queue an already-built entry."""
    _writer.submit(_write, entry)


def flush(timeout: float = 10.0) -> None:
    """Drain pending writes. Called on shutdown so a redeploy doesn't drop the
    last few entries."""
    _writer.shutdown(wait=True, cancel_futures=False)


atexit.register(flush)


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:60]
    return (request.client.host if request.client else "")[:60]


def log(
    action: str,
    *,
    user: UserRecord | None = None,
    target: str = "",
    detail: str = "",
    request: Request | None = None,
) -> None:
    """Append-only audit trail.

    Every authenticated action writes a row here. `detail` should describe what
    happened, never the document text itself — the log is queryable by admins
    and should not become a second copy of the corpus.
    """
    # Built here, on the request thread, so the caller's identity and IP are
    # captured accurately; only the write is deferred.
    _writer.submit(
        _write,
        AuditEntry(
            user_id=user.id if user else None,
            user_email=user.email if user else "",
            action=action,
            target=target[:300],
            detail=detail[:2000],
            ip=client_ip(request),
        ),
    )

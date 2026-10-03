from __future__ import annotations

import atexit
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi import Request

from repo import get_repo
from repo.base import AuditEntry, UserRecord, utcnow

# The trail is append-only and nothing reads it during a request, so writing it
# inline just made every caller wait on a Firestore round trip. Two workers is
# enough to keep up and bounded enough not to pile up under load.
_writer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit")


# ------------------------------------------------------------ retention
# The trail is kept for a set number of days (admin-adjustable, stored in the
# database) so it stays readable and doesn't eat the storage limit. 0 keeps
# everything. Question/answer stats are read from this trail, so they cover
# at most the retention window.
RETENTION_KEY = "audit_retention_days"
DEFAULT_RETENTION_DAYS = 7
RETENTION_CHOICES = (1, 3, 7, 14, 30, 90, 0)
_PRUNE_EVERY = 3600.0
_last_prune = 0.0
_prune_lock = threading.Lock()


def retention_days() -> int:
    store = get_repo()
    if not hasattr(store, "get_setting"):
        return DEFAULT_RETENTION_DAYS
    try:
        raw = store.get_setting(RETENTION_KEY)
        return int(raw) if raw is not None else DEFAULT_RETENTION_DAYS
    except Exception:  # noqa: BLE001 - a bad value falls back to the default
        return DEFAULT_RETENTION_DAYS


def set_retention_days(days: int) -> None:
    get_repo().set_setting(RETENTION_KEY, str(days))
    prune(force=True)


def prune(force: bool = False) -> int:
    """Deletes entries older than the retention window. Throttled to once an
    hour per process unless forced."""
    global _last_prune
    store = get_repo()
    if not hasattr(store, "delete_audit_before"):
        return 0
    with _prune_lock:
        if not force and time.monotonic() - _last_prune < _PRUNE_EVERY:
            return 0
        _last_prune = time.monotonic()
    days = retention_days()
    if days <= 0:
        return 0
    return store.delete_audit_before(utcnow() - timedelta(days=days))


def _write(entry: AuditEntry) -> None:
    try:
        get_repo().append_audit(entry)
        prune()
    except Exception as exc:  # noqa: BLE001 - a failed audit must not 500 a request
        print(f"[audit] write failed: {type(exc).__name__}: {exc}")


def submit(entry: AuditEntry) -> None:
    """Queue an already-built entry."""
    _writer.submit(_write, entry)


def flush_pending(timeout: float = 10.0) -> None:
    """Waits for writes already queued, without stopping the writer. One
    marker per worker: once every worker has reached its marker, everything
    queued before them has been written."""
    barrier = threading.Barrier(_writer._max_workers)
    marks = [_writer.submit(barrier.wait, timeout) for _ in range(_writer._max_workers)]
    for f in marks:
        try:
            f.result(timeout=timeout)
        except Exception:  # noqa: BLE001 - best effort; the clear still proceeds
            pass


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

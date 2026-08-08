"""Storage abstraction.

Two implementations satisfy this interface:

  sqlite    — the default. Local file, no cloud account, works offline. Used by
              the test suite, so the routes above it are exercised for real.
  firestore — Google Cloud. Survives the machine it runs on, which is what makes
              a Cloud Run deployment possible.

Everything above this layer speaks in the dataclasses defined here, never in
SQLAlchemy models or Firestore snapshots, so a route cannot accidentally depend
on one backend's behaviour.
"""

from __future__ import annotations

import os

from .base import (  # noqa: F401
    AuditEntry,
    ChunkRecord,
    ConversationRecord,
    DocumentRecord,
    InviteRecord,
    MessageRecord,
    Repo,
    UserRecord,
)

_repo: Repo | None = None


def get_repo() -> Repo:
    """The process-wide store. Chosen once, at first use."""
    global _repo
    if _repo is None:
        backend = os.getenv("REPO_BACKEND", "sqlite").strip().lower()
        if backend == "firestore":
            from .firestore_repo import FirestoreRepo

            _repo = FirestoreRepo()
        elif backend == "sqlite":
            from .sqlite_repo import SqliteRepo

            _repo = SqliteRepo()
        else:
            raise RuntimeError(
                f"REPO_BACKEND must be 'sqlite' or 'firestore', got {backend!r}"
            )
    return _repo


def set_repo(repo: Repo | None) -> None:
    """Test hook — swap the store, or reset with None."""
    global _repo
    _repo = repo

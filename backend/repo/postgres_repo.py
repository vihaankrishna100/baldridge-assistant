"""Postgres (Neon) implementation of the Repo protocol.

Why this exists: the Firestore backend needed a Google Cloud project with
billing enabled, and Cloud Run needed a card on file to serve a single request.
Neon's free tier runs this workload — one lodge, a handful of staff, a few
policy documents — without a payment method.

Three things are better here than on Firestore, and they are the reason the
code is shorter:

  * Unique constraints exist, so create_user does not need a companion
    user_emails/{email} document inside a transaction. A 23505 is EmailTaken.
  * GROUP BY exists, so coverage_gaps is one query instead of a Python tally.
  * Joins exist, though chunks stay denormalised anyway so that retrieval is a
    single indexed scan.

Connections: Neon suspends an idle branch and resumes in well under a second.
Use the POOLED connection string (it has `-pooler` in the host) — a serverless
function opens a connection per invocation and pgbouncer is what keeps that
from exhausting the backend.
"""

from __future__ import annotations

import atexit
import os
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .base import (
    AuditEntry,
    ChunkRecord,
    ConversationRecord,
    DocumentRecord,
    EmailTaken,
    InviteRecord,
    MessageRecord,
    UserRecord,
    as_naive_utc,
    utcnow,
)

T = TypeVar("T")

UNIQUE_VIOLATION = "23505"

_pool: ConnectionPool | None = None


def _dsn() -> str:
    # POSTGRES_URL wins so that DATABASE_URL can keep pointing at the local
    # SQLite file during a migration — the migrator needs to read one and
    # write the other in the same process. In production only DATABASE_URL
    # may be set, so it is the fallback.
    from config import settings

    dsn = os.getenv("POSTGRES_URL", "") or settings.postgres_url or os.getenv("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError(
            "Neither POSTGRES_URL nor DATABASE_URL is set — point one at the "
            "Neon pooled connection string."
        )
    # SQLAlchemy-style prefixes are common in copied config; psycopg wants the
    # plain one.
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgres://"):
        if dsn.startswith(prefix):
            dsn = "postgresql://" + dsn[len(prefix) :]
            break
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _dsn(),
            min_size=0,          # nothing held open while the lodge is asleep
            max_size=int(os.getenv("PG_POOL_MAX", "5")),
            timeout=15,
            max_idle=60,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Shut the pool down.

    Without this the worker threads outlive the interpreter and psycopg prints
    "couldn't stop thread ... within 5.0 seconds" on every exit. On a
    serverless platform that is a function that will not retire cleanly, so it
    is wired into the application lifespan and atexit as well.
    """
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


atexit.register(close_pool)


def _hydrate(cls: type[T], row: dict[str, Any] | None) -> T | None:
    """Build a dataclass from a row, normalising timestamps to naive UTC and
    ignoring columns the dataclass does not declare (search_vector)."""
    if row is None:
        return None
    names = {f.name for f in dataclass_fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, value in row.items():
        if key not in names:
            continue
        kwargs[key] = as_naive_utc(value) if isinstance(value, datetime) else value
    return cls(**kwargs)


def _all(cls: type[T], rows: list[dict[str, Any]]) -> list[T]:
    return [r for r in (_hydrate(cls, row) for row in rows) if r is not None]


class PostgresRepo:

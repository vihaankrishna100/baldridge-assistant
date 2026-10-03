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
    DocumentRecord,
    EmailTaken,
    InviteRecord,
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
    ignoring columns the dataclass does not declare."""
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
    # ---------------------------------------------------------------- users

    def get_user(self, user_id: str) -> UserRecord | None:
        with get_pool().connection() as c:
            return _hydrate(UserRecord, c.execute(
                "SELECT * FROM users WHERE id = %s", (user_id,)).fetchone())

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with get_pool().connection() as c:
            return _hydrate(UserRecord, c.execute(
                "SELECT * FROM users WHERE lower(email) = lower(%s)", (email,)).fetchone())

    def list_users(self) -> list[UserRecord]:
        with get_pool().connection() as c:
            return _all(UserRecord, c.execute(
                "SELECT * FROM users ORDER BY created_at").fetchall())

    def create_user(self, user: UserRecord) -> UserRecord:
        user.email = user.email.lower()
        try:
            with get_pool().connection() as c:
                c.execute(
                    """INSERT INTO users (id, email, full_name, password_hash, role,
                           totp_secret, totp_confirmed, is_active, must_change_password,
                           failed_logins, locked_until, last_login_at, created_at, token_epoch)
                       VALUES (%(id)s, %(email)s, %(full_name)s, %(password_hash)s, %(role)s,
                           %(totp_secret)s, %(totp_confirmed)s, %(is_active)s,
                           %(must_change_password)s, %(failed_logins)s, %(locked_until)s,
                           %(last_login_at)s, %(created_at)s, %(token_epoch)s)""",
                    user.__dict__,
                )
        except psycopg.errors.UniqueViolation as exc:
            raise EmailTaken(user.email) from exc
        return user

    def save_user(self, user: UserRecord) -> None:
        with get_pool().connection() as c:
            c.execute(
                """UPDATE users SET email=%(email)s, full_name=%(full_name)s,
                       password_hash=%(password_hash)s, role=%(role)s,
                       totp_secret=%(totp_secret)s, totp_confirmed=%(totp_confirmed)s,
                       is_active=%(is_active)s, must_change_password=%(must_change_password)s,
                       failed_logins=%(failed_logins)s, locked_until=%(locked_until)s,
                       last_login_at=%(last_login_at)s, token_epoch=%(token_epoch)s
                   WHERE id=%(id)s""",
                user.__dict__,
            )

    def delete_user(self, user_id: str) -> None:
        with get_pool().connection() as c:
            c.execute("DELETE FROM users WHERE id = %s", (user_id,))

    def count_active_users(self) -> int:
        with get_pool().connection() as c:
            return c.execute("SELECT count(*) AS n FROM users WHERE is_active").fetchone()["n"]

    # -------------------------------------------------------------- invites

    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        with get_pool().connection() as c:
            return _hydrate(InviteRecord, c.execute(
                "SELECT * FROM invites WHERE token_hash = %s", (token_hash,)).fetchone())

    def get_invite(self, invite_id: str) -> InviteRecord | None:
        with get_pool().connection() as c:
            return _hydrate(InviteRecord, c.execute(
                "SELECT * FROM invites WHERE id = %s", (invite_id,)).fetchone())

    def list_open_invites(self) -> list[InviteRecord]:
        with get_pool().connection() as c:
            return _all(InviteRecord, c.execute(
                """SELECT * FROM invites
                   WHERE accepted_at IS NULL AND expires_at > %s
                   ORDER BY created_at DESC""",
                (utcnow(),)).fetchall())

    def create_invite(self, invite: InviteRecord) -> InviteRecord:
        invite.email = invite.email.lower()
        with get_pool().connection() as c:
            c.execute(
                """INSERT INTO invites (id, email, role, token_hash, created_by,
                       expires_at, accepted_at, created_at)
                   VALUES (%(id)s, %(email)s, %(role)s, %(token_hash)s, %(created_by)s,
                       %(expires_at)s, %(accepted_at)s, %(created_at)s)""",
                invite.__dict__,
            )
        return invite

    def save_invite(self, invite: InviteRecord) -> None:
        with get_pool().connection() as c:
            c.execute(
                """UPDATE invites SET email=%(email)s, role=%(role)s,
                       token_hash=%(token_hash)s, expires_at=%(expires_at)s,
                       accepted_at=%(accepted_at)s
                   WHERE id=%(id)s""",
                invite.__dict__,
            )

    def delete_invite(self, invite_id: str) -> None:
        with get_pool().connection() as c:
            c.execute("DELETE FROM invites WHERE id = %s", (invite_id,))

    def delete_invites_for_email(self, email: str) -> None:
        with get_pool().connection() as c:
            c.execute("DELETE FROM invites WHERE lower(email) = lower(%s)", (email,))

    # ------------------------------------------------------------ documents

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with get_pool().connection() as c:
            return _hydrate(DocumentRecord, c.execute(
                "SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone())

    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents"
        if not include_inactive:
            sql += " WHERE is_active"
        sql += " ORDER BY created_at DESC"
        with get_pool().connection() as c:
            return _all(DocumentRecord, c.execute(sql).fetchall())

    def find_active_document_by_checksum(self, checksum: str) -> DocumentRecord | None:
        with get_pool().connection() as c:
            return _hydrate(DocumentRecord, c.execute(
                "SELECT * FROM documents WHERE checksum = %s AND is_active LIMIT 1",
                (checksum,)).fetchone())

    def create_document(self, doc: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        with get_pool().connection() as c, c.transaction():
            c.execute(
                """INSERT INTO documents (id, title, filename, content_type, category,
                       visibility, version, is_active, checksum, size_bytes, char_count,
                       chunk_count, pii_flags, uploaded_by, created_at, updated_at)
                   VALUES (%(id)s, %(title)s, %(filename)s, %(content_type)s, %(category)s,
                       %(visibility)s, %(version)s, %(is_active)s, %(checksum)s,
                       %(size_bytes)s, %(char_count)s, %(chunk_count)s, %(pii_flags)s,
                       %(uploaded_by)s, %(created_at)s, %(updated_at)s)""",
                doc.__dict__,
            )
            if chunks:
                # executemany on one statement: 645 chunks is a single round
                # trip, and the generated tsvector is computed server-side.
                with c.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO chunks (id, document_id, ordinal, heading, page,
                               text, document_title, category, visibility, document_active)
                           VALUES (%(id)s, %(document_id)s, %(ordinal)s, %(heading)s,
                               %(page)s, %(text)s, %(document_title)s, %(category)s,
                               %(visibility)s, %(document_active)s)""",
                        [ch.__dict__ for ch in chunks],
                    )

    def update_document(self, doc: DocumentRecord) -> None:
        doc.updated_at = utcnow()
        with get_pool().connection() as c, c.transaction():
            c.execute(
                """UPDATE documents SET title=%(title)s, category=%(category)s,
                       visibility=%(visibility)s, is_active=%(is_active)s,
                       version=%(version)s, chunk_count=%(chunk_count)s,
                       pii_flags=%(pii_flags)s, updated_at=%(updated_at)s
                   WHERE id=%(id)s""",
                doc.__dict__,
            )
            # The denormalised copies on every chunk have to follow, or
            # retrieval keeps filtering on the old visibility.
            c.execute(
                """UPDATE chunks SET document_title=%s, category=%s, visibility=%s,
                       document_active=%s
                   WHERE document_id=%s""",
                (doc.title, doc.category, doc.visibility, doc.is_active, doc.id),
            )

    def delete_document(self, document_id: str) -> None:
        # Chunks no longer reference documents (see schema.sql), so they are
        # removed explicitly; document_blobs still cascades.
        with get_pool().connection() as c, c.transaction():
            c.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            c.execute("DELETE FROM documents WHERE id = %s", (document_id,))

    def count_active_documents(self) -> int:
        # Counted from the search copy so it holds whether document metadata
        # lives in this database or in GitHub.
        with get_pool().connection() as c:
            return c.execute(
                "SELECT count(DISTINCT document_id) AS n FROM chunks WHERE document_active"
            ).fetchone()["n"]

    # ------------------------------------------- search copy (GitHub mode)
    # When documents live in GitHub, these are the only document writes this
    # database sees: passages keyed by document id, with no documents row.

    def ensure_search_copy_schema(self) -> None:
        with get_pool().connection() as c:
            c.execute("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_id_fkey")

    def put_chunks(self, document_id: str, chunks: list[ChunkRecord]) -> None:
        with get_pool().connection() as c, c.transaction():
            c.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            if chunks:
                with c.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO chunks (id, document_id, ordinal, heading, page,
                               text, document_title, category, visibility, document_active)
                           VALUES (%(id)s, %(document_id)s, %(ordinal)s, %(heading)s,
                               %(page)s, %(text)s, %(document_title)s, %(category)s,
                               %(visibility)s, %(document_active)s)""",
                        [ch.__dict__ for ch in chunks],
                    )

    def set_chunks_meta(
        self, document_id: str, title: str, category: str, visibility: str, active: bool
    ) -> None:
        with get_pool().connection() as c:
            c.execute(
                """UPDATE chunks SET document_title=%s, category=%s, visibility=%s,
                       document_active=%s
                   WHERE document_id=%s""",
                (title, category, visibility, active, document_id),
            )

    def delete_chunks(self, document_id: str) -> None:
        with get_pool().connection() as c:
            c.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))

    def storage_bytes(self) -> int:
        """The whole database: every table, index and system catalog."""
        with get_pool().connection() as c:
            return c.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]

    _STORAGE_GROUPS = {
        "documents": ("documents", "document_blobs", "chunks"),
        "users": ("users", "invites", "query_counters"),
        # Left over from before chat history went session-only. Nothing writes
        # these any more; the line disappears (0 bytes) once they are dropped.
        "old chat history": ("conversations", "messages"),
        "audit log": ("audit",),
    }

    def storage_breakdown(self) -> dict[str, int]:
        """Bytes per area, tables plus their indexes. Whatever the database
        uses beyond these tables — Postgres's own catalogs, about 8 MB and
        fixed — is reported as "system" so the parts add up to storage_bytes."""
        with get_pool().connection() as c:
            rows = c.execute(
                """SELECT c.relname AS name, pg_total_relation_size(c.oid) AS n
                   FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
                   WHERE c.relkind = 'r' AND ns.nspname = current_schema()"""
            ).fetchall()
        sizes = {r["name"]: r["n"] for r in rows}
        out = {
            group: sum(sizes.pop(t, 0) for t in tables)
            for group, tables in self._STORAGE_GROUPS.items()
        }
        out["system"] = max(0, self.storage_bytes() - sum(out.values()))
        return out

    def chunk_document_ids(self) -> set[str]:
        with get_pool().connection() as c:
            rows = c.execute("SELECT DISTINCT document_id FROM chunks").fetchall()
        return {r["document_id"] for r in rows}

    # --------------------------------------------------------------- chunks

    def iter_active_chunks(self) -> list[ChunkRecord]:
        with get_pool().connection() as c:
            return _all(ChunkRecord, c.execute(
                """SELECT id, document_id, ordinal, heading, page, text,
                          document_title, category, visibility, document_active
                   FROM chunks WHERE document_active ORDER BY document_id, ordinal"""
            ).fetchall())

    def count_active_chunks(self) -> int:
        """Used by the index for its readiness report. A COUNT, rather than
        pulling 645 rows across the wire just to call len() on them."""
        with get_pool().connection() as c:
            return c.execute(
                "SELECT count(*) AS n FROM chunks WHERE document_active").fetchone()["n"]

    # Two queries, strict then relaxed. websearch_to_tsquery ANDs every term,
    # which is right when the phrasing matches the document and catastrophic
    # when it does not: "how many face-to-face contacts a month do we need
    # with each child" returned nothing, because one word of the eleven was
    # absent, even though the passage answering it was in the corpus.
    #
    # Casting the parsed query to text and swapping & for | relaxes it to OR
    # while keeping everything websearch_to_tsquery already did correctly —
    # stemming, stopwords, quoted phrases (<-> survives the swap). Ranking
    # then does the work BM25 used to: a chunk matching more of the question
    # scores above one matching less.
    # Scored by term coverage, not by ts_rank alone.
    #
    # ts_rank_cd ranks a chunk highly for matching one common word often,
    # which is fine under AND semantics and badly wrong under OR: relaxing the
    # query put an irrelevant "PBP Score Report Dispute Procedure" passage at
    # 0.91 for a question about incident reports, purely on the word "report".
    #
    # coverage is the fraction of the question's own lexemes that appear in
    # the chunk, so it means something a person can check: 1.0 is "every word
    # you asked about is in this passage", 0.25 is "one word in four". That is
    # the number the refusal logic and the citations are better off reading.
    # ts_rank_cd stays as the tie-break, where density is the right signal.
    #
    # The INTERSECT runs per surviving row rather than through the GIN index.
    # At 645 chunks that is immaterial; past roughly 100k it would need to
    # become a two-stage query (index-narrowed candidates, then rescored).
    # Must match the chunks_fts_idx expression in schema.sql character for
    # character, or the planner falls back to a sequential scan.
    SEARCH_VECTOR = (
        "(setweight(to_tsvector('english'::regconfig, coalesce(c.heading, '')), 'B') || "
        "setweight(to_tsvector('english'::regconfig, coalesce(c.text, '')), 'A'))"
    )

    _SEARCH_SQL = """
        WITH q AS (
            SELECT {query_expr} AS tsq,
                   tsvector_to_array(to_tsvector('english', %(q)s)) AS terms
        )
        SELECT c.id, c.document_id, c.ordinal, c.heading, c.page, c.text,
               c.document_title, c.category, c.visibility, c.document_active,
               CASE WHEN cardinality(q.terms) = 0 THEN 0::float8
                    ELSE cardinality(ARRAY(
                             SELECT unnest(tsvector_to_array({vec}))
                             INTERSECT
                             SELECT unnest(q.terms)
                         ))::float8 / cardinality(q.terms)
               END AS score,
               ts_rank_cd({vec}, q.tsq, 32) AS density
        FROM chunks c, q
        WHERE c.document_active
          AND c.visibility = ANY(%(vis)s)
          AND {vec} @@ q.tsq
        ORDER BY score DESC, density DESC
        LIMIT %(lim)s
    """

    _STRICT = "websearch_to_tsquery('english', %(q)s)"
    _RELAXED = "replace(websearch_to_tsquery('english', %(q)s)::text, '&', '|')::tsquery"

    def search_chunks(
        self, query: str, visibilities: list[str], limit: int = 8
    ) -> list[tuple[ChunkRecord, float]]:
        """Full-text retrieval, ranked, filtered by visibility.

        Not part of the Repo protocol — it is the Postgres-native replacement
        for the in-memory BM25 + LSA index, which needed 358 MB of scientific
        Python and rebuilt itself on every cold start.

        ts_rank_cd with normalisation 32 divides by (rank + 1), bounding the
        score into [0, 1). The previous fused BM25/LSA score was unbounded and
        uncalibrated — an off-corpus question once outscored a real one.
        """
        if not visibilities or not query.strip():
            return []
        params = {"q": query, "vis": list(visibilities), "lim": limit}
        with get_pool().connection() as c:
            rows = c.execute(
                self._SEARCH_SQL.format(query_expr=self._STRICT, vec=self.SEARCH_VECTOR), params).fetchall()
            if not rows:
                rows = c.execute(
                    self._SEARCH_SQL.format(query_expr=self._RELAXED, vec=self.SEARCH_VECTOR), params).fetchall()
        out: list[tuple[ChunkRecord, float]] = []
        for row in rows:
            score = float(row.pop("score") or 0.0)
            row.pop("density", None)
            chunk = _hydrate(ChunkRecord, row)
            if chunk is not None:
                out.append((chunk, score))
        return out

    # ---------------------------------------------------------------- audit

    def append_audit(self, entry: AuditEntry) -> None:
        with get_pool().connection() as c:
            c.execute(
                """INSERT INTO audit (id, at, user_id, user_email, action, target, detail, ip)
                   VALUES (%(id)s, %(at)s, %(user_id)s, %(user_email)s, %(action)s,
                       %(target)s, %(detail)s, %(ip)s)""",
                entry.__dict__,
            )

    def list_audit(self, limit: int = 200, action: str = "") -> list[AuditEntry]:
        sql = "SELECT * FROM audit"
        params: list[Any] = []
        if action:
            sql += " WHERE action = %s"
            params.append(action)
        sql += " ORDER BY at DESC LIMIT %s"
        params.append(limit)
        with get_pool().connection() as c:
            return _all(AuditEntry, c.execute(sql, params).fetchall())

    # ----------------------------------------------------------- statistics

    def count_questions_since(self, since: datetime, escalated: bool) -> int:
        """Answered vs. escalated questions, read from the audit log — chat
        history itself is session-only and never reaches this database."""
        action = "question_escalated" if escalated else "question_answered"
        with get_pool().connection() as c:
            return c.execute(
                "SELECT count(*) AS n FROM audit WHERE action = %s AND at >= %s",
                (action, since)).fetchone()["n"]

    def coverage_gaps(self, since: datetime, limit: int = 15) -> list[tuple[str, int]]:
        """What staff keep asking that the library does not answer.

        One GROUP BY, where Firestore needed a full scan and a Python tally.
        The excluded reasons are the ones that say nothing about coverage: a
        blocked meta-query, a crash, or a safety refusal is not a gap in the
        documents.
        """
        with get_pool().connection() as c:
            rows = c.execute(
                """SELECT target, count(*) AS n FROM audit
                   WHERE action = 'question_escalated'
                     AND at >= %s
                     AND target <> ''
                     AND detail NOT LIKE '%%meta_query%%'
                     AND detail NOT LIKE '%%error%%'
                     AND detail NOT LIKE '%%safety_refusal%%'
                     AND detail NOT LIKE '%%out_of_scope%%'
                   GROUP BY target ORDER BY n DESC LIMIT %s""",
                (since, limit)).fetchall()
        return [(r["target"], r["n"]) for r in rows]

    # ----------------------------------------------------------- rate limit

    def bump_query_counter(self, user_id: str, hour_bucket: str, limit: int) -> bool:
        """Atomic. The SQLite version reads then writes, so two questions sent
        at once can both see count == limit-1 and both be allowed. Here the
        upsert and the check are one statement, and a row that is already at
        the cap updates nothing and returns no row."""
        with get_pool().connection() as c:
            row = c.execute(
                """INSERT INTO query_counters (user_id, hour_bucket, count)
                   VALUES (%s, %s, 1)
                   ON CONFLICT (user_id, hour_bucket) DO UPDATE
                       SET count = query_counters.count + 1
                       WHERE query_counters.count < %s
                   RETURNING count""",
                (user_id, hour_bucket, limit)).fetchone()
        return row is not None

    def get_query_counter(self, user_id: str, hour_bucket: str) -> int:
        with get_pool().connection() as c:
            row = c.execute(
                "SELECT count FROM query_counters WHERE user_id = %s AND hour_bucket = %s",
                (user_id, hour_bucket)).fetchone()
        return row["count"] if row else 0

    # ------------------------------------------------------------ lifecycle

    def bootstrap(self) -> None:
        ddl = (Path(__file__).parent / "schema.sql").read_text()
        with get_pool().connection() as c:
            had_stored_vector = c.execute(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'chunks' AND column_name = 'search_vector'"""
            ).fetchone() is not None
            c.execute(ddl)
        if had_stored_vector:
            # Dropping a column leaves its bytes in every row until the table
            # is rewritten. Once, on the upgrade: chunks is small and the lock
            # lasts well under a second.
            with get_pool().connection() as c:  # pool connections autocommit
                c.execute("VACUUM FULL chunks")
        type(self)._schema_current = True

    _schema_current = False

    def upgrade_if_needed(self) -> None:
        """Production sets SKIP_BOOTSTRAP, so a schema change would never reach
        it. Document uploads, deletes and the storage meter call this instead:
        one cheap lookup, and the full bootstrap only on a database still in
        the old layout. Remembered per process after the first check."""
        if type(self)._schema_current:
            return
        with get_pool().connection() as c:
            stale = c.execute(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'chunks' AND column_name = 'search_vector'"""
            ).fetchone() is not None
        if stale:
            self.bootstrap()
        type(self)._schema_current = True

    # ------------------------------------------------- document bytes (blobs)

    def put_blob(self, document_id: str, content: bytes) -> None:
        with get_pool().connection() as c:
            c.execute(
                """INSERT INTO document_blobs (document_id, content) VALUES (%s, %s)
                   ON CONFLICT (document_id) DO UPDATE SET content = EXCLUDED.content""",
                (document_id, content))

    def get_blob(self, document_id: str) -> bytes | None:
        with get_pool().connection() as c:
            row = c.execute(
                "SELECT content FROM document_blobs WHERE document_id = %s",
                (document_id,)).fetchone()
        return bytes(row["content"]) if row else None

    def delete_blob(self, document_id: str) -> None:
        with get_pool().connection() as c:
            c.execute("DELETE FROM document_blobs WHERE document_id = %s", (document_id,))

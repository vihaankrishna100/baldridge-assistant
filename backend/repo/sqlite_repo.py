"""SQLite-backed store, wrapping the existing SQLAlchemy models.

Kept as a first-class implementation rather than legacy: it needs no cloud
account, so the test suite runs against it and thereby exercises every route
above this layer for real.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

import models as m
from database import Base, SessionLocal, engine, run_migrations

from .base import (
    AuditEntry,
    ChunkRecord,
    DocumentRecord,
    EmailTaken,
    InviteRecord,
    UserRecord,
    as_naive_utc,
)


def _user(row: m.User) -> UserRecord:
    return UserRecord(
        id=row.id, email=row.email, full_name=row.full_name,
        password_hash=row.password_hash, role=row.role,
        totp_secret=row.totp_secret, totp_confirmed=row.totp_confirmed,
        is_active=row.is_active, must_change_password=row.must_change_password,
        failed_logins=row.failed_logins,
        locked_until=as_naive_utc(row.locked_until),
        last_login_at=as_naive_utc(row.last_login_at),
        created_at=as_naive_utc(row.created_at), token_epoch=row.token_epoch,
    )


def _invite(row: m.Invite) -> InviteRecord:
    return InviteRecord(
        id=row.id, email=row.email, role=row.role, token_hash=row.token_hash,
        created_by=row.created_by, expires_at=as_naive_utc(row.expires_at),
        accepted_at=as_naive_utc(row.accepted_at),
        created_at=as_naive_utc(row.created_at),
    )


def _document(row: m.Document) -> DocumentRecord:
    return DocumentRecord(
        id=row.id, title=row.title, filename=row.filename,
        content_type=row.content_type, category=row.category,
        visibility=row.visibility, version=row.version, is_active=row.is_active,
        checksum=row.checksum, size_bytes=row.size_bytes,
        char_count=row.char_count, chunk_count=row.chunk_count,
        pii_flags=row.pii_flags, uploaded_by=row.uploaded_by,
        created_at=as_naive_utc(row.created_at),
        updated_at=as_naive_utc(row.updated_at),
    )


def _audit(row: m.AuditLog) -> AuditEntry:
    return AuditEntry(
        id=str(row.id), at=as_naive_utc(row.at), user_id=row.user_id,
        user_email=row.user_email, action=row.action, target=row.target,
        detail=row.detail, ip=row.ip,
    )


class SqliteRepo:
    # ---------------------------------------------------------------- users

    def get_user(self, user_id: str) -> UserRecord | None:
        with SessionLocal() as s:
            row = s.get(m.User, user_id)
            return _user(row) if row else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with SessionLocal() as s:
            row = s.query(m.User).filter(m.User.email == email.lower()).one_or_none()
            return _user(row) if row else None

    def list_users(self) -> list[UserRecord]:
        with SessionLocal() as s:
            return [_user(r) for r in s.query(m.User).order_by(m.User.created_at).all()]

    def create_user(self, user: UserRecord) -> UserRecord:
        user.email = user.email.lower()
        with SessionLocal() as s:
            if s.query(m.User).filter(m.User.email == user.email).one_or_none():
                raise EmailTaken(user.email)
            s.add(m.User(
                id=user.id, email=user.email, full_name=user.full_name,
                password_hash=user.password_hash, role=user.role,
                totp_secret=user.totp_secret, totp_confirmed=user.totp_confirmed,
                is_active=user.is_active, must_change_password=user.must_change_password,
                failed_logins=user.failed_logins, locked_until=user.locked_until,
                last_login_at=user.last_login_at, created_at=user.created_at,
                token_epoch=user.token_epoch,
            ))
            s.commit()
        return user

    def save_user(self, user: UserRecord) -> None:
        with SessionLocal() as s:
            row = s.get(m.User, user.id)
            if row is None:
                return
            for key in ("email", "full_name", "password_hash", "role", "totp_secret",
                        "totp_confirmed", "is_active", "must_change_password",
                        "failed_logins", "locked_until", "last_login_at", "token_epoch"):
                setattr(row, key, getattr(user, key))
            s.commit()

    def delete_user(self, user_id: str) -> None:
        with SessionLocal() as s:
            row = s.get(m.User, user_id)
            if row:
                s.delete(row)
                s.commit()

    def count_active_users(self) -> int:
        with SessionLocal() as s:
            return s.query(func.count(m.User.id)).filter(m.User.is_active.is_(True)).scalar() or 0

    # -------------------------------------------------------------- invites

    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        with SessionLocal() as s:
            row = s.query(m.Invite).filter(m.Invite.token_hash == token_hash).one_or_none()
            return _invite(row) if row else None

    def get_invite(self, invite_id: str) -> InviteRecord | None:
        with SessionLocal() as s:
            row = s.get(m.Invite, invite_id)
            return _invite(row) if row else None

    def list_open_invites(self) -> list[InviteRecord]:
        with SessionLocal() as s:
            rows = (s.query(m.Invite).filter(m.Invite.accepted_at.is_(None))
                    .order_by(m.Invite.created_at.desc()).all())
            return [_invite(r) for r in rows]

    def create_invite(self, invite: InviteRecord) -> InviteRecord:
        with SessionLocal() as s:
            s.add(m.Invite(
                id=invite.id, email=invite.email, role=invite.role,
                token_hash=invite.token_hash, created_by=invite.created_by,
                expires_at=invite.expires_at, accepted_at=invite.accepted_at,
                created_at=invite.created_at,
            ))
            s.commit()
        return invite

    def save_invite(self, invite: InviteRecord) -> None:
        with SessionLocal() as s:
            row = s.get(m.Invite, invite.id)
            if row:
                row.accepted_at = invite.accepted_at
                s.commit()

    def delete_invite(self, invite_id: str) -> None:
        with SessionLocal() as s:
            row = s.get(m.Invite, invite_id)
            if row:
                s.delete(row)
                s.commit()

    def delete_invites_for_email(self, email: str) -> None:
        with SessionLocal() as s:
            s.query(m.Invite).filter(m.Invite.email == email.lower()).delete()
            s.commit()

    # ------------------------------------------------------------ documents

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with SessionLocal() as s:
            row = s.get(m.Document, document_id)
            return _document(row) if row else None

    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]:
        with SessionLocal() as s:
            q = s.query(m.Document)
            if not include_inactive:
                q = q.filter(m.Document.is_active.is_(True))
            rows = q.order_by(m.Document.category, m.Document.title).all()
            return [_document(r) for r in rows]

    def find_active_document_by_checksum(self, checksum: str) -> DocumentRecord | None:
        with SessionLocal() as s:
            row = (s.query(m.Document)
                   .filter(m.Document.checksum == checksum, m.Document.is_active.is_(True))
                   .first())
            return _document(row) if row else None

    def create_document(self, doc: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        with SessionLocal() as s:
            s.add(m.Document(
                id=doc.id, title=doc.title, filename=doc.filename,
                content_type=doc.content_type, category=doc.category,
                visibility=doc.visibility, version=doc.version,
                is_active=doc.is_active, checksum=doc.checksum,
                size_bytes=doc.size_bytes, char_count=doc.char_count,
                chunk_count=doc.chunk_count, pii_flags=doc.pii_flags,
                uploaded_by=doc.uploaded_by, created_at=doc.created_at,
                updated_at=doc.updated_at,
            ))
            for c in chunks:
                s.add(m.Chunk(id=c.id, document_id=c.document_id, ordinal=c.ordinal,
                              heading=c.heading, page=c.page, text=c.text))
            s.commit()

    def update_document(self, doc: DocumentRecord) -> None:
        with SessionLocal() as s:
            row = s.get(m.Document, doc.id)
            if row is None:
                return
            for key in ("title", "category", "visibility", "is_active", "updated_at"):
                setattr(row, key, getattr(doc, key))
            s.commit()

    def delete_document(self, document_id: str) -> None:
        with SessionLocal() as s:
            row = s.get(m.Document, document_id)
            if row:
                s.delete(row)  # chunks cascade
                s.commit()

    def count_active_documents(self) -> int:
        with SessionLocal() as s:
            return (s.query(func.count(m.Document.id))
                    .filter(m.Document.is_active.is_(True)).scalar() or 0)

    # --------------------------------------------------------------- chunks

    def iter_active_chunks(self) -> list[ChunkRecord]:
        with SessionLocal() as s:
            rows = (s.query(m.Chunk, m.Document)
                    .join(m.Document, m.Chunk.document_id == m.Document.id)
                    .filter(m.Document.is_active.is_(True)).all())
            return [
                ChunkRecord(
                    id=c.id, document_id=d.id, ordinal=c.ordinal, heading=c.heading,
                    page=c.page, text=c.text, document_title=d.title,
                    category=d.category, visibility=d.visibility, document_active=True,
                )
                for c, d in rows
            ]

    # ---------------------------------------------------------------- audit

    def append_audit(self, entry: AuditEntry) -> None:
        with SessionLocal() as s:
            s.add(m.AuditLog(
                at=entry.at, user_id=entry.user_id, user_email=entry.user_email,
                action=entry.action, target=entry.target, detail=entry.detail, ip=entry.ip,
            ))
            s.commit()

    def list_audit(self, limit: int = 200, action: str = "") -> list[AuditEntry]:
        with SessionLocal() as s:
            q = s.query(m.AuditLog)
            if action:
                q = q.filter(m.AuditLog.action == action)
            rows = q.order_by(m.AuditLog.at.desc()).limit(limit).all()
            return [_audit(r) for r in rows]

    def delete_audit_before(self, cutoff: datetime | None) -> int:
        """Removes audit rows older than cutoff, or every row when None."""
        with SessionLocal() as s:
            q = s.query(m.AuditLog)
            if cutoff is not None:
                q = q.filter(m.AuditLog.at < cutoff)
            n = q.delete(synchronize_session=False)
            s.commit()
            return n

    def get_setting(self, key: str) -> str | None:
        with SessionLocal() as s:
            row = s.get(m.AppSetting, key)
            return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        with SessionLocal() as s:
            s.merge(m.AppSetting(key=key, value=value))
            s.commit()

    # ----------------------------------------------------------- statistics

    def count_questions_since(self, since: datetime, escalated: bool) -> int:
        """Answered vs. escalated questions, read from the audit log — chat
        history itself is session-only and never reaches this database."""
        action = "question_escalated" if escalated else "question_answered"
        with SessionLocal() as s:
            return (s.query(func.count(m.AuditLog.id))
                    .filter(m.AuditLog.action == action,
                            m.AuditLog.at >= since).scalar() or 0)

    def coverage_gaps(self, since: datetime, limit: int = 15) -> list[tuple[str, int]]:
        with SessionLocal() as s:
            rows = (s.query(m.AuditLog.target, func.count(m.AuditLog.id))
                    .filter(m.AuditLog.action == "question_escalated",
                            m.AuditLog.at >= since,
                            m.AuditLog.detail.notlike("%meta_query%"),
                            m.AuditLog.detail.notlike("%error%"),
                            m.AuditLog.detail.notlike("%safety_refusal%"),
                            m.AuditLog.detail.notlike("%out_of_scope%"))
                    .group_by(m.AuditLog.target)
                    .order_by(func.count(m.AuditLog.id).desc())
                    .limit(limit).all())
            return [(t, n) for t, n in rows if t]

    # ----------------------------------------------------------- rate limit

    def bump_query_counter(self, user_id: str, hour_bucket: str, limit: int) -> bool:
        with SessionLocal() as s:
            row = (s.query(m.QueryCounter)
                   .filter(m.QueryCounter.user_id == user_id,
                           m.QueryCounter.hour_bucket == hour_bucket).one_or_none())
            if row is None:
                row = m.QueryCounter(user_id=user_id, hour_bucket=hour_bucket, count=0)
                s.add(row)
            if row.count >= limit:
                return False
            row.count += 1
            s.commit()
            return True

    def get_query_counter(self, user_id: str, hour_bucket: str) -> int:
        with SessionLocal() as s:
            row = (s.query(m.QueryCounter)
                   .filter(m.QueryCounter.user_id == user_id,
                           m.QueryCounter.hour_bucket == hour_bucket).one_or_none())
            return row.count if row else 0

    # ------------------------------------------------------------ lifecycle

    def bootstrap(self) -> None:
        Base.metadata.create_all(bind=engine)
        run_migrations()

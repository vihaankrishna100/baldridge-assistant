"""Entities and the storage interface.

The entities are plain dataclasses rather than ORM objects on purpose: a route
holding one of these cannot lazy-load a relationship, so it cannot behave
differently depending on which backend produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Naive UTC. Firestore hands back tz-aware datetimes and SQLite naive
    ones; everything is normalised to naive UTC at the boundary so comparisons
    never raise."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass
class UserRecord:
    id: str = field(default_factory=new_id)
    email: str = ""
    full_name: str = ""
    password_hash: str = ""
    role: str = "staff"
    totp_secret: str | None = None
    totp_confirmed: bool = False
    is_active: bool = True
    must_change_password: bool = False
    failed_logins: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    token_epoch: int = 1


@dataclass
class InviteRecord:
    id: str = field(default_factory=new_id)
    email: str = ""
    role: str = "staff"
    token_hash: str = ""
    created_by: str = ""
    expires_at: datetime = field(default_factory=utcnow)
    accepted_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class DocumentRecord:
    id: str = field(default_factory=new_id)
    title: str = ""
    filename: str = ""
    content_type: str = ""
    category: str = "General"
    visibility: str = "staff"
    version: int = 1
    is_active: bool = True
    checksum: str = ""
    size_bytes: int = 0
    char_count: int = 0
    chunk_count: int = 0
    pii_flags: str = ""
    uploaded_by: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ChunkRecord:
    """Document fields are denormalised onto the chunk.

    Firestore has no joins, and the retrieval index needs title/category/
    visibility for every chunk at startup. Copying them here turns index
    construction into a single collection scan instead of 645 lookups.
    Whoever changes a document's title or visibility must rewrite its chunks —
    `Repo.update_document` handles that.
    """

    id: str = field(default_factory=new_id)
    document_id: str = ""
    ordinal: int = 0
    heading: str = ""
    page: int | None = None
    text: str = ""
    document_title: str = ""
    category: str = "General"
    visibility: str = "staff"
    document_active: bool = True


@dataclass
class ConversationRecord:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    title: str = "New question"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class MessageRecord:
    id: str = field(default_factory=new_id)
    conversation_id: str = ""
    role: str = "user"
    content: str = ""
    answered: bool = True
    escalated: bool = False
    escalation_reason: str = ""
    citations_json: str = "[]"
    top_score: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class AuditEntry:
    id: str = field(default_factory=new_id)
    at: datetime = field(default_factory=utcnow)
    user_id: str | None = None
    user_email: str = ""
    action: str = ""
    target: str = ""
    detail: str = ""
    ip: str = ""


class EmailTaken(Exception):
    """Raised instead of relying on a unique index, which Firestore lacks."""


class Repo(Protocol):
    # ---------------------------------------------------------------- users
    def get_user(self, user_id: str) -> UserRecord | None: ...
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def list_users(self) -> list[UserRecord]: ...
    def create_user(self, user: UserRecord) -> UserRecord:
        """Raises EmailTaken if the address already exists."""
        ...
    def save_user(self, user: UserRecord) -> None: ...
    def delete_user(self, user_id: str) -> None: ...
    def count_active_users(self) -> int: ...

    # -------------------------------------------------------------- invites
    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None: ...
    def get_invite(self, invite_id: str) -> InviteRecord | None: ...
    def list_open_invites(self) -> list[InviteRecord]: ...
    def create_invite(self, invite: InviteRecord) -> InviteRecord: ...
    def save_invite(self, invite: InviteRecord) -> None: ...
    def delete_invite(self, invite_id: str) -> None: ...
    def delete_invites_for_email(self, email: str) -> None: ...

    # ------------------------------------------------------------ documents
    def get_document(self, document_id: str) -> DocumentRecord | None: ...
    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]: ...
    def find_active_document_by_checksum(self, checksum: str) -> DocumentRecord | None: ...
    def create_document(self, doc: DocumentRecord, chunks: list[ChunkRecord]) -> None: ...
    def update_document(self, doc: DocumentRecord) -> None:
        """Persists the document and re-syncs the denormalised chunk fields."""
        ...
    def delete_document(self, document_id: str) -> None:
        """Deletes the document and every chunk belonging to it."""
        ...
    def count_active_documents(self) -> int: ...

    # --------------------------------------------------------------- chunks
    def iter_active_chunks(self) -> list[ChunkRecord]:
        """Every chunk of every active document — the retrieval index input."""
        ...

    # -------------------------------------------------------- conversations
    def get_conversation(self, conversation_id: str) -> ConversationRecord | None: ...
    def list_conversations(self, user_id: str, limit: int = 50) -> list[ConversationRecord]: ...
    def create_conversation(self, conversation: ConversationRecord) -> ConversationRecord: ...
    def save_conversation(self, conversation: ConversationRecord) -> None: ...
    def delete_conversation(self, conversation_id: str) -> None: ...

    def list_messages(self, conversation_id: str) -> list[MessageRecord]: ...
    def add_message(self, message: MessageRecord) -> MessageRecord: ...

    # ---------------------------------------------------------------- audit
    def append_audit(self, entry: AuditEntry) -> None: ...
    def list_audit(self, limit: int = 200, action: str = "") -> list[AuditEntry]: ...

    # ----------------------------------------------------------- statistics
    def count_messages_since(self, since: datetime, escalated: bool) -> int: ...
    def coverage_gaps(self, since: datetime, limit: int = 15) -> list[tuple[str, int]]: ...

    # ----------------------------------------------------------- rate limit
    def bump_query_counter(self, user_id: str, hour_bucket: str, limit: int) -> bool:
        """Increments the bucket. Returns False when the caller is over `limit`."""
        ...

    def get_query_counter(self, user_id: str, hour_bucket: str) -> int:
        """Reads a bucket without changing it."""
        ...

    # ------------------------------------------------------------- lifecycle
    def bootstrap(self) -> None:
        """Create tables / warm clients. Safe to call repeatedly."""
        ...

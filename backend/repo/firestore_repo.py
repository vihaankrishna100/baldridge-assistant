"""Firestore-backed store.

Notes that matter when reading this:

* Firestore has no unique constraint, so `users` uniqueness is enforced with a
  companion `user_emails/{email}` document written in the same transaction.
* Firestore has no joins, so chunks carry a copy of their document's title,
  category and visibility. `update_document` re-syncs them.
* Firestore has no GROUP BY, so the coverage-gap tally happens in Python over a
  bounded query.
* Writes are batched at 450 (the hard cap is 500) because a 645-chunk upload
  would otherwise fail.
"""

from __future__ import annotations

import os
from dataclasses import asdict, fields
from datetime import datetime

from google.api_core import exceptions as gexc
from google.cloud import firestore

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
)

BATCH_LIMIT = 450


def _to_dict(record) -> dict:
    return asdict(record)


def _from_dict(cls, data: dict):
    """Tolerates documents written by an older version of the app: unknown keys
    are dropped, missing ones fall back to the dataclass default."""
    known = {f.name for f in fields(cls)}
    clean = {k: v for k, v in (data or {}).items() if k in known}
    for key, value in list(clean.items()):
        if isinstance(value, datetime):
            clean[key] = as_naive_utc(value)
    return cls(**clean)


class FirestoreRepo:
    def __init__(self, client: firestore.Client | None = None, prefix: str = ""):
        self.prefix = prefix or os.getenv("FIRESTORE_PREFIX", "")
        if client is not None:
            self._db = client
        else:
            project = os.getenv("FIRESTORE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
            database = os.getenv("FIRESTORE_DATABASE", "(default)")
            self._db = firestore.Client(project=project, database=database)

    def _col(self, name: str):
        return self._db.collection(f"{self.prefix}{name}")

    # ---------------------------------------------------------------- users

    def get_user(self, user_id: str) -> UserRecord | None:
        snap = self._col("users").document(user_id).get()
        return _from_dict(UserRecord, snap.to_dict()) if snap.exists else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        key = self._col("user_emails").document(email.lower()).get()
        if not key.exists:
            return None
        return self.get_user((key.to_dict() or {}).get("user_id", ""))

    def list_users(self) -> list[UserRecord]:
        users = [_from_dict(UserRecord, d.to_dict()) for d in self._col("users").stream()]
        return sorted(users, key=lambda u: u.created_at)

    def create_user(self, user: UserRecord) -> UserRecord:
        user.email = user.email.lower()
        email_ref = self._col("user_emails").document(user.email)
        user_ref = self._col("users").document(user.id)

        @firestore.transactional
        def _create(txn):
            # Reads must precede writes inside a Firestore transaction.
            if email_ref.get(transaction=txn).exists:
                raise EmailTaken(user.email)
            txn.set(user_ref, _to_dict(user))
            txn.set(email_ref, {"user_id": user.id})

        _create(self._db.transaction())
        return user

    def save_user(self, user: UserRecord) -> None:
        self._col("users").document(user.id).set(_to_dict(user))

    def delete_user(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        self._col("user_emails").document(user.email.lower()).delete()
        self._col("users").document(user_id).delete()

    def count_active_users(self) -> int:
        query = self._col("users").where(filter=firestore.FieldFilter("is_active", "==", True))
        return _count(query)

    # -------------------------------------------------------------- invites

    def get_invite_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        docs = list(
            self._col("invites")
            .where(filter=firestore.FieldFilter("token_hash", "==", token_hash))
            .limit(1)
            .stream()
        )
        return _from_dict(InviteRecord, docs[0].to_dict()) if docs else None

    def get_invite(self, invite_id: str) -> InviteRecord | None:
        snap = self._col("invites").document(invite_id).get()
        return _from_dict(InviteRecord, snap.to_dict()) if snap.exists else None

    def list_open_invites(self) -> list[InviteRecord]:
        rows = [
            _from_dict(InviteRecord, d.to_dict())
            for d in self._col("invites")
            .where(filter=firestore.FieldFilter("accepted_at", "==", None))
            .stream()
        ]
        return sorted(rows, key=lambda i: i.created_at, reverse=True)

    def create_invite(self, invite: InviteRecord) -> InviteRecord:
        self._col("invites").document(invite.id).set(_to_dict(invite))
        return invite

    def save_invite(self, invite: InviteRecord) -> None:
        self._col("invites").document(invite.id).set(_to_dict(invite))

    def delete_invite(self, invite_id: str) -> None:
        self._col("invites").document(invite_id).delete()

    def delete_invites_for_email(self, email: str) -> None:
        for doc in (
            self._col("invites")
            .where(filter=firestore.FieldFilter("email", "==", email.lower()))
            .stream()
        ):
            doc.reference.delete()

    # ------------------------------------------------------------ documents

    def get_document(self, document_id: str) -> DocumentRecord | None:
        snap = self._col("documents").document(document_id).get()
        return _from_dict(DocumentRecord, snap.to_dict()) if snap.exists else None

    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]:
        query = self._col("documents")
        if not include_inactive:
            query = query.where(filter=firestore.FieldFilter("is_active", "==", True))
        docs = [_from_dict(DocumentRecord, d.to_dict()) for d in query.stream()]
        return sorted(docs, key=lambda d: (d.category, d.title))

    def find_active_document_by_checksum(self, checksum: str) -> DocumentRecord | None:
        docs = list(
            self._col("documents")
            .where(filter=firestore.FieldFilter("checksum", "==", checksum))
            .where(filter=firestore.FieldFilter("is_active", "==", True))
            .limit(1)
            .stream()
        )
        return _from_dict(DocumentRecord, docs[0].to_dict()) if docs else None

    def create_document(self, doc: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        self._col("documents").document(doc.id).set(_to_dict(doc))
        self._write_chunks(chunks)

    def _write_chunks(self, chunks: list[ChunkRecord]) -> None:
        col = self._col("chunks")
        for start in range(0, len(chunks), BATCH_LIMIT):
            batch = self._db.batch()
            for chunk in chunks[start : start + BATCH_LIMIT]:
                batch.set(col.document(chunk.id), _to_dict(chunk))
            batch.commit()

    def update_document(self, doc: DocumentRecord) -> None:
        self._col("documents").document(doc.id).set(_to_dict(doc))
        # Keep the denormalised copies honest, or retrieval will filter on a
        # visibility the document no longer has.
        col = self._col("chunks")
        refs = [
            d.reference
            for d in col.where(filter=firestore.FieldFilter("document_id", "==", doc.id)).stream()
        ]
        patch = {
            "document_title": doc.title,
            "category": doc.category,
            "visibility": doc.visibility,
            "document_active": doc.is_active,
        }
        for start in range(0, len(refs), BATCH_LIMIT):
            batch = self._db.batch()
            for ref in refs[start : start + BATCH_LIMIT]:
                batch.update(ref, patch)
            batch.commit()

    def delete_document(self, document_id: str) -> None:
        col = self._col("chunks")
        refs = [
            d.reference
            for d in col.where(
                filter=firestore.FieldFilter("document_id", "==", document_id)
            ).stream()
        ]
        for start in range(0, len(refs), BATCH_LIMIT):
            batch = self._db.batch()
            for ref in refs[start : start + BATCH_LIMIT]:
                batch.delete(ref)
            batch.commit()
        self._col("documents").document(document_id).delete()

    def count_active_documents(self) -> int:
        query = self._col("documents").where(
            filter=firestore.FieldFilter("is_active", "==", True)
        )
        return _count(query)

    # --------------------------------------------------------------- chunks

    def iter_active_chunks(self) -> list[ChunkRecord]:
        return [
            _from_dict(ChunkRecord, d.to_dict())
            for d in self._col("chunks")
            .where(filter=firestore.FieldFilter("document_active", "==", True))
            .stream()
        ]

    # -------------------------------------------------------- conversations

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        snap = self._col("conversations").document(conversation_id).get()
        return _from_dict(ConversationRecord, snap.to_dict()) if snap.exists else None

    def list_conversations(self, user_id: str, limit: int = 50) -> list[ConversationRecord]:
        rows = [
            _from_dict(ConversationRecord, d.to_dict())
            for d in self._col("conversations")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .stream()
        ]
        rows.sort(key=lambda c: c.updated_at, reverse=True)
        return rows[:limit]

    def create_conversation(self, conversation: ConversationRecord) -> ConversationRecord:
        self._col("conversations").document(conversation.id).set(_to_dict(conversation))
        return conversation

    def save_conversation(self, conversation: ConversationRecord) -> None:
        self._col("conversations").document(conversation.id).set(_to_dict(conversation))

    def delete_conversation(self, conversation_id: str) -> None:
        for doc in (
            self._col("messages")
            .where(filter=firestore.FieldFilter("conversation_id", "==", conversation_id))
            .stream()
        ):
            doc.reference.delete()
        self._col("conversations").document(conversation_id).delete()

    def list_messages(self, conversation_id: str) -> list[MessageRecord]:
        rows = [
            _from_dict(MessageRecord, d.to_dict())
            for d in self._col("messages")
            .where(filter=firestore.FieldFilter("conversation_id", "==", conversation_id))
            .stream()
        ]
        return sorted(rows, key=lambda m: m.created_at)

    def add_message(self, message: MessageRecord) -> MessageRecord:
        self._col("messages").document(message.id).set(_to_dict(message))
        return message

    # ---------------------------------------------------------------- audit

    def append_audit(self, entry: AuditEntry) -> None:
        self._col("audit").document(entry.id).set(_to_dict(entry))

    def list_audit(self, limit: int = 200, action: str = "") -> list[AuditEntry]:
        query = self._col("audit")
        if action:
            query = query.where(filter=firestore.FieldFilter("action", "==", action))
        query = query.order_by("at", direction=firestore.Query.DESCENDING).limit(limit)
        return [_from_dict(AuditEntry, d.to_dict()) for d in query.stream()]

    # ----------------------------------------------------------- statistics

    def count_messages_since(self, since: datetime, escalated: bool) -> int:
        query = (
            self._col("messages")
            .where(filter=firestore.FieldFilter("role", "==", "assistant"))
            .where(filter=firestore.FieldFilter("escalated", "==", escalated))
            .where(filter=firestore.FieldFilter("created_at", ">=", since))
        )
        return _count(query)

    def coverage_gaps(self, since: datetime, limit: int = 15) -> list[tuple[str, int]]:
        rows = (
            self._col("audit")
            .where(filter=firestore.FieldFilter("action", "==", "question_escalated"))
            .where(filter=firestore.FieldFilter("at", ">=", since))
            .stream()
        )
        tally: dict[str, int] = {}
        for doc in rows:
            data = doc.to_dict() or {}
            detail = data.get("detail", "")
            # Mirrors the SQL exclusions: a blocked injection attempt or an API
            # outage is not a hole in the document library.
            if any(x in detail for x in ("meta_query", "error", "safety_refusal", "out_of_scope")):
                continue
            target = data.get("target", "")
            if target:
                tally[target] = tally.get(target, 0) + 1
        return sorted(tally.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    # ----------------------------------------------------------- rate limit

    def bump_query_counter(self, user_id: str, hour_bucket: str, limit: int) -> bool:
        ref = self._col("counters").document(f"{user_id}:{hour_bucket}")

        @firestore.transactional
        def _bump(txn) -> bool:
            snap = ref.get(transaction=txn)
            count = (snap.to_dict() or {}).get("count", 0) if snap.exists else 0
            if count >= limit:
                return False
            txn.set(ref, {"user_id": user_id, "hour_bucket": hour_bucket, "count": count + 1})
            return True

        return _bump(self._db.transaction())

    # ------------------------------------------------------------ lifecycle

    def bootstrap(self) -> None:
        # Firestore creates collections lazily; this just fails fast on bad
        # credentials rather than at the first user request.
        try:
            next(iter(self._col("users").limit(1).stream()), None)
        except gexc.GoogleAPIError as exc:
            raise RuntimeError(
                "Could not reach Firestore. Check FIRESTORE_PROJECT and that "
                "credentials are available (GOOGLE_APPLICATION_CREDENTIALS, or "
                "the service account attached to Cloud Run)."
            ) from exc


def _count(query) -> int:
    """Server-side aggregation — avoids reading every document just to size it."""
    result = query.count().get()
    return int(result[0][0].value)

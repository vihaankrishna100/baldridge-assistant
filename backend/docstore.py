"""Where documents live: their metadata and the original files.

GitHubDocStore keeps both in a GitHub repository â€” the files under
`<dir>/files/<id>/`, the metadata in `<dir>/manifest.json` â€” and every change
is a single commit made through the API. Documents belong to the organisation,
not to any account, so they live beside the code rather than in the user
database; the history of every policy version comes for free.

RepoDocStore keeps them in the database, as before. It is what runs when no
GitHub repository is configured: local development and the test suite.

Either way, the searchable passages are written to the database, because that
is where retrieval runs. In GitHub mode that copy is derived data: it can be
rebuilt from the repository at any time (POST /documents/reindex).
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from dataclasses import asdict, fields
from datetime import datetime
from typing import Callable

import httpx

from blobs import get_blobs
from config import settings
from repo import get_repo
from repo.base import ChunkRecord, DocumentRecord, utcnow


class DocStoreError(RuntimeError):
    pass


class DuplicateDocument(DocStoreError):
    def __init__(self, existing: DocumentRecord):
        super().__init__(existing.title)
        self.existing = existing


class DocumentMissing(DocStoreError):
    pass


# ------------------------------------------------------------------ database


class RepoDocStore:
    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]:
        return get_repo().list_documents(include_inactive=include_inactive)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return get_repo().get_document(document_id)

    def find_active_by_checksum(self, checksum: str) -> DocumentRecord | None:
        return get_repo().find_active_document_by_checksum(checksum)

    def publish(
        self,
        doc: DocumentRecord,
        data: bytes,
        chunks: list[ChunkRecord],
        previous: DocumentRecord | None,
    ) -> None:
        store = get_repo()
        # Record before bytes: Postgres keys document_blobs to documents(id).
        store.create_document(doc, chunks)
        try:
            get_blobs().put(doc.id, data)
        except Exception:
            store.delete_document(doc.id)
            raise
        # Retired only once the new version is stored, so a failed upload never
        # leaves the policy missing from search.
        if previous is not None:
            previous.is_active = False
            previous.updated_at = utcnow()
            store.update_document(previous)

    def update(self, doc: DocumentRecord) -> None:
        get_repo().update_document(doc)

    def delete(self, doc: DocumentRecord) -> None:
        get_blobs().delete(doc.id)
        get_repo().delete_document(doc.id)

    def get_bytes(self, doc: DocumentRecord) -> bytes | None:
        return get_blobs().get(doc.id)

    def restore_bytes(self, doc: DocumentRecord, data: bytes) -> None:
        get_blobs().put(doc.id, data)


# -------------------------------------------------------------------- GitHub

_API = "https://api.github.com"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_DOC_FIELDS = {f.name for f in fields(DocumentRecord)}


def _to_entry(doc: DocumentRecord) -> dict:
    entry = asdict(doc)
    entry["created_at"] = doc.created_at.isoformat()
    entry["updated_at"] = doc.updated_at.isoformat()
    return entry


def _from_entry(entry: dict) -> DocumentRecord:
    kw = {k: v for k, v in entry.items() if k in _DOC_FIELDS}
    for key in ("created_at", "updated_at"):
        if isinstance(kw.get(key), str):
            kw[key] = datetime.fromisoformat(kw[key])
    return DocumentRecord(**kw)


class GitHubDocStore:
    def __init__(
        self,
        repo: str,
        branch: str,
        directory: str,
        token: str,
        client: httpx.Client | None = None,
    ):
        self._repo = repo
        self._branch = branch
        self._dir = directory.strip("/") or "documents"
        self._http = client or httpx.Client(
            base_url=_API,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "baldridge-assistant",
            },
        )
        self._lock = threading.Lock()
        self._cache: tuple[str, list[dict]] | None = None  # (etag, entries)
        self._search_schema_ready = False

    # ------------------------------------------------------------ paths

    @property
    def manifest_path(self) -> str:
        return f"{self._dir}/manifest.json"

    def file_path(self, doc: DocumentRecord) -> str:
        name = _SAFE_NAME.sub("_", doc.filename).strip("._") or "file"
        return f"{self._dir}/files/{doc.id}/{name}"

    # ------------------------------------------------------------ HTTP

    def _call(self, method: str, url: str, ok: tuple[int, ...] = (200, 201), **kw) -> httpx.Response:
        r = self._http.request(method, f"/repos/{self._repo}{url}", **kw)
        if r.status_code not in ok:
            # The body can echo the request path but never the token.
            raise DocStoreError(f"GitHub {method} {url} -> {r.status_code}: {r.text[:300]}")
        return r

    def _fetch_manifest(self, ref: str | None = None) -> tuple[list[dict], bool]:
        """(entries, exists). With no ref, reads the branch tip through an ETag
        cache â€” a 304 costs nothing against the rate limit."""
        headers = {"Accept": "application/vnd.github.raw+json"}
        cached = self._cache if ref is None else None
        if cached:
            headers["If-None-Match"] = cached[0]
        r = self._call(
            "GET", f"/contents/{self.manifest_path}", ok=(200, 304, 404),
            params={"ref": ref or self._branch}, headers=headers,
        )
        if r.status_code == 304 and cached:
            return cached[1], True
        if r.status_code == 404:
            return [], False
        entries = json.loads(r.content).get("documents", [])
        if ref is None and r.headers.get("ETag"):
            with self._lock:
                self._cache = (r.headers["ETag"], entries)
        return entries, True

    def _entries(self) -> list[dict]:
        entries, exists = self._fetch_manifest()
        if not exists:
            entries = self._import_from_database()
        return entries

    def _commit(
        self,
        message: str,
        mutate: Callable[[list[dict]], list[dict]],
        files: dict[str, bytes] | None = None,
        deletes: tuple[str, ...] = (),
    ) -> list[dict]:
        """One atomic commit: new files, removed files, and the manifest as
        `mutate` leaves it. Retried from a fresh read if the branch moved."""
        blob_shas = {
            path: self._call(
                "POST", "/git/blobs",
                json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
            ).json()["sha"]
            for path, data in (files or {}).items()
        }
        for _ in range(4):
            head = self._call("GET", f"/git/ref/heads/{self._branch}").json()["object"]["sha"]
            base_tree = self._call("GET", f"/git/commits/{head}").json()["tree"]["sha"]
            current, _exists = self._fetch_manifest(ref=head)
            updated = mutate([dict(e) for e in current])

            manifest = json.dumps({"documents": updated}, indent=2, ensure_ascii=False) + "\n"
            tree = [
                {"path": p, "mode": "100644", "type": "blob", "sha": s}
                for p, s in blob_shas.items()
            ]
            tree.append({"path": self.manifest_path, "mode": "100644", "type": "blob", "content": manifest})
            tree += [{"path": p, "mode": "100644", "type": "blob", "sha": None} for p in deletes]

            new_tree = self._call("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree}).json()["sha"]
            commit = self._call(
                "POST", "/git/commits",
                json={"message": message, "tree": new_tree, "parents": [head]},
            ).json()["sha"]
            r = self._call(
                "PATCH", f"/git/refs/heads/{self._branch}", ok=(200, 422),
                json={"sha": commit, "force": False},
            )
            if r.status_code == 200:
                with self._lock:
                    self._cache = None
                return updated
            # 422: not a fast-forward â€” someone else committed. Go again.
        raise DocStoreError("The document repository kept changing; please try again.")

    def _search_copy(self):
        store = get_repo()
        if not self._search_schema_ready:
            store.ensure_search_copy_schema()
            self._search_schema_ready = True
        return store

    # ------------------------------------------------------------ reads

    def list_documents(self, include_inactive: bool = False) -> list[DocumentRecord]:
        docs = [_from_entry(e) for e in self._entries()]
        if not include_inactive:
            docs = [d for d in docs if d.is_active]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        for e in self._entries():
            if e.get("id") == document_id:
                return _from_entry(e)
        return None

    def find_active_by_checksum(self, checksum: str) -> DocumentRecord | None:
        for e in self._entries():
            if e.get("is_active") and e.get("checksum") == checksum:
                return _from_entry(e)
        return None

    def get_bytes(self, doc: DocumentRecord) -> bytes | None:
        r = self._call(
            "GET", f"/contents/{self.file_path(doc)}", ok=(200, 404),
            params={"ref": self._branch},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        return r.content if r.status_code == 200 else None

    # ------------------------------------------------------------ writes

    def restore_bytes(self, doc: DocumentRecord, data: bytes) -> None:
        self._commit(f"Restore file for {doc.title}", lambda entries: entries,
                     files={self.file_path(doc): data})

    def publish(
        self,
        doc: DocumentRecord,
        data: bytes,
        chunks: list[ChunkRecord],
        previous: DocumentRecord | None,
    ) -> None:
        store = self._search_copy()
        # Passages go in first, switched off, so nothing half-published is
        # ever searchable. They are switched on once GitHub has the commit.
        for ch in chunks:
            ch.document_active = False
        store.put_chunks(doc.id, chunks)

        def mutate(entries: list[dict]) -> list[dict]:
            for e in entries:
                if (
                    e.get("is_active")
                    and e.get("checksum") == doc.checksum
                    and (previous is None or e.get("id") != previous.id)
                ):
                    raise DuplicateDocument(_from_entry(e))
            if previous is not None:
                match = [e for e in entries if e.get("id") == previous.id]
                if not match:
                    raise DocumentMissing(previous.id)
                match[0]["is_active"] = False
                match[0]["updated_at"] = utcnow().isoformat()
            return entries + [_to_entry(doc)]

        verb = f"Replace {previous.title} with v{doc.version}" if previous else f"Add {doc.title}"
        try:
            self._commit(verb, mutate, files={self.file_path(doc): data})
        except Exception:
            store.delete_chunks(doc.id)
            raise

        store.set_chunks_meta(doc.id, doc.title, doc.category, doc.visibility, True)
        if previous is not None:
            previous.is_active = False
            store.set_chunks_meta(previous.id, previous.title, previous.category, previous.visibility, False)

    def update(self, doc: DocumentRecord) -> None:
        def mutate(entries: list[dict]) -> list[dict]:
            for i, e in enumerate(entries):
                if e.get("id") == doc.id:
                    entries[i] = _to_entry(doc)
                    return entries
            raise DocumentMissing(doc.id)

        self._commit(f"Update {doc.title}", mutate)
        self._search_copy().set_chunks_meta(doc.id, doc.title, doc.category, doc.visibility, doc.is_active)

    def delete(self, doc: DocumentRecord) -> None:
        def mutate(entries: list[dict]) -> list[dict]:
            return [e for e in entries if e.get("id") != doc.id]

        self._commit(f"Delete {doc.title}", mutate, deletes=(self.file_path(doc),))
        # Passages, plus any copy left in the database from before documents
        # moved to GitHub (its row and original bytes). A no-op otherwise.
        self._search_copy().delete_document(doc.id)

    # ------------------------------------------------------------ migration

    def _import_from_database(self) -> list[dict]:
        """One-time move of documents that were stored in the database.

        Runs only while the repository has no manifest. Passages already in the
        search copy keep their document ids, so nothing is re-indexed.
        """
        store = get_repo()
        try:
            docs = store.list_documents(include_inactive=True)
        except Exception:
            return []
        if not docs:
            return []
        blobs = get_blobs()
        files: dict[str, bytes] = {}
        for d in docs:
            data = blobs.get(d.id)
            if data is not None:
                files[self.file_path(d)] = data

        def mutate(entries: list[dict]) -> list[dict]:
            # Another instance may have finished the import first.
            return entries or [_to_entry(d) for d in docs]

        print(f"[docstore] importing {len(docs)} document(s) from the database into GitHub")
        return self._commit(
            f"Import {len(docs)} document(s) from the database", mutate, files=files
        )


# ------------------------------------------------------------------ selection

_store: RepoDocStore | GitHubDocStore | None = None


def get_docstore() -> RepoDocStore | GitHubDocStore:
    global _store
    if _store is None:
        if settings.github_docs_repo.strip():
            if not settings.github_docs_token:
                raise RuntimeError("GITHUB_DOCS_REPO is set but GITHUB_DOCS_TOKEN is not.")
            if os.getenv("REPO_BACKEND", "sqlite").strip().lower() != "postgres":
                raise RuntimeError("Documents in GitHub need REPO_BACKEND=postgres for the search copy.")
            _store = GitHubDocStore(
                settings.github_docs_repo.strip(),
                settings.github_docs_branch,
                settings.github_docs_dir,
                settings.github_docs_token,
            )
        else:
            _store = RepoDocStore()
    return _store


def set_docstore(store) -> None:
    """Test hook â€” swap the store, or reset with None."""
    global _store
    _store = store

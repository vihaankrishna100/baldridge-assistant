"""Where the original uploaded files live.

Local disk by default, which is fine for development and useless anywhere
serverless: the filesystem is wiped on every deploy and every cold start.

On Postgres the bytes go in a table alongside everything else. That is the
right call at this size — the whole library is one 3 MB PDF against Neon's
0.5 GB free tier — and it means there is no second service to provision, no
second set of credentials, and a backup of the database is a backup of the
documents.

GCS remains for reading the old Cloud Run deployment's bucket during
migration. The chunked text lives in the repo either way; this is only about
serving back the exact file leadership approved.
"""

from __future__ import annotations

import os

from config import settings


class LocalBlobs:
    def put(self, key: str, data: bytes) -> None:
        (settings.storage_path / key).write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = settings.storage_path / key
        return path.read_bytes() if path.exists() else None

    def delete(self, key: str) -> None:
        path = settings.storage_path / key
        if path.exists():
            path.unlink()


class GcsBlobs:
    def __init__(self, bucket_name: str):
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket_name)
        self._prefix = os.getenv("GCS_PREFIX", "documents/")

    def _blob(self, key: str):
        return self._bucket.blob(f"{self._prefix}{key}")

    def put(self, key: str, data: bytes) -> None:
        self._blob(key).upload_from_string(data)

    def get(self, key: str) -> bytes | None:
        blob = self._blob(key)
        return blob.download_as_bytes() if blob.exists() else None

    def delete(self, key: str) -> None:
        blob = self._blob(key)
        if blob.exists():
            blob.delete()


class PostgresBlobs:
    """Bytes in `document_blobs`, keyed by document id.

    `key` arrives as the storage key the routes already use, which is the
    document id (optionally with an extension). Everything after the first dot
    is dropped so the row lines up with documents.id and the ON DELETE CASCADE
    does the cleanup.
    """

    @staticmethod
    def _doc_id(key: str) -> str:
        return key.split("/")[-1].split(".")[0]

    def _repo(self):
        from repo import get_repo

        return get_repo()

    def put(self, key: str, data: bytes) -> None:
        self._repo().put_blob(self._doc_id(key), data)

    def get(self, key: str) -> bytes | None:
        return self._repo().get_blob(self._doc_id(key))

    def delete(self, key: str) -> None:
        self._repo().delete_blob(self._doc_id(key))


_blobs = None


def get_blobs():
    global _blobs
    if _blobs is None:
        bucket = os.getenv("GCS_BUCKET", "").strip()
        backend = os.getenv("REPO_BACKEND", "sqlite").strip().lower()
        if backend == "postgres":
            _blobs = PostgresBlobs()
        elif bucket:
            _blobs = GcsBlobs(bucket)
        else:
            _blobs = LocalBlobs()
    return _blobs

"""Where the original uploaded files live.

Local disk by default. On Cloud Run the container filesystem is wiped on every
deploy and every scale-to-zero, so set GCS_BUCKET and the originals go to Cloud
Storage instead. The chunked text lives in the repo either way — this is only
about serving back the exact file leadership approved.
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


_blobs = None


def get_blobs():
    global _blobs
    if _blobs is None:
        bucket = os.getenv("GCS_BUCKET", "").strip()
        _blobs = GcsBlobs(bucket) if bucket else LocalBlobs()
    return _blobs

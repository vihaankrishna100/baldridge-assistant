"""Copy an existing SQLite library into Firestore.

    python migrate_to_firestore.py --dry-run
    python migrate_to_firestore.py

Reads through the SQLite repo and writes through the Firestore one, so both
sides go through the same validated interface rather than raw SQL.

Idempotent by document id: re-running overwrites rather than duplicating.
Original uploaded files are handled separately — set GCS_BUCKET and pass
--files to push those too.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    ap.add_argument("--files", action="store_true", help="also copy original files to GCS")
    args = ap.parse_args()

    # Import after arg parsing so a bad invocation doesn't open connections.
    from repo.sqlite_repo import SqliteRepo

    src = SqliteRepo()
    src.bootstrap()

    users = src.list_users()
    documents = src.list_documents(include_inactive=True)
    chunks = src.iter_active_chunks()
    invites = src.list_open_invites()
    audit = src.list_audit(limit=5000)

    print("found in SQLite:")
    print(f"  users     {len(users)}")
    print(f"  documents {len(documents)}")
    print(f"  chunks    {len(chunks)}")
    print(f"  invites   {len(invites)}")
    print(f"  audit     {len(audit)}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if not (os.getenv("FIRESTORE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")):
        print("\nFIRESTORE_PROJECT is not set — refusing to guess which project to write to.")
        return 1

    from repo.base import EmailTaken
    from repo.firestore_repo import FirestoreRepo

    dst = FirestoreRepo()
    dst.bootstrap()

    print("\nwriting to Firestore...")

    for u in users:
        try:
            dst.create_user(u)
        except EmailTaken:
            dst.save_user(u)  # already migrated; refresh in place
    print(f"  users     {len(users)}")

    for i in invites:
        dst.create_invite(i)
    print(f"  invites   {len(invites)}")

    by_document: dict[str, list] = {}
    for c in chunks:
        by_document.setdefault(c.document_id, []).append(c)

    for d in documents:
        dst.create_document(d, by_document.get(d.id, []))
    print(f"  documents {len(documents)} ({len(chunks)} chunks)")

    for entry in audit:
        dst.append_audit(entry)
    print(f"  audit     {len(audit)}")

    if args.files:
        from blobs import GcsBlobs, LocalBlobs

        bucket = os.getenv("GCS_BUCKET", "").strip()
        if not bucket:
            print("\n--files needs GCS_BUCKET set; skipping originals")
        else:
            local, remote = LocalBlobs(), GcsBlobs(bucket)
            moved = 0
            for d in documents:
                data = local.get(d.id)
                if data:
                    remote.put(d.id, data)
                    moved += 1
            print(f"  files     {moved}")

    print("\ndone. Set REPO_BACKEND=firestore to start using it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

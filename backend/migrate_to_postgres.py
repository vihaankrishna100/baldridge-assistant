"""Copy everything from the local SQLite store into Neon Postgres.

    python migrate_to_postgres.py

Reads POSTGRES_URL for the destination and DATABASE_URL (the SQLite file) for
the source, so both stores are open at once.

Safe to re-run: every write is an upsert keyed on the original id, so a half
finished run can simply be repeated.

Reads through SqliteRepo and writes through PostgresRepo rather than moving
rows directly, so the dataclasses are the contract and a schema drift between
the two backends shows up here as a TypeError instead of silently landing bad
data in production.

The original uploaded PDFs are a separate matter. They lived in the Cloud
Storage bucket, which needs billing to read; the extracted text is all in
`chunks` and migrates fine, so search is unaffected. Re-upload the source PDF
afterwards if staff need to download the original — `--pdf path.pdf --pdf-doc
<document_id>` does that in the same run.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count what would move, write nothing")
    ap.add_argument("--pdf", help="original file to attach to a migrated document")
    ap.add_argument("--pdf-doc", help="document id the --pdf belongs to")
    args = ap.parse_args()

    # settings reads backend/.env, which is where the Neon DSN lives; the bare
    # environment variable is only set when running in CI or on Vercel.
    from config import settings

    if not (os.getenv("POSTGRES_URL") or settings.postgres_url):
        print("POSTGRES_URL is not set (checked the environment and backend/.env).",
              file=sys.stderr)
        return 1

    # Import after the env check so a missing DSN fails fast and clearly.
    from repo.base import EmailTaken
    from repo.postgres_repo import PostgresRepo
    from repo.sqlite_repo import SqliteRepo

    src = SqliteRepo()
    src.bootstrap()
    dst = PostgresRepo()

    users = src.list_users()
    documents = src.list_documents(include_inactive=True)
    chunks = src.iter_active_chunks()
    audit = src.list_audit(limit=100_000)

    print(f"source: {len(users)} users, {len(documents)} documents, "
          f"{len(chunks)} chunks, {len(audit)} audit rows")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    print("creating schema...")
    dst.bootstrap()

    # -------------------------------------------------------------- users
    moved = skipped = 0
    for u in users:
        try:
            dst.create_user(u)
            moved += 1
        except EmailTaken:
            # Already migrated. Overwrite so a re-run picks up a password
            # change or a role edit made since the last pass.
            existing = dst.get_user_by_email(u.email)
            if existing is not None:
                u.id = existing.id
                dst.save_user(u)
            skipped += 1
    print(f"  users: {moved} created, {skipped} already present")

    # ---------------------------------------------------------- documents
    by_doc: dict[str, list] = {}
    for c in chunks:
        by_doc.setdefault(c.document_id, []).append(c)

    for d in documents:
        if dst.get_document(d.id) is not None:
            dst.update_document(d)
            print(f"  document (updated): {d.title}")
            continue
        dst.create_document(d, by_doc.get(d.id, []))
        print(f"  document: {d.title} — {len(by_doc.get(d.id, []))} chunks")

    # Chat history is session-only, so conversations are not carried across.

    # -------------------------------------------------------------- audit
    for entry in reversed(audit):  # oldest first, so `at DESC` reads naturally
        dst.append_audit(entry)
    print(f"  audit: {len(audit)} rows")

    # ------------------------------------------------------ original file
    if args.pdf:
        if not args.pdf_doc:
            print("--pdf needs --pdf-doc <document_id>", file=sys.stderr)
            return 1
        data = open(args.pdf, "rb").read()
        dst.put_blob(args.pdf_doc, data)
        print(f"  attached {len(data):,} bytes to document {args.pdf_doc}")

    print("\nverifying...")
    print(f"  users            {dst.count_active_users()}")
    print(f"  documents        {dst.count_active_documents()}")
    print(f"  chunks           {dst.count_active_chunks()}")
    print(f"  audit (sample)   {len(dst.list_audit(limit=5))}")
    print("\ndone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

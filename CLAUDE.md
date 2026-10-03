# Bald Ridge assistant: notes for whoever works on this next

## Database storage (Neon, 512 MB free plan)

- Production sets `SKIP_BOOTSTRAP=1`, so `repo/schema.sql` does **not** run on
  startup. Schema changes reach production through
  `PostgresRepo.upgrade_if_needed()`, which document upload, document delete
  and `GET /documents/storage` call. If you add another schema change,
  extend that check, or run `get_repo().bootstrap()` against Neon by hand.
- October 2026: the passages table dropped its stored `search_vector` column
  and the unused heading trigram index. Search uses an expression index
  (`chunks_fts_idx`), which must match `PostgresRepo.SEARCH_VECTOR` exactly.
  This cut a document's search data to about a third of its old size.
- What's left per document is mostly the original file in `document_blobs`.
  PDFs don't compress further without loss. The real fix is GitHub document
  storage (`GITHUB_DOCS_REPO` / `GITHUB_DOCS_TOKEN` etc. in the backend's
  Vercel env). Those are set but not taking effect yet. Once they work,
  originals live in GitHub and Neon keeps only the search passages.
  **To do (Vihaan): get GitHub document storage working, then confirm
  `/documents/storage` reports `files_in_github: true`.**

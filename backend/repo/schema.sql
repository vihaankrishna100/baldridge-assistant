-- Postgres schema for the Bald Ridge assistant.
--
-- Two things differ from the Firestore layout on purpose:
--
--   1. Retrieval lives in the database. The Python index needed scikit-learn,
--      numpy and scipy — 358 MB, which does not fit Vercel's 250 MB function
--      cap — and rebuilt itself on every cold start. A GIN index over a
--      generated tsvector does the same job, statelessly, per request.
--
--   2. Email uniqueness is a real constraint. Firestore has none, so the
--      previous backend kept a companion user_emails/{email} doc inside a
--      transaction to fake it. Here the database enforces it and the repo
--      turns 23505 into EmailTaken.
--
-- Safe to re-run.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,
    email                TEXT NOT NULL,
    full_name            TEXT NOT NULL DEFAULT '',
    password_hash        TEXT NOT NULL DEFAULT '',
    role                 TEXT NOT NULL DEFAULT 'staff',
    totp_secret          TEXT,
    totp_confirmed       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    failed_logins        INTEGER NOT NULL DEFAULT 0,
    locked_until         TIMESTAMP,
    last_login_at        TIMESTAMP,
    created_at           TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    token_epoch          INTEGER NOT NULL DEFAULT 1
);

-- Case-insensitive: the app lowercases on the way in, this stops a stray
-- mixed-case insert from creating a second account for the same person.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users (lower(email));

-- ---------------------------------------------------------------- invites
CREATE TABLE IF NOT EXISTS invites (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'staff',
    token_hash  TEXT NOT NULL,
    created_by  TEXT NOT NULL DEFAULT '',
    expires_at  TIMESTAMP NOT NULL,
    accepted_at TIMESTAMP,
    created_at  TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE UNIQUE INDEX IF NOT EXISTS invites_token_hash_key ON invites (token_hash);
CREATE INDEX IF NOT EXISTS invites_email_idx ON invites (lower(email));
-- list_open_invites filters on both; accepted_at IS NULL is the common case.
CREATE INDEX IF NOT EXISTS invites_open_idx ON invites (expires_at) WHERE accepted_at IS NULL;

-- ---------------------------------------------------------------- documents
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    filename     TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT 'General',
    visibility   TEXT NOT NULL DEFAULT 'staff',
    version      INTEGER NOT NULL DEFAULT 1,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    checksum     TEXT NOT NULL DEFAULT '',
    size_bytes   BIGINT NOT NULL DEFAULT 0,
    char_count   BIGINT NOT NULL DEFAULT 0,
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    pii_flags    TEXT NOT NULL DEFAULT '',
    uploaded_by  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at   TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

-- find_active_document_by_checksum is the duplicate-upload guard.
CREATE INDEX IF NOT EXISTS documents_checksum_idx ON documents (checksum) WHERE is_active;
CREATE INDEX IF NOT EXISTS documents_active_idx ON documents (is_active, created_at DESC);

-- Original bytes, kept out of `documents` so listing never drags them over the
-- wire. This replaces the Cloud Storage bucket; Neon's free tier is 0.5 GB and
-- the whole current library is a single 3 MB PDF.
CREATE TABLE IF NOT EXISTS document_blobs (
    document_id TEXT PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    content     BYTEA NOT NULL
);

-- ---------------------------------------------------------------- chunks
-- document_title / category / visibility / document_active are denormalised
-- copies. They were denormalised for Firestore, and they stay that way here so
-- retrieval is one indexed table scan with no join. update_document rewrites
-- them whenever the parent changes.
CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL DEFAULT 0,
    heading         TEXT NOT NULL DEFAULT '',
    page            INTEGER,
    text            TEXT NOT NULL DEFAULT '',
    document_title  TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'General',
    visibility      TEXT NOT NULL DEFAULT 'staff',
    document_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- The retrieval index itself. Heading is weighted B and body A: a heading
    -- match is a useful signal but a body match is what actually answers the
    -- question. Stored, so it is computed on write, not per query.
    search_vector   TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(heading, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(text, '')), 'A')
    ) STORED
);

CREATE INDEX IF NOT EXISTS chunks_search_idx ON chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id, ordinal);
-- Visibility is part of every search's WHERE clause, so it is worth its own index.
CREATE INDEX IF NOT EXISTS chunks_visible_idx ON chunks (visibility) WHERE document_active;
-- Trigram index over headings, for matching a section the user half-remembers.
CREATE INDEX IF NOT EXISTS chunks_heading_trgm_idx ON chunks USING GIN (heading gin_trgm_ops);

-- ---------------------------------------------------------------- conversations

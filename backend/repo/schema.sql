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

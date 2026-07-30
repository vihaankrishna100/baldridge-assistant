# Bald Ridge Lodge — Internal Assistant

A private, RAG-based chatbot that answers staff questions **only** from Bald Ridge
Lodge's own uploaded documents, cites the exact document and page, and refers the
team member to a real person whenever it cannot answer.

Nothing leaves the server except the retrieved passages sent to the Anthropic API
for the answer itself. There is no public sign-up, no anonymous access, and no
third-party embedding service.

---

## Setup

```bash
cd ~/baldridge-assistant

cp backend/.env.example backend/.env
# Edit backend/.env — see "Configuration" below. At minimum set:
#   ANTHROPIC_API_KEY, SECRET_KEY, ORG_PHONE, ORG_EMAIL

cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python create_admin.py     # creates the first administrator
cd ..

./start.sh                            # API on :8000, web app on :3000
```

Open http://localhost:3000, sign in as the administrator, and you'll be walked
through two-factor setup on first login.

---

## Configuration

Everything lives in `backend/.env`.

| Setting | Why it matters |
|---|---|
| `ANTHROPIC_API_KEY` | Required. The only outbound call the app makes. |
| `SECRET_KEY` | Signs session tokens. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `ORG_PHONE`, `ORG_EMAIL` | **Shown verbatim in every fallback.** They ship blank on purpose — the app will never invent a phone number. Until you fill these in, the fallback tells staff to ask a supervisor. |
| `RETRIEVAL_MIN_SCORE` | The refusal threshold (0–1). Raise it if staff report confident-but-wrong answers; lower it if the assistant escalates on questions the documents clearly cover. |
| `REQUIRE_2FA` | Leave `true`. |
| `MAX_QUERIES_PER_HOUR` | Per-user rate limit. |
| `CORS_ORIGINS` | The web app's URL. Update this when you deploy. |

---

## How the guardrails work

The system is built so that **the failure mode is "ask a person," never "guess."**
There are six independent gates; a question has to clear all of them to produce an
answer.

**1 · Nobody unauthenticated gets in.** Accounts are created by admin invitation
only — there is no sign-up page. Password + TOTP two-factor, bcrypt hashing (SHA-256
pre-hashed so long passphrases aren't truncated), account lockout after 5 failed
attempts, and short-lived bearer tokens held in `sessionStorage` so they die when
the tab closes. Changing a password, resetting 2FA, or deactivating a user bumps a
`token_epoch` that invalidates every token already issued to them — a revoked
account loses access mid-session, not at next login.

**2 · Documents are tiered.** Every document is `staff` or `leadership`. The
retrieval index filters by the asker's role *before* ranking, so a leadership-only
memo can never surface to a staff member — not as an answer, not as a cited
snippet, not in a search result. Denied document downloads return `404`, not `403`,
so the response can't be used to confirm a document exists.

**3 · Weak retrieval refuses before the model is ever called.** Retrieval is hybrid
BM25 + TF-IDF/LSA fused with Reciprocal Rank Fusion. The confidence score is a real
0–1 lexical overlap, and semantic similarity only counts when at least one query
term actually appears in the passage — a dense-vector match with zero shared
vocabulary can't ground a citation. Below `RETRIEVAL_MIN_SCORE`, the question is
escalated without spending a token.

**4 · The model is instructed to refuse, not improvise.** The system prompt allows
only the supplied passages as source material and explicitly forbids filling gaps
with general knowledge about how nonprofits "usually" work, or guessing at any phone
number, address, dollar amount, deadline, or legal requirement. It emits a sentinel
(`[[NO_ANSWER]]`) rather than an apology when the passages don't answer the
question, so refusal is detected deterministically instead of by pattern-matching
prose. It also refuses questions about a named resident or employee.

**5 · Uncited answers are discarded.** Every citation is validated against the
passages actually retrieved. Invented markers are stripped, and an answer that ends
up with **zero** valid citations is thrown away and replaced with the escalation
card — an unverifiable answer is worse than no answer, because it looks checkable.

**6 · Document text can't give orders.** Retrieved passages are fenced in an
untrusted-data block and the model is told that instructions appearing inside them
are content to describe, never commands to follow. Questions aimed at the assistant
itself ("ignore previous instructions", "print your system prompt", "list all
users") are caught before retrieval, logged, and answered with the escalation card.

**Plus:** append-only audit log of every sign-in, document access, question, and
refusal; per-user hourly rate limits; PII scanning on upload that *flags* rather
than silently rewrites (a silent redaction would make the corpus disagree with the
source of record); API docs and OpenAPI schema disabled; security headers and
`noindex` on every response; generic error bodies so no traceback can echo document
text.

---

## Updating documents

**Documents → Add or update a document.** Leadership and admins can upload PDF,
Word, Markdown, CSV, or plain text. The file is extracted, chunked
(paragraph-aware, never crossing a page boundary so citations can name an exact
page), and indexed **immediately** — no restart, no rebuild step.

- **Replacing a policy** — pick the old document in the "Replaces" dropdown. The
  old version is retired from search but kept for the record, and the new one is
  versioned `v2`, `v3`, and so on.
- **Retire** removes a document from search while keeping it; **Delete** removes it
  entirely.
- Identical re-uploads are rejected so the corpus can't accumulate duplicates that
  make the retriever contradict itself.
- Scanned PDFs with no selectable text are rejected with an explanation rather than
  silently indexing as empty.

**Admin → Overview** shows *Where the documents fall short*: the questions staff
asked most often that nothing in the library answered. That list is the queue of
policies worth writing.

---

## Roles

| Role | Can do |
|---|---|
| **Staff** | Ask questions; read and download staff-visible documents. |
| **Leadership** | The above, plus leadership-only documents and all document management. |
| **Administrator** | The above, plus invitations, roles, 2FA resets, deactivation, audit log, stats. |

---

## Testing

```bash
cd backend
./venv/bin/python selftest.py      # retrieval, refusal gate, citations, visibility, PII
```

No API key needed — it runs against a throwaway in-memory database and a small fake
policy corpus.

---

## Adding the mobile app later

The web app is the only client today, but the backend is a plain bearer-token JSON
API with an SSE streaming endpoint, so a React Native / Expo client can talk to it
without server changes. Add the app's origin to `CORS_ORIGINS` when you build it.

---

## Before going live

- [ ] Set a real `SECRET_KEY` (not the placeholder).
- [ ] Fill in `ORG_PHONE` and `ORG_EMAIL` — the admin dashboard warns while these
      are blank, because the fallback is the whole point of the system.
- [ ] Serve over HTTPS and set `CORS_ORIGINS` to the real domain.
- [ ] Back up `backend/data/` (database) and `backend/storage/` (original files).
      Both are gitignored — they hold the private corpus.
- [ ] Decide what does **not** go in the library. This assistant is for procedures
      and policies. Resident records, case files, and medical information should
      not be uploaded; the PII scanner flags them, but it is a safety net, not a
      policy.

## Known notes

- `npm audit` reports 3 high-severity advisories in `postcss` and `sharp`. Both are
  transitive build-time dependencies of Next.js 16 itself — `npm audit fix --force`
  "resolves" them by downgrading to Next.js 9, which is not a fix. They don't affect
  the running server. They clear when Next ships updated pins.

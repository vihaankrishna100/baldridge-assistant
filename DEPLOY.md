# Deploying

The two halves go to different places, and that split is not optional.

**Frontend → Vercel.** Static Next.js, no state. Already live at
https://baldridge-assistant.vercel.app

**Backend → Railway (or any host with a persistent disk).** It cannot go on
Vercel:

- SQLite lives on disk. Vercel functions have an ephemeral filesystem, so every
  account, the audit log, and the document library would vanish between
  invocations.
- `storage/` holds the original uploaded files. Same problem.
- The retrieval index is held in process memory and rebuilt only when documents
  change. Serverless has no persistent process, so every cold start would
  rebuild it.
- scipy (97 MB) + sklearn (50 MB) + numpy (31 MB) is 178 MB before your own
  code, against Vercel's 250 MB Python bundle limit.

---

## 1 · Deploy the backend to Railway

```bash
npm i -g @railway/cli
```

```bash
railway login
```

That opens a browser to authorize — you have to do this one yourself.

```bash
cd ~/baldridge-assistant/backend && railway init && railway up
```

Railway detects the `Dockerfile` and builds it.

### Add the persistent volume — do this before anything real goes in

In the Railway dashboard: **your service → Variables → Volumes → New Volume**,
mount path exactly:

```
/data
```

Without it the database resets on every redeploy. The `Dockerfile` already
points `DATABASE_URL` and `STORAGE_DIR` at `/data`.

### Set the environment variables

Railway dashboard → **Variables** → paste as raw editor:

```
ANTHROPIC_API_KEY=<your rotated key>
SECRET_KEY=<generate a fresh one, see below>

ORG_NAME=Bald Ridge Lodge
ORG_PHONE=770-887-1220
ORG_EMAIL=adikes@baldridgelodge.org
ORG_FALLBACK_CONTACT_NAME=the front office
ORG_PROFILE=Bald Ridge Lodge is a Child Caring Institution (CCI) in Forsyth County, Georgia, contracted with Georgia DFCS to provide Room, Board and Watchful Oversight (RBWO). It is NOT a Child Placing Agency (CPA), an Independent Living Program (ILP), a Transitional Living Program (TLP), a Maternity Home, or a Parenting Support / Second Chance Home. Standards written specifically for those provider types do not bind Bald Ridge Lodge; standards written for all providers, and those written for CCIs, do.

ASSISTANT_MODEL=claude-opus-5
ASSISTANT_EFFORT=medium
ASSISTANT_MAX_TOKENS=8192

RETRIEVAL_TOP_K=8
RETRIEVAL_CANDIDATES=30
RETRIEVAL_MIN_SCORE=0.08
CHUNK_TOKENS=350
CHUNK_OVERLAP=60

SESSION_TTL_MINUTES=480
REQUIRE_2FA=true
TWOFA_EXEMPT_EMAILS=adikes@baldridgelodge.org
MAX_QUERIES_PER_HOUR=60
MAX_UPLOAD_MB=25

CORS_ORIGINS=https://baldridge-assistant.vercel.app
```

Generate `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

`CORS_ORIGINS` is also what builds invitation links, so it must be the real
frontend URL — not localhost.

### Create the administrator on the server

```bash
cd ~/baldridge-assistant/backend && railway run python create_admin.py
```

The local database does not travel with the deploy. This account is separate
from your local one.

---

## 2 · Point the frontend at it

Copy the backend's public URL from Railway (**Settings → Networking → Generate
Domain** if it doesn't have one yet), then:

```bash
cd ~/baldridge-assistant/frontend && vercel env add NEXT_PUBLIC_API_BASE production
```

Paste the Railway URL when prompted (no trailing slash), then redeploy:

```bash
cd ~/baldridge-assistant/frontend && vercel deploy --prod --yes
```

---

## 3 · Re-upload the documents

The RBWO standards PDF is in your *local* library, not the deployed one. Sign
in to the deployed site, go to **Documents**, and upload it again. It re-chunks
in about a minute.

---

## Before you tell staff about it

- [ ] **Rotate the Anthropic API key.** The current one was pasted in a chat
      transcript. Generate a new one at console.anthropic.com and set it only
      as a Railway variable.
- [ ] Confirm the `/data` volume is mounted — redeploy once and check your
      admin account survives.
- [ ] `TWOFA_EXEMPT_EMAILS` is set, so that account signs in on password alone.
      On a public URL that password is the only thing between the internet and
      every document, including leadership-only files. Use a long unique one,
      and remove the line to turn 2FA back on.
- [ ] Decide what does **not** go in the library. Resident records, case files,
      and medical information should not be uploaded. The PII scanner flags
      them, but it is a safety net, not a policy.

## Redeploying later

Frontend:

```bash
cd ~/baldridge-assistant/frontend && vercel deploy --prod --yes
```

Backend:

```bash
cd ~/baldridge-assistant/backend && railway up
```

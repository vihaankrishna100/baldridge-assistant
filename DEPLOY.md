# Deploying

**Frontend → Vercel.** Already live at https://baldridge-assistant.vercel.app

**Backend → Cloud Run, data → Firestore, files → Cloud Storage.** This is the
version that runs without your laptop.

Cost: the free tiers cover a nonprofit's usage comfortably (Cloud Run bills
per request and scales to zero; Firestore gives 50k reads and 20k writes a
day). A billing account with a card is required to enable Cloud Run, but you
should expect $0 apart from Anthropic API usage. **Set a budget alert anyway.**

---

## 1 · Create the project

```bash
brew install --cask google-cloud-sdk && gcloud init
```

```bash
gcloud projects create baldridge-assistant --name="Bald Ridge Assistant"
```

Link billing in the console, then:

```bash
gcloud config set project baldridge-assistant && gcloud services enable run.googleapis.com firestore.googleapis.com storage.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

## 2 · Firestore and the bucket

```bash
gcloud firestore databases create --location=nam5
```

```bash
gcloud storage buckets create gs://baldridge-documents --location=us-east1 --uniform-bucket-level-access
```

Composite indexes (queries that filter on two fields need these):

```bash
cd ~/baldridge-assistant && firebase deploy --only firestore:indexes --project baldridge-assistant
```

If you skip that, the first admin-stats or filtered-audit call fails with an
error containing a link that creates the missing index for you.

## 3 · Deploy

```bash
cd ~/baldridge-assistant/backend && gcloud run deploy baldridge-api --source . --region us-east1 --allow-unauthenticated --min-instances 0 --max-instances 1 --memory 1Gi --cpu 1 --timeout 300
```

`--max-instances 1` is deliberate. The retrieval index lives in each instance's
memory, so a second instance would hold a stale copy after an upload until it
restarted. One instance handles a few dozen staff fine; raise it only if you
add index invalidation.

Then set configuration:

```bash
gcloud run services update baldridge-api --region us-east1 --update-env-vars "REPO_BACKEND=firestore,GCS_BUCKET=baldridge-documents,FIRESTORE_PROJECT=baldridge-assistant,ORG_NAME=Bald Ridge Lodge,ORG_PHONE=770-887-1220,ORG_EMAIL=adikes@baldridgelodge.org,CORS_ORIGINS=https://baldridge-assistant.vercel.app,TWOFA_EXEMPT_EMAILS=adikes@baldridgelodge.org"
```

The API key belongs in Secret Manager, not an env var:

```bash
printf 'sk-ant-YOUR-ROTATED-KEY' | gcloud secrets create anthropic-key --data-file=- && gcloud run services update baldridge-api --region us-east1 --update-secrets=ANTHROPIC_API_KEY=anthropic-key:latest
```

`SECRET_KEY` the same way — generate one with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.

Grant the service account access to Firestore and the bucket:

```bash
gcloud projects add-iam-policy-binding baldridge-assistant --member="serviceAccount:$(gcloud run services describe baldridge-api --region us-east1 --format='value(spec.template.spec.serviceAccountName)')" --role=roles/datastore.user
```

## 4 · Move your existing library across

Everything currently on your laptop — the admin account, the RBWO standards,
645 chunks, the audit log — copies over in one command:

```bash
cd ~/baldridge-assistant/backend && FIRESTORE_PROJECT=baldridge-assistant GCS_BUCKET=baldridge-documents ./venv/bin/python migrate_to_firestore.py --files
```

Run `--dry-run` first to see the counts. It is idempotent — re-running
overwrites rather than duplicating.

## 5 · Point the frontend at it

```bash
cd ~/baldridge-assistant/frontend && vercel env add NEXT_PUBLIC_API_BASE production
```

Paste the Cloud Run URL (`gcloud run services describe baldridge-api
--region us-east1 --format='value(status.url)'`), then:

```bash
cd ~/baldridge-assistant/frontend && vercel deploy --prod --yes
```

---

## What to expect

**Cold starts.** With `--min-instances 0` the container sleeps when idle. The
first question after a quiet period waits while the index rebuilds — reading
645 chunks from Firestore and fitting TF-IDF/SVD, roughly 15–25 seconds. Every
question after that is fast. If that first-question delay is unacceptable,
`--min-instances 1` removes it but runs the container continuously, which does
cost a few dollars a month.

**Adding documents still works the same.** Upload through the Documents page;
chunks go to Firestore and the index rebuilds in the running instance
immediately. No redeploy, no retraining.

**Free-tier headroom.** A 645-chunk upload is 645 writes against a 20k/day
allowance, so roughly 30 documents that size per day. Reads are 645 per cold
start against 50k/day.

---

## Running locally

Unchanged. `REPO_BACKEND` defaults to `sqlite`, so `./start.sh` needs no cloud
account and no credentials. That is also what the test suite runs against:

```bash
cd backend && ./venv/bin/python selftest.py
```

To point local development at Firestore instead:

```bash
export REPO_BACKEND=firestore FIRESTORE_PROJECT=baldridge-assistant && gcloud auth application-default login
```

---

## Before staff use it

- [ ] **Rotate the Anthropic API key** — the current one is in a chat
      transcript. Put the replacement in Secret Manager only.
- [ ] Set a billing budget alert at, say, $5 so nothing can surprise you.
- [ ] `TWOFA_EXEMPT_EMAILS` means that account signs in on password alone. On a
      public URL that password is the only thing protecting every document.
      Delete the variable to turn 2FA back on.
- [ ] Firestore has no backups on the free tier. Export periodically:
      `gcloud firestore export gs://baldridge-documents/backups/$(date +%F)`
- [ ] Resident records, case files, and medical information should not be
      uploaded. The PII scanner flags them; it is a safety net, not a policy.

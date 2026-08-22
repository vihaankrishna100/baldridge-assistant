#!/usr/bin/env bash
#
# Deploys the assistant to Google Cloud, end to end.
#
#   bash deploy/gcloud-setup.sh
#
# Prerequisites you must do yourself (they need a browser and your account):
#   gcloud auth login
#   billing enabled on the project
#
# Safe to re-run. Every step checks whether it already happened.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-baldridge-assistant}"
REGION="${REGION:-us-east1}"
SERVICE="${SERVICE:-baldridge-api}"
BUCKET="${BUCKET:-${PROJECT}-documents}"
FRONTEND="${FRONTEND:-https://baldridge-assistant.vercel.app}"

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
ok()  { printf "    %s\n" "$1"; }
die() { printf "\n!! %s\n" "$1" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
command -v gcloud >/dev/null || die "gcloud not installed: brew install --cask google-cloud-sdk"

gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q . \
  || die "Not signed in. Run:  gcloud auth login"

ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)
ok "signed in as $ACCOUNT"

if [ ! -f backend/.env ]; then
  die "backend/.env is missing — it holds the API key this deploy reads."
fi

API_KEY=$(grep -E '^ANTHROPIC_API_KEY=' backend/.env | cut -d= -f2- || true)
[ -n "$API_KEY" ] && [[ "$API_KEY" == sk-* ]] \
  || die "ANTHROPIC_API_KEY in backend/.env is empty or not a real key. Set it first."

# ---------------------------------------------------------------- project
say "project"
if gcloud projects describe "$PROJECT" >/dev/null 2>&1; then
  ok "$PROJECT already exists"
else
  gcloud projects create "$PROJECT" --name="Bald Ridge Assistant"
  ok "created $PROJECT"
fi
gcloud config set project "$PROJECT" >/dev/null
gcloud config set run/region "$REGION" >/dev/null

if ! gcloud beta billing projects describe "$PROJECT" \
     --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  cat <<EOF

!! Billing is not enabled on $PROJECT.

   Cloud Run needs it. You will not be charged for this workload — the free
   tier covers it — but a card must be on file.

   Enable it here, then re-run this script:
   https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT

EOF
  exit 1
fi
ok "billing enabled"

# ---------------------------------------------------------------- services
say "enabling APIs (slow the first time)"
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com --quiet
ok "done"

# ---------------------------------------------------------------- firestore
say "firestore"
if gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  ok "database already exists"
else
  gcloud firestore databases create --location=nam5 --quiet
  ok "created"
fi

if command -v firebase >/dev/null && [ -f deploy/firestore.indexes.json ]; then
  cat > /tmp/firebase.json <<EOF
{ "firestore": { "indexes": "deploy/firestore.indexes.json" } }
EOF
  cp /tmp/firebase.json firebase.json
  firebase deploy --only firestore:indexes --project "$PROJECT" --non-interactive 2>&1 | tail -3 \
    || ok "index deploy skipped (firebase login needed) — Firestore will link the ones it wants on first use"
  rm -f firebase.json
fi

# ---------------------------------------------------------------- bucket
say "storage bucket"
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  ok "gs://$BUCKET already exists"
else
  gcloud storage buckets create "gs://$BUCKET" \
    --location="$REGION" --uniform-bucket-level-access --quiet
  ok "created gs://$BUCKET"
fi

# ---------------------------------------------------------------- secrets
say "secrets"
put_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --quiet >/dev/null
    ok "$name updated"
  else
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --quiet >/dev/null
    ok "$name created"
  fi
}
put_secret anthropic-key "$API_KEY"

SECRET_KEY=$(grep -E '^SECRET_KEY=' backend/.env | cut -d= -f2- || true)
[ -n "$SECRET_KEY" ] || SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
put_secret session-key "$SECRET_KEY"

# ---------------------------------------------------------------- deploy
# --no-cpu-throttling matters more than it looks. Cloud Run only gives CPU
# while a request is in flight by default, which starves the background thread
# that builds the retrieval index — it took 94s to warm instead of 8. Without
# this the first question after a cold start waits on a half-built index.
say "building and deploying (first build takes a few minutes)"
gcloud run deploy "$SERVICE" \
  --source backend \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 1 \
  --cpu-boost \
  --no-cpu-throttling \
  --timeout 300 \
  --quiet

SA=$(gcloud run services describe "$SERVICE" --region "$REGION" \
     --format='value(spec.template.spec.serviceAccountName)')
[ -n "$SA" ] || SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"

say "permissions"
for role in roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role="$role" --quiet >/dev/null
  ok "$role"
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin --quiet >/dev/null
ok "roles/storage.objectAdmin on the bucket"

# ---------------------------------------------------------------- config
say "configuration"
# Written as a YAML file rather than --set-env-vars: ORG_PROFILE contains
# commas and ORG_EMAIL contains "@", so every gcloud delimiter escaping trick
# breaks on one of them. A file has no delimiter problem at all.
python3 - "$PROJECT" "$BUCKET" "$FRONTEND" <<'PYEOF' > /tmp/baldridge-env.yaml
import sys, pathlib
project, bucket, frontend = sys.argv[1], sys.argv[2], sys.argv[3]

env = {
    "REPO_BACKEND": "firestore",
    "FIRESTORE_PROJECT": project,
    "GCS_BUCKET": bucket,
    "CORS_ORIGINS": frontend,
}
carry = [
    "ORG_NAME", "ORG_PHONE", "ORG_EMAIL", "ORG_FALLBACK_CONTACT_NAME",
    "ORG_PROFILE", "ASSISTANT_MODEL", "ASSISTANT_EFFORT", "ASSISTANT_MAX_TOKENS",
    "RETRIEVAL_TOP_K", "RETRIEVAL_CANDIDATES", "RETRIEVAL_MIN_SCORE",
    "CHUNK_TOKENS", "CHUNK_OVERLAP", "SESSION_TTL_MINUTES", "REQUIRE_2FA",
    "TWOFA_EXEMPT_EMAILS", "MAX_QUERIES_PER_HOUR", "MAX_UPLOAD_MB",
]
for line in pathlib.Path("backend/.env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    if key.strip() in carry and value.strip():
        env[key.strip()] = value.strip()

def quote(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'

for k, v in env.items():
    print(f"{k}: {quote(str(v))}")
PYEOF

gcloud run services update "$SERVICE" --region "$REGION" \
  --env-vars-file /tmp/baldridge-env.yaml \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-key:latest,SECRET_KEY=session-key:latest" \
  --quiet >/dev/null
rm -f /tmp/baldridge-env.yaml
ok "environment and secrets attached"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')

say "deployed"
echo "    API   $URL"
echo ""
curl -fsS --max-time 60 "$URL/health" | sed 's/^/    /' || echo "    (health check not answering yet — give it a minute)"

cat <<EOF

Next, in order:

  1. Copy your existing library across (admin account, RBWO standards, 645 chunks):

       cd backend && FIRESTORE_PROJECT=$PROJECT GCS_BUCKET=$BUCKET \\
         ./venv/bin/python migrate_to_firestore.py --files

  2. Point the website at the API:

       cd frontend && vercel env add NEXT_PUBLIC_API_BASE production
       # paste: $URL
       vercel deploy --prod --yes

  3. Open $FRONTEND and sign in.

EOF

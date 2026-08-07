#!/usr/bin/env bash
# Starts the assistant. Ctrl-C stops everything.
#
#   ./start.sh            local only — http://localhost:3000
#   ./start.sh --share    also opens a public HTTPS link so staff can use it
#
set -euo pipefail
cd "$(dirname "$0")"

SHARE=0
[[ "${1:-}" == "--share" ]] && SHARE=1

# ---------------------------------------------------------------- checks
if [ ! -f backend/.env ]; then
  echo "backend/.env is missing. Run:"
  echo "    cp backend/.env.example backend/.env"
  echo "Then add your ANTHROPIC_API_KEY."
  exit 1
fi

if ! grep -qE '^ANTHROPIC_API_KEY=sk-' backend/.env; then
  echo "!! ANTHROPIC_API_KEY is not set in backend/.env — questions will fail."
  echo "   Get a key at https://console.anthropic.com/settings/keys"
  echo ""
fi

if [ ! -d backend/venv ]; then
  echo "Setting up Python (one time, ~2 min)..."
  python3 -m venv backend/venv
  ./backend/venv/bin/pip install -q --upgrade pip
  ./backend/venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "Setting up the web app (one time)..."
  (cd frontend && npm install --silent)
fi

# Free the ports if something is already holding them, otherwise the second
# run of the day silently binds nothing and the app looks broken.
for port in 8000 3000; do
  pid=$(lsof -ti tcp:$port 2>/dev/null || true)
  [ -n "$pid" ] && { echo "freeing port $port"; kill $pid 2>/dev/null || true; sleep 1; }
done

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------- run
(cd backend && exec ./venv/bin/uvicorn main:app --port 8000 --log-level warning) &

# Wait for the index to load before starting the UI, so the first click works.
printf "starting"
for _ in $(seq 1 45); do
  if curl -fsS --max-time 2 http://localhost:8000/health >/dev/null 2>&1; then break; fi
  printf "."; sleep 1
done
echo ""
curl -fsS --max-time 3 http://localhost:8000/health 2>/dev/null | sed 's/^/  /' || {
  echo "  the API did not come up — check the messages above"; exit 1; }

API_URL="http://localhost:8000"
if [ "$SHARE" = "1" ]; then
  if ! command -v cloudflared >/dev/null; then
    echo ""
    echo "  --share needs cloudflared. Install it once with:"
    echo "      brew install cloudflared"
    exit 1
  fi
  echo ""
  echo "  opening a public link..."
  cloudflared tunnel --url http://localhost:8000 --no-autoupdate > /tmp/br-tunnel.log 2>&1 &
  for _ in $(seq 1 30); do
    API_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/br-tunnel.log 2>/dev/null | head -1 || true)
    [ -n "$API_URL" ] && break
    sleep 1
  done
  if [ -z "$API_URL" ]; then
    echo "  tunnel did not start; falling back to local only"
    API_URL="http://localhost:8000"
  fi
fi

# The browser app needs to know where the API is. A temporary tunnel gets a new
# hostname each run, so this is written fresh every start rather than committed.
printf 'NEXT_PUBLIC_API_BASE=%s\n' "$API_URL" > frontend/.env.local

(cd frontend && exec npm run dev) &

echo ""
echo "  ------------------------------------------------------------"
echo "   Open        http://localhost:3000"
[ "$SHARE" = "1" ] && echo "   Staff link  $API_URL   (API — see SHARING.md)"
echo "   Stop        Ctrl-C"
echo "  ------------------------------------------------------------"
echo ""
wait

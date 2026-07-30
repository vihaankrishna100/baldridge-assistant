#!/usr/bin/env bash
# Starts the API and the web app together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f backend/.env ]; then
  echo "backend/.env is missing. Run:  cp backend/.env.example backend/.env"
  echo "Then add your ANTHROPIC_API_KEY and the Bald Ridge Lodge phone/email."
  exit 1
fi

if [ ! -d backend/venv ]; then
  echo "Creating the Python environment (one time)..."
  python3 -m venv backend/venv
  ./backend/venv/bin/pip install -q --upgrade pip
  ./backend/venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing web dependencies (one time)..."
  (cd frontend && npm install)
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && ./venv/bin/uvicorn main:app --reload --port 8000) &
(cd frontend && npm run dev) &

echo ""
echo "  API   http://localhost:8000"
echo "  App   http://localhost:3000"
echo ""
wait

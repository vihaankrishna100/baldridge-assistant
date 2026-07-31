#!/usr/bin/env bash
#
# Sets up the assistant API on a fresh Ubuntu/Debian server.
#
#   sudo bash install.sh api.yourdomain.org
#
# Safe to re-run — it only creates what is missing.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
    echo "usage: sudo bash install.sh <api-domain>" >&2
    echo "   eg: sudo bash install.sh api.baldridgelodge.org" >&2
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "run with sudo" >&2
    exit 1
fi

APP_DIR=/opt/baldridge
REPO_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ufw debian-keyring \
    debian-archive-keyring apt-transport-https curl gnupg

if ! command -v caddy >/dev/null; then
    echo "==> caddy"
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
fi

echo "==> service account"
id -u baldridge &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin baldridge

echo "==> application files"
mkdir -p "$APP_DIR"
# Never overwrite live data or the configured secrets.
rsync -a --delete \
    --exclude venv/ --exclude data/ --exclude storage/ \
    --exclude __pycache__/ --exclude .env \
    "$REPO_SRC/backend/" "$APP_DIR/backend/"

mkdir -p "$APP_DIR/backend/data" "$APP_DIR/backend/storage"

echo "==> python environment"
if [[ ! -d "$APP_DIR/backend/venv" ]]; then
    python3 -m venv "$APP_DIR/backend/venv"
fi
"$APP_DIR/backend/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/backend/venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

if [[ ! -f "$APP_DIR/backend/.env" ]]; then
    cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
    # A generated key beats the placeholder if nobody edits the file.
    KEY="$("$APP_DIR/backend/venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(48))')"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$KEY|" "$APP_DIR/backend/.env"
    echo
    echo "  !! $APP_DIR/backend/.env was created from the example."
    echo "     Set ANTHROPIC_API_KEY and CORS_ORIGINS before this will work."
    echo
fi

chown -R baldridge:baldridge "$APP_DIR"
chmod 600 "$APP_DIR/backend/.env"

echo "==> systemd"
install -m 644 "$REPO_SRC/deploy/baldridge-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now baldridge-api

echo "==> caddy"
sed "s|api\.baldridgelodge\.org|$DOMAIN|" "$REPO_SRC/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "==> firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo
echo "done. https://$DOMAIN/health should answer once DNS points here."
echo
echo "next:"
echo "  1. edit $APP_DIR/backend/.env  (ANTHROPIC_API_KEY, CORS_ORIGINS)"
echo "  2. systemctl restart baldridge-api"
echo "  3. sudo -u baldridge $APP_DIR/backend/venv/bin/python \\"
echo "         $APP_DIR/backend/create_admin.py    # run from that directory"

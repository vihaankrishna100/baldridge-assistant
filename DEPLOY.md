# Deploying

Two halves, two places.

**Frontend → Vercel.** Static Next.js, no state. Live at
https://baldridge-assistant.vercel.app

**Backend → a normal Linux server.** Any VPS will do — DigitalOcean, Hetzner,
Linode, Vultr, or a box at the Lodge with a static IP. The smallest tier is
enough: 1 vCPU / 1 GB RAM handles a few dozen staff comfortably.

It needs an ordinary server rather than a serverless host because:

- SQLite lives on disk, and the audit log has to survive restarts.
- `storage/` holds the original uploaded files.
- The retrieval index is built once at startup and held in memory. A process
  that gets torn down between requests would rebuild all 645 chunks every time.

---

## 1 · Point DNS at the server

Create an A record for the API before running anything, so Caddy can get a
certificate on first start:

```
api.baldridgelodge.org.   A   <your server IP>
```

## 2 · Install

Copy the project to the server and run the installer:

```bash
scp -r ~/baldridge-assistant root@<server-ip>:/root/
```

```bash
ssh root@<server-ip> "cd /root/baldridge-assistant && bash deploy/install.sh api.baldridgelodge.org"
```

That script installs Python and Caddy, creates an unprivileged `baldridge`
service account, builds the virtualenv, installs the systemd unit, configures
HTTPS, and opens only ports 22/80/443. It is safe to re-run — it never
overwrites `.env`, the database, or `storage/`.

## 3 · Configure

```bash
ssh root@<server-ip> "nano /opt/baldridge/backend/.env"
```

At minimum set:

```
ANTHROPIC_API_KEY=<your rotated key>
CORS_ORIGINS=https://baldridge-assistant.vercel.app
```

`SECRET_KEY` was generated for you by the installer. `CORS_ORIGINS` is also
what builds invitation links, so it must be the real frontend URL.

Then restart and create the administrator:

```bash
ssh root@<server-ip> "systemctl restart baldridge-api"
```

```bash
ssh root@<server-ip> "cd /opt/baldridge/backend && sudo -u baldridge venv/bin/python create_admin.py"
```

The local database does not travel with the deploy — this account is separate
from the one on your laptop.

Check it:

```bash
curl https://api.baldridgelodge.org/health
```

## 4 · Point the frontend at it

```bash
cd ~/baldridge-assistant/frontend && vercel env add NEXT_PUBLIC_API_BASE production
```

Paste the API URL (no trailing slash), then redeploy:

```bash
cd ~/baldridge-assistant/frontend && vercel deploy --prod --yes
```

## 5 · Upload the documents

Sign in to the deployed site, go to **Documents**, and upload the RBWO
standards PDF. It re-chunks in about a minute. The library on your laptop is
not the library on the server.

---

## Operating it

```bash
systemctl status baldridge-api        # is it up
journalctl -u baldridge-api -f        # live logs
systemctl restart baldridge-api       # after an .env change
```

**Back up these two paths.** They are the whole system:

```
/opt/baldridge/backend/data/      # accounts, audit log, document text
/opt/baldridge/backend/storage/   # original uploaded files
```

```bash
ssh root@<server-ip> "tar czf - /opt/baldridge/backend/data /opt/baldridge/backend/storage" > baldridge-backup-$(date +%F).tar.gz
```

Deploying an update:

```bash
scp -r ~/baldridge-assistant root@<server-ip>:/root/ && \
ssh root@<server-ip> "cd /root/baldridge-assistant && bash deploy/install.sh api.baldridgelodge.org"
```

---

## Before you tell staff about it

- [ ] **Rotate the Anthropic API key.** The current one was pasted into a chat
      transcript. Generate a new one at console.anthropic.com and put it only
      in the server's `.env`.
- [ ] Confirm backups run. Everything lives in those two directories.
- [ ] `TWOFA_EXEMPT_EMAILS` is set, so that account signs in on password alone.
      On a public URL that password is the only thing between the internet and
      every document, including leadership-only files. Use a long unique one;
      delete the line to turn 2FA back on.
- [ ] Decide what does **not** go in the library. Resident records, case files,
      and medical information should not be uploaded. The PII scanner flags
      them, but it is a safety net, not a policy.

## If you'd rather use Docker

`backend/Dockerfile` builds the same thing and runs anywhere containers do.
Mount a volume at `/data`. Note it has not been built or tested — there is no
Docker on the machine this was developed on, so treat it as a starting point
rather than a verified path. The systemd route above is the tested one.

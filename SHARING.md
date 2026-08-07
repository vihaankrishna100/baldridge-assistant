# Running it for free

No server, no hosting bill. The only thing that costs money is Anthropic API
usage, which for a few dozen questions a day is cents.

## Just you

```bash
cd ~/baldridge-assistant && ./start.sh
```

Open http://localhost:3000. Everything works — asking, uploading documents,
the admin panel. Nothing leaves your machine except the retrieved passages
sent to Anthropic to write the answer.

Stop it with Ctrl-C.

## Letting staff use it

```bash
cd ~/baldridge-assistant && ./start.sh --share
```

This opens a free Cloudflare tunnel — a public HTTPS address that forwards to
the API on your machine. No account, no card, no bill.

One-time install:

```bash
brew install cloudflared
```

Then point the deployed site at it. Copy the staff link the script prints, and:

```bash
cd ~/baldridge-assistant/frontend && vercel env add NEXT_PUBLIC_API_BASE production
```

```bash
cd ~/baldridge-assistant/frontend && vercel deploy --prod --yes
```

Staff then use **https://baldridge-assistant.vercel.app** from any phone or
computer.

### What you're trading away

- **Your computer has to be awake and running the script.** Close the laptop
  and the assistant goes down for everyone.
- **The address changes every restart.** A free tunnel gets a new random
  hostname each time, so you have to redeploy the frontend after each restart.
  A fixed address needs a Cloudflare account with a domain — still free, but
  more setup.
- Not something to build a shift around. It's fine for trying it with a few
  people; it is not a service.

If it becomes something staff rely on daily, the honest answer is a small
always-on machine. That can be an old desktop in the office running
`deploy/install.sh` — no monthly bill, just a computer that stays on.

## Changing the API key

One line in `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Restart with `./start.sh` and it picks up the new one. Nothing else references
the key.

**Rotate the current one.** It was pasted into a chat transcript. Create a
replacement at https://console.anthropic.com/settings/keys, paste it into
`backend/.env`, then delete the old key from the console so the exposed one
stops working.

## Keeping your documents safe

Everything lives in two folders:

```
backend/data/      accounts, audit log, document text and search index
backend/storage/   the original uploaded files
```

Copy them somewhere safe now and then:

```bash
cd ~/baldridge-assistant && tar czf ~/baldridge-backup-$(date +%F).tar.gz backend/data backend/storage
```

Neither folder is in git, so they are not backed up by committing.

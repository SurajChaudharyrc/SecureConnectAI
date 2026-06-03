# Deploying SecureConnect-AI

This app needs a **persistent WebSocket server** (live chat) and a **real
database**. It is NOT deployable on serverless platforms (Vercel/Netlify
Functions, AWS Lambda) because:

- WebSockets require a long-lived connection; serverless functions are ephemeral.
- The chat broker keeps presence + fan-out **in process memory**, so the app must
  run as a **single, always-on process** (do not run multiple workers/replicas
  without first swapping in a Redis-backed broker — see `services/chat.py`).
- It uses a SQL database via `DATABASE_URL` (SQLite locally; **Postgres** in prod —
  a serverless filesystem can't persist SQLite).

Provided files: `Dockerfile`, `docker-start.sh`, `.dockerignore`,
`backend/requirements-prod.txt` (slim, no TensorFlow), `fly.toml`.

## Required environment variables (set as secrets on the host)

| Var | Value |
|-----|-------|
| `APP_ENV` | `prod` (enables HSTS) — already set in Dockerfile/fly.toml |
| `APP_SECRET` | a random string **≥ 32 chars** (signs sessions + CSRF) |
| `DATABASE_URL` | `postgresql+psycopg://USER:PASS@HOST:5432/DBNAME` (note the `+psycopg`) |
| `ALLOWED_ORIGIN` | the deployed origin, e.g. `https://secureconnect-ai.fly.dev` — **must** match exactly (CORS + the WebSocket CSWSH origin check compare against it) |
| `DEEPFACE_ENABLED` | `false` — already set; face verify returns a graceful stub |
| `PORT` | provided by the host (Fly sets it; Dockerfile defaults to 8000) |

A `DATABASE_URL` from Neon/Supabase usually starts `postgresql://…` — change the
scheme to `postgresql+psycopg://…` so SQLAlchemy uses the psycopg v3 driver.

Demo accounts (all password `DemoPass1234`): `aryan_dev`, `maya_chen`, `raj_patel`,
`sara_k`, `leo_m`, `new_user`. They are (re)seeded on every boot by
`docker-start.sh`; remove that line to disable demo data.

## Deploy on Fly.io (recommended — Docker-from-folder, native WebSockets)

```powershell
# 1. Install the CLI (PowerShell), then RESTART the terminal so `fly` is on PATH:
iwr https://fly.io/install.ps1 -useB | iex

# 2. Log in (opens a browser):
fly auth login

# 3. From this folder, create the app from fly.toml (don't deploy yet):
fly launch --no-deploy --copy-config --name secureconnect-ai

# 4. Get a Postgres URL. Easiest free option: create a Neon project
#    (https://neon.tech) and copy its connection string. Then:
fly secrets set `
  APP_SECRET="$([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))" `
  DATABASE_URL="postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require" `
  ALLOWED_ORIGIN="https://secureconnect-ai.fly.dev"

# 5. Ship it:
fly deploy

# 6. Open it:
fly open
```

Keep it on **one machine** (`fly.toml` pins `max_machines_running = 1`). Scaling
out needs a Redis broker first.

## Alternatives

- **Railway** — `railway login`, `railway init`, add a Postgres plugin (sets
  `DATABASE_URL` — append `+psycopg` to the scheme via a variable override),
  set `APP_SECRET`/`ALLOWED_ORIGIN`, `railway up`. Uses the same `Dockerfile`.
  Ensure the service runs a single replica.
- **Render** — New → Web Service → Docker; add a Render Postgres; set the env
  vars above; instance count = 1. (Render is Git-based, so it needs this project
  in its own repo/root.)

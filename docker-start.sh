#!/usr/bin/env sh
set -e

# Create tables (Base.metadata.create_all) + seed demo data. Idempotent — safe
# on every boot. Remove this line if you don't want demo accounts in production.
python -m backend.seed || echo "seed step failed (continuing without demo data)"

# Single worker is REQUIRED: presence and chat fan-out live in an in-process
# in-memory broker, so the app must run as ONE process. Do not add --workers >1
# or scale to multiple machines without first swapping in a Redis-backed broker.
exec python -m uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips '*'

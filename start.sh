#!/usr/bin/env bash
# SecureConnect-AI: one-command start (macOS / Linux)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

PIP=".venv/bin/pip"
PY=".venv/bin/python"

echo "Installing dependencies (this can take a few minutes the first time)..."
"$PIP" install --upgrade pip >/dev/null
"$PIP" install -r backend/requirements.txt

if [ ! -f "backend/.env" ]; then
    cp backend/.env.example backend/.env
    echo "Created backend/.env from .env.example (edit APP_SECRET for prod)."
fi

echo "Seeding demo data..."
"$PY" -m backend.seed

echo "Starting server at http://localhost:8000 ..."
exec "$PY" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

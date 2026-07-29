#!/usr/bin/env bash
# Convenience launcher for local dev — starts backend (:8000) and frontend (:5173).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
( cd "$here/backend" && pip install -q -r requirements.txt && \
  uvicorn app.main:app --reload --port "${MLB_GPP_PORT:-8000}" ) &
( cd "$here/frontend" && npm install --silent && npm run dev ) &
wait

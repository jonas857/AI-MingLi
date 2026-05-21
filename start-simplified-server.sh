#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PORT="${PORT:-5002}"
HOST="${HOST:-0.0.0.0}"

cd "$APP_DIR"

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export PORT
export HOST
export FLASK_DEBUG="${FLASK_DEBUG:-false}"
export FLASK_ENV="${FLASK_ENV:-production}"

exec gunicorn \
  --bind "${HOST}:${PORT}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-300}" \
  app_simplified:app

#!/bin/bash
set -e

cd /app

if [ -f "/app/.env" ]; then
    set -a
    . /app/.env
    set +a
fi

HOST="${DM_GUNICORN_BIND_HOST}"
PORT="${PORT}"
WORKERS="${DM_GUNICORN_WORKERS}"
THREADS="${DM_GUNICORN_THREADS}"
TIMEOUT="${DM_GUNICORN_TIMEOUT}"
WORKER_CLASS="${DM_GUNICORN_WORKER_CLASS}"

echo "Starting gunicorn on ${HOST}:${PORT}..."

exec uv run gunicorn single_page.app:app \
    --bind "${HOST}:${PORT}" \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --worker-class "${WORKER_CLASS}" \
    --access-logfile - \
    --error-logfile -

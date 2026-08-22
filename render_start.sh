#!/usr/bin/env bash
set -o errexit
set -o nounset

: "${PORT:?Render must provide PORT for web services}"

cd backend
echo "Running database migrations..."
python -m alembic -c alembic.ini upgrade head
echo "Starting application..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"

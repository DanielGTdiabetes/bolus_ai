#!/bin/sh
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# Run migrations (idempotent)
echo "Running database migrations..."
python -m alembic -c "${SCRIPT_DIR}/alembic.ini" upgrade head

# Start the application
echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

#!/bin/sh

# Configuration
# Load environment variables from .env file relative to script location
SCRIPT_DIR="$(dirname "$0")"
ENV_FILE="$SCRIPT_DIR/../deploy/nas/.env"

if [ -f "$ENV_FILE" ]; then
    # POSIX compliant source/export loop
    set -a
    . "$ENV_FILE"
    set +a
else
    echo "Error: .env file not found at $ENV_FILE" - but continuing if vars are in env
fi

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="/tmp/bolus_backup_$TIMESTAMP.sql"

# Telegram Notification Function (Delegated to bolus_app to avoid deps)
send_telegram() {
    local message="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_CHAT_ID" ]; then
        # Check if bolus_app is running to use its python/networking
        # We use python one-liner to send safe JSON
        docker exec bolus_app python -c "
import requests
import os
try:
    requests.post(
        'https://api.telegram.org/bot$BOT_TOKEN/sendMessage',
        json={'chat_id': '$ADMIN_CHAT_ID', 'text': '$message'},
        timeout=5
    )
except: pass" > /dev/null 2>&1
    fi
}

echo "Starting Backup Routine: NAS -> Neon..."

# 1. Dump Local DB
# Access from inside the bolus_db container is easiest, but script runs on host.
# Assuming we run this via docker exec or have pg_dump installed on NAS host.
# Better: Use docker exec to dump from container.

CONTAINER_NAME="bolus_db"
DB_USER="${POSTGRES_USER:-bolus_user}"
DB_NAME="${POSTGRES_DB:-bolus_db}"

echo "Dumping local database..."
if docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" -F c -b -v -f "/tmp/dump.sql"; then
    # Copy out
    docker cp "$CONTAINER_NAME":/tmp/dump.sql "$BACKUP_FILE"
else
    echo "Error: Failed to dump local database."
    send_telegram "❌ Backup Failed: Could not dump local database on NAS."
    exit 1
fi

# 2. Restore to Neon (Remote)
# We need the NEON connection string. 
# It should be in .env as DATABASE_URL_NEON or similar, or we construct it.
# Usually Render uses DATABASE_URL. For NAS, we need a separate variable for the REMOTE target.

if [ -z "$DATABASE_URL_NEON" ]; then
    echo "Error: DATABASE_URL_NEON not defined in .env"
    send_telegram "❌ Backup Failed: Target Neon URL not configured."
    rm "$BACKUP_FILE"
    exit 1
fi

echo "Running Integrity Check: Comparing Local vs Remote timestamps..."

# Get Latest Timestamp (Epoch) from Local NAS
LATEST_NAS=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT EXTRACT(EPOCH FROM MAX(created_at))::int FROM treatments;")
LATEST_NAS=$(echo "$LATEST_NAS" | xargs)
LATEST_NAS=${LATEST_NAS:-0}

# Get Latest Timestamp (Epoch) from Remote Neon
# Use a temporary container to query remote
LATEST_NEON=$(docker run --rm -e DIRECT_URL="$DATABASE_URL_NEON" postgres:16-alpine \
    psql "$DIRECT_URL" -t -c "SELECT EXTRACT(EPOCH FROM MAX(created_at))::int FROM treatments;")
LATEST_NEON=$(echo "$LATEST_NEON" | xargs)
LATEST_NEON=${LATEST_NEON:-0}

echo "Latest Data Check -> Local: $LATEST_NAS | Remote: $LATEST_NEON"

if [ "$LATEST_NEON" -gt "$LATEST_NAS" ]; then
    DIFF=$((LATEST_NEON - LATEST_NAS))
    echo "⚠️ SAFETY STOP: Neon has newer data (+$DIFF sec). Render might have been active."
    echo "Backup aborted to prevent data loss."
    send_telegram "⚠️ Backup ABORTED: Neon DB is ahead of NAS (Render active?). Sync required."
    rm "$BACKUP_FILE"
    exit 1
fi

echo "Safety Check Passed. Restoring to Neon (Overwriting)..."
# We use PGPASSWORD / pg_restore locally on host (requires tools) OR use a temporary docker container with tools.
# Using a temporary docker container is safer/cleaner than ensuring pg_restore is on NAS host.

docker run --rm -v "$BACKUP_FILE":/backup.sql -e DIRECT_URL="$DATABASE_URL_NEON" postgres:16-alpine \
    sh -c "pg_restore --clean --if-exists --no-owner --no-privileges -d \"\$DIRECT_URL\" /backup.sql"

if [ $? -eq 0 ]; then
    echo "Success: Backup restored to Neon."
    send_telegram "✅ Backup Successful: NAS Database synchronized to Neon."
else
    echo "Error: Failed to restore to Neon."
    send_telegram "❌ Backup Failed: Could not restore data to Neon."
    rm "$BACKUP_FILE"
    exit 1
fi

# Cleanup
rm "$BACKUP_FILE"
echo "Done."

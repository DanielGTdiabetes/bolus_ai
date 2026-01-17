#!/bin/bash

# Configuration
# Load environment variables from .env file relative to script location
SCRIPT_DIR="$(dirname "$0")"
ENV_FILE="$SCRIPT_DIR/../deploy/nas/.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="/tmp/bolus_backup_$TIMESTAMP.sql"

# Telegram Notification Function
send_telegram() {
    local message="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d chat_id="$ADMIN_CHAT_ID" \
            -d text="$message" > /dev/null
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

echo "Restoring to Neon (Overwriting)..."
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

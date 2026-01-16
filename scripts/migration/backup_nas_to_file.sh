#!/bin/bash

# Configuration
CONTAINER_NAME="nas-db-1"
LOCAL_DB_USER="bolus_user"
LOCAL_DB_NAME="bolus_db"
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M)
BACKUP_FILE="$BACKUP_DIR/bolus_nas_$TIMESTAMP.sql"

mkdir -p "$BACKUP_DIR"

echo "=== Backup: NAS Database -> File ==="

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Error: Container '$CONTAINER_NAME' is not running."
    exit 1
fi

echo "Creating dump from $CONTAINER_NAME..."
docker exec "$CONTAINER_NAME" pg_dump -U "$LOCAL_DB_USER" --clean --if-exists "$LOCAL_DB_NAME" > "$BACKUP_FILE"

if [ -s "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ Backup successful: $BACKUP_FILE ($SIZE)"
else
    echo "❌ Backup failed or empty."
    rm -f "$BACKUP_FILE"
    exit 1
fi

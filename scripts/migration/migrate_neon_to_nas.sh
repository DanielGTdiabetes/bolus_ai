#!/bin/bash

# Configuration
NEON_DB_URL="${NEON_DB_URL:-replace_me_with_neon_connection_string}"
CONTAINER_NAME="nas-db-1" # Ensure this matches your docker ps output
LOCAL_DB_USER="bolus_user"
LOCAL_DB_NAME="bolus_db"
DUMP_FILE="neon_backup_$(date +%Y%m%d).sql"

echo "=== Starting Migration: Neon -> NAS (Dockerized) ==="

# 1. Validation
if [[ "$NEON_DB_URL" == *"replace_me"* ]]; then
    echo "❌ Error: Please set NEON_DB_URL env var or edit the script."
    exit 1
fi

echo "1. Dumping data from Neon (using temporary postgres container)..."
# We run a temporary container to perform the dump, mounting the current directory to save the file
docker run --rm \
    -v "$(pwd):/tmp_dump" \
    postgres:15-alpine \
    pg_dump "$NEON_DB_URL" --no-owner --no-acl --clean --if-exists -f "/tmp_dump/$DUMP_FILE"

if [ ! -f "$DUMP_FILE" ]; then
    echo "❌ Dump failed: File was not created."
    exit 1
fi

FILE_SIZE=$(wc -c < "$DUMP_FILE")
if [ "$FILE_SIZE" -lt 100 ]; then
    echo "❌ Dump failed: File is too small ($FILE_SIZE bytes). Check permissions or URL."
    exit 1
fi

echo "✅ Dump successful: $DUMP_FILE ($FILE_SIZE bytes)"
echo "   Sanity Check: First 5 lines of dump:"
head -n 5 "$DUMP_FILE"

echo "2. Copying dump to NAS Database Container ($CONTAINER_NAME)..."
# Verify container exists
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Error: Container '$CONTAINER_NAME' is not running."
    exit 1
fi

docker cp "$DUMP_FILE" "$CONTAINER_NAME":/tmp/"$DUMP_FILE"

echo "3. Restoring data to Local NAS Database..."
docker exec -i "$CONTAINER_NAME" psql -U "$LOCAL_DB_USER" -d "$LOCAL_DB_NAME" -f /tmp/"$DUMP_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Migration Complete! Data is now in your local NAS."
    echo "🧹 Cleaning up..."
    rm "$DUMP_FILE"
    docker exec "$CONTAINER_NAME" rm /tmp/"$DUMP_FILE"
else
    echo "❌ Restore failed."
    exit 1
fi

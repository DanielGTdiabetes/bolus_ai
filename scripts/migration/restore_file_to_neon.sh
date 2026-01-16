#!/bin/bash

# Configuration
NEON_DB_URL="${NEON_DB_URL:-replace_me_with_neon_connection_string}"
# Usage: ./restore_file_to_neon.sh ./backups/my_backup.sql

BACKUP_FILE="$1"

echo "=== Restore: File -> Neon (FAILOVER/RECOVERY) ==="
echo "⚠️  WARNING: This will OVERWRITE data in the NEON database."
echo "Target: $NEON_DB_URL"

if [ -z "$BACKUP_FILE" ]; then
    echo "❌ Usage: $0 <path_to_sql_file>"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ File not found: $BACKUP_FILE"
    exit 1
fi

read -p "Are you sure you want to proceed? (y/N): " confirm
if [[ "$confirm" != "y" ]]; then
    echo "Aborted."
    exit 0
fi

echo "Restoring $BACKUP_FILE to Neon..."

# Use Docker to run psql so we don't need it on host
docker run --rm -i \
    -e PGPASSWORD=unused \
    postgres:16-alpine \
    psql "$NEON_DB_URL" < "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Restore to Neon completed successfully."
else
    echo "❌ Restore failed."
    exit 1
fi

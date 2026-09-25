#!/usr/bin/env bash
set -e

# IoT Telemetry Hub Restore Script
# Restores a compressed PostgreSQL dump into the telemetry database.
# WARNING: This will overwrite existing data.

if [ -z "$1" ]; then
    echo "Usage: $0 <path_to_backup.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Error: Backup file ${BACKUP_FILE} not found."
    exit 1
fi

echo "WARNING: This will drop the existing telemetry database and restore from ${BACKUP_FILE}."
read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 1
fi

echo "Stopping API and Worker containers..."
docker compose -f /opt/iot-telemetry-hub/compose.yaml stop api worker

echo "Restoring database..."
# Drop schema and recreate to ensure clean restore, then gunzip and restore
docker compose -f /opt/iot-telemetry-hub/compose.yaml exec -T db psql -U telemetry telemetry -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
gunzip -c "${BACKUP_FILE}" | docker compose -f /opt/iot-telemetry-hub/compose.yaml exec -T db psql -U telemetry telemetry

echo "Starting API and Worker containers..."
docker compose -f /opt/iot-telemetry-hub/compose.yaml start api worker

echo "Restore completed successfully."

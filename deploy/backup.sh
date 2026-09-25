#!/usr/bin/env bash
set -e

# IoT Telemetry Hub Backup Script
# Creates a compressed PostgreSQL dump of the telemetry database.

BACKUP_DIR="/opt/iot-telemetry-hub/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/telemetry_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "Starting database backup to ${BACKUP_FILE}..."
docker compose -f /opt/iot-telemetry-hub/compose.yaml exec -T db pg_dump -U telemetry telemetry | gzip > "${BACKUP_FILE}"

echo "Backup completed successfully."
# Optional: retain only last 7 days of backups
find "${BACKUP_DIR}" -name "telemetry_*.sql.gz" -type f -mtime +7 -delete
echo "Cleaned up old backups."

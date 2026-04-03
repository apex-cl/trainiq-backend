#!/bin/sh
#
# backup.sh — PostgreSQL Backup mit S3-Upload und automatischer Aufräumung
#
# Cron: Wird um 03:00 Uhr ausgeführt (siehe docker-compose.backend.yml)
# Variablen: POSTGRES_HOST, POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD
#            S3_BUCKET, S3_ENDPOINT (optional), BACKUP_RETENTION_DAYS

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
BACKUP_FILE="${BACKUP_DIR}/trainiq_${TIMESTAMP}.sql.gz"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

echo "[$(date)] === TrainIQ DB-Backup gestartet ==="

# Backup-Verzeichnis sicherstellen
mkdir -p "$BACKUP_DIR"

# PostgreSQL Dump (komprimiert)
echo "[$(date)] Erstelle pg_dump..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "$POSTGRES_HOST" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --no-owner \
    --no-privileges \
    --format=plain \
    | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date)] Dump erstellt: $BACKUP_FILE ($BACKUP_SIZE)"

# S3 Upload (falls konfiguriert)
if [ -n "${S3_BUCKET:-}" ]; then
    echo "[$(date)] Lade Backup zu S3 hoch..."

    # AWS CLI Argumente aufbauen
    AWS_ARGS=()
    if [ -n "${S3_ENDPOINT:-}" ]; then
        AWS_ARGS=(--endpoint-url "$S3_ENDPOINT")
    fi

    aws s3 cp "$BACKUP_FILE" "s3://${S3_BUCKET}/db-backups/trainiq_${TIMESTAMP}.sql.gz" \
        "${AWS_ARGS[@]}" \
        --storage-class STANDARD_IA

    echo "[$(date)] S3-Upload abgeschlossen."

    # Alte Backups auf S3 löschen
    echo "[$(date)] Lösche S3-Backups älter als ${RETENTION_DAYS} Tage..."
    CUTOFF_DATE=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d 2>/dev/null \
        || date -v-${RETENTION_DAYS}d +%Y-%m-%d 2>/dev/null || echo "")

    if [ -n "$CUTOFF_DATE" ]; then
        aws s3 ls "s3://${S3_BUCKET}/db-backups/" "${AWS_ARGS[@]}" | \
            awk '{print $4}' | \
            while read -r file; do
                file_date=$(echo "$file" | grep -oP '\d{8}' | head -1)
                if [ -n "$file_date" ] && [ "$file_date" \< "$(echo $CUTOFF_DATE | tr -d '-')" ]; then
                    echo "  Lösche: $file"
                    aws s3 rm "s3://${S3_BUCKET}/db-backups/$file" "${AWS_ARGS[@]}"
                fi
            done
    fi
fi

# Lokale Backups aufräumen
echo "[$(date)] Lösche lokale Backups älter als ${RETENTION_DAYS} Tage..."
find "$BACKUP_DIR" -name "trainiq_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete -print | \
    while read -r f; do echo "  Gelöscht: $f"; done

echo "[$(date)] === Backup abgeschlossen ==="

#!/usr/bin/env bash

set -euo pipefail

SOURCE_DIR="${1:-/data}"
BACKUP_ROOT="${2:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT%/}/${TIMESTAMP}"

mkdir -p "${BACKUP_DIR}"

if [[ -f "${SOURCE_DIR}/pm_dashboard.db" ]]; then
  cp "${SOURCE_DIR}/pm_dashboard.db" "${BACKUP_DIR}/pm_dashboard.db"
fi

if [[ -d "${SOURCE_DIR}/uploads" ]]; then
  tar -czf "${BACKUP_DIR}/uploads.tar.gz" -C "${SOURCE_DIR}" uploads
fi

cat <<EOF
Backup created at ${BACKUP_DIR}
- Database: ${BACKUP_DIR}/pm_dashboard.db
- Upload archive: ${BACKUP_DIR}/uploads.tar.gz
EOF

#!/usr/bin/env bash

set -euo pipefail

BACKUP_DIR="${1:?usage: restore_data.sh <backup-dir> [target-data-dir]}"
TARGET_DIR="${2:-/data}"

mkdir -p "${TARGET_DIR}/uploads"

if [[ -f "${BACKUP_DIR}/pm_dashboard.db" ]]; then
  cp "${BACKUP_DIR}/pm_dashboard.db" "${TARGET_DIR}/pm_dashboard.db"
fi

if [[ -f "${BACKUP_DIR}/uploads.tar.gz" ]]; then
  rm -rf "${TARGET_DIR}/uploads"
  tar -xzf "${BACKUP_DIR}/uploads.tar.gz" -C "${TARGET_DIR}"
fi

cat <<EOF
Restore completed into ${TARGET_DIR}
- Database: ${TARGET_DIR}/pm_dashboard.db
- Uploads: ${TARGET_DIR}/uploads
EOF

#!/bin/bash
# Open WebUI のユーザー退避スクリプト。
# user / auth テーブルだけを INSERT 文として吐く。チャット履歴・設定は含まない。
set -euo pipefail

CONTAINER="${OWUI_CONTAINER:-llens-open-webui}"
DB_PATH_IN_CONTAINER="/app/backend/data/webui.db"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTDIR="${OWUI_BACKUP_DIR:-${SCRIPT_DIR}/../../backups}"
mkdir -p "${OUTDIR}"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="${OUTDIR}/owui-users-${STAMP}.sql"
TMPDB=$(mktemp -t webui-backup-XXXXXX.db)
trap 'rm -f "${TMPDB}"' EXIT

if ! command -v sqlite3 >/dev/null; then
  echo "[x] sqlite3 not found on host" >&2
  exit 1
fi

if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
  echo "[x] container not found: ${CONTAINER}" >&2
  exit 1
fi

WAS_RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")

if [[ "${WAS_RUNNING}" == "true" ]]; then
  echo "[*] Stopping ${CONTAINER}"
  docker stop "${CONTAINER}" >/dev/null
fi

echo "[*] Copying DB out of container"
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}" "${TMPDB}"
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}-wal" "${TMPDB}-wal" 2>/dev/null || true
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}-shm" "${TMPDB}-shm" 2>/dev/null || true

if [[ "${WAS_RUNNING}" == "true" ]]; then
  echo "[*] Starting ${CONTAINER}"
  docker start "${CONTAINER}" >/dev/null
fi

echo "[*] Checkpointing WAL"
sqlite3 "${TMPDB}" "PRAGMA wal_checkpoint(TRUNCATE);"

echo "[*] Dumping user + auth tables → ${OUT}"
sqlite3 "${TMPDB}" <<'SQL' > "${OUT}"
.mode insert user
SELECT * FROM user;
.mode insert auth
SELECT * FROM auth;
SQL

USER_COUNT=$(grep -c '^INSERT INTO "\?user"\?' "${OUT}" || true)
AUTH_COUNT=$(grep -c '^INSERT INTO "\?auth"\?' "${OUT}" || true)

sha256sum "${OUT}" > "${OUT}.sha256"

echo "[✓] Done"
echo "    file:        ${OUT}"
echo "    user rows:   ${USER_COUNT}"
echo "    auth rows:   ${AUTH_COUNT}"
echo "    checksum:    ${OUT}.sha256"
ls -lh "${OUT}" "${OUT}.sha256"

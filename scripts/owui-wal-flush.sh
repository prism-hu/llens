#!/bin/bash
# Open WebUI の SQLite WAL をチェックポイント (本体に統合) する。
set -euo pipefail

CONTAINER="${OWUI_CONTAINER:-llens-open-webui}"
DB_PATH_IN_CONTAINER="/app/backend/data/webui.db"

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

WORKDIR=$(mktemp -d -t owui-checkpoint-XXXXXX)
trap 'rm -rf "${WORKDIR}"' EXIT

echo "[*] Copying DB out of container"
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}" "${WORKDIR}/webui.db"
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}-wal" "${WORKDIR}/webui.db-wal" 2>/dev/null || true
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}-shm" "${WORKDIR}/webui.db-shm" 2>/dev/null || true

echo "[*] Checkpointing WAL"
sqlite3 "${WORKDIR}/webui.db" "PRAGMA wal_checkpoint(TRUNCATE);"

echo "[*] Copying back into container"
docker cp "${WORKDIR}/webui.db" "${CONTAINER}:${DB_PATH_IN_CONTAINER}"
: > "${WORKDIR}/empty"
docker cp "${WORKDIR}/empty" "${CONTAINER}:${DB_PATH_IN_CONTAINER}-wal" 2>/dev/null || true
docker cp "${WORKDIR}/empty" "${CONTAINER}:${DB_PATH_IN_CONTAINER}-shm" 2>/dev/null || true

if [[ "${WAS_RUNNING}" == "true" ]]; then
  echo "[*] Starting ${CONTAINER}"
  docker start "${CONTAINER}" >/dev/null
fi

echo "[✓] Done"

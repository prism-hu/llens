#!/bin/bash
# Open WebUI のユーザー復元スクリプト (冪等)。
#   - 判定は email のみ。target に同じ email があれば丸ごとスキップ
#   - user + auth は id で紐づけてセットで入る (片方だけ入ることは無い)
#   - 既存の行は上書きしない (= 搬入先で追加されたユーザーは保持)
#   - 同じ dump を何度流しても安全 (2 回目以降は全件 skip される)
set -euo pipefail

DUMP="${1:-}"
if [[ -z "${DUMP}" || ! -f "${DUMP}" ]]; then
  echo "Usage: $0 <owui-users-YYYYMMDD_HHMMSS.sql>" >&2
  exit 1
fi

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

if [[ -f "${DUMP}.sha256" ]]; then
  echo "[*] Verifying checksum"
  ( cd "$(dirname "${DUMP}")" && sha256sum -c "$(basename "${DUMP}").sha256" )
else
  echo "[!] No ${DUMP}.sha256 — skipping checksum verification"
fi

WORKDIR=$(mktemp -d -t owui-restore-XXXXXX)
trap 'rm -rf "${WORKDIR}"' EXIT

LIVE_DB="${WORKDIR}/webui.db"
SCRATCH_DB="${WORKDIR}/scratch.db"

WAS_RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")

if [[ "${WAS_RUNNING}" == "true" ]]; then
  echo "[*] Stopping ${CONTAINER}"
  docker stop "${CONTAINER}" >/dev/null
fi

echo "[*] Copying DB out of container"
docker cp "${CONTAINER}:${DB_PATH_IN_CONTAINER}" "${LIVE_DB}"

echo "[*] Building scratch DB from live schema"
# Rebuild just user + auth on the scratch DB using the live schema so the
# column order matches. If the dump was taken from an incompatible schema
# (different column count), the subsequent load will fail loudly.
sqlite3 "${LIVE_DB}" ".schema user" ".schema auth" > "${WORKDIR}/schema.sql"
sqlite3 "${SCRATCH_DB}" < "${WORKDIR}/schema.sql"

echo "[*] Loading dump into scratch DB"
sqlite3 "${SCRATCH_DB}" < "${DUMP}"

DUMP_USERS=$(sqlite3 "${SCRATCH_DB}" "SELECT COUNT(*) FROM user;")
DUMP_AUTHS=$(sqlite3 "${SCRATCH_DB}" "SELECT COUNT(*) FROM auth;")
BEFORE_USERS=$(sqlite3 "${LIVE_DB}" "SELECT COUNT(*) FROM user;")

echo "[*] Merging (existing email = skip; user+auth kept atomic)"
sqlite3 "${LIVE_DB}" <<SQL
ATTACH '${SCRATCH_DB}' AS src;

CREATE TEMP TABLE importable AS
  SELECT s.id AS id
    FROM src.user AS s
   WHERE s.email NOT IN (SELECT email FROM main.user);

INSERT INTO main.user SELECT * FROM src.user WHERE id IN (SELECT id FROM importable);
INSERT INTO main.auth SELECT * FROM src.auth WHERE id IN (SELECT id FROM importable);

DETACH src;
SQL

AFTER_USERS=$(sqlite3 "${LIVE_DB}" "SELECT COUNT(*) FROM user;")
AFTER_AUTHS=$(sqlite3 "${LIVE_DB}" "SELECT COUNT(*) FROM auth;")
INSERTED=$(( AFTER_USERS - BEFORE_USERS ))
SKIPPED=$(( DUMP_USERS - INSERTED ))

echo "[*] Copying merged DB back into container"
docker cp "${LIVE_DB}" "${CONTAINER}:${DB_PATH_IN_CONTAINER}"

if [[ "${WAS_RUNNING}" == "true" ]]; then
  echo "[*] Starting ${CONTAINER}"
  docker start "${CONTAINER}" >/dev/null
fi

echo "[✓] Done"
echo "    dump:             ${DUMP}"
echo "    users in dump:    ${DUMP_USERS}  (auths: ${DUMP_AUTHS})"
echo "    users before:     ${BEFORE_USERS}"
echo "    inserted:         ${INSERTED}"
echo "    skipped (exist):  ${SKIPPED}"
echo "    users after:      ${AFTER_USERS}  (auths: ${AFTER_AUTHS})"

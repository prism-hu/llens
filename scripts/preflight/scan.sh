#!/bin/bash
#==============================================================================
# preflight-scan.sh
#   ClamAV による全体スキャン (院外シャットダウン直前用)
#
# 使い方:
#   make preflight-scan
#   または: sudo bash scripts/preflight-scan.sh
#
# 出力:
#   <repo>/logs/preflight-scan_<TS>.log     スクリプト実行ログ
#   <repo>/logs/clamscan/clamscan_<TS>.log  スキャン結果本体
#
# 終了コード:
#   0  感染なし
#   2  感染検知あり (搬入中止)
#   それ以外  ClamAV 自体のエラー
#==============================================================================

set -uo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: root権限で実行してください (make preflight-scan を推奨)"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
LOGDIR="$REPO_DIR/logs"
SCANDIR="$LOGDIR/clamscan"
TS=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/preflight-scan_${TS}.log"
SCANLOG="$SCANDIR/clamscan_${TS}.log"

mkdir -p "$LOGDIR" "$SCANDIR"
chmod 700 "$LOGDIR" "$SCANDIR"
: > "$LOGFILE"
: > "$SCANLOG"
chmod 600 "$LOGFILE" "$SCANLOG"

if [ -n "${SUDO_USER:-}" ]; then
    SUDO_GID=$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")
    chown "$SUDO_USER:$SUDO_GID" "$LOGDIR" "$SCANDIR" "$LOGFILE" "$SCANLOG" 2>/dev/null || true
fi

exec > >(tee -a "$LOGFILE") 2>&1

section() {
    echo ""
    echo "------ $* ------"
}

echo "=============================================================="
echo " preflight-scan.sh   $(date '+%Y-%m-%d %H:%M:%S')"
echo " host=$(hostname)   invoker=${SUDO_USER:-root}"
echo "=============================================================="

if ! command -v clamscan >/dev/null 2>&1; then
    echo "ERROR: clamscan が未インストールです (apt install clamav)"
    exit 1
fi

#------------------------------------------------------------------------------
section "ClamAV パターン最新化 (freshclam)"
# clamav-freshclam サービスが動いていればロック競合するため一旦停止
systemctl stop clamav-freshclam 2>/dev/null || true
freshclam || { echo "ERROR: freshclam 失敗 — 院外ネットワーク接続を確認"; exit 1; }

section "パターンファイル情報"
for f in /var/lib/clamav/main.cvd /var/lib/clamav/daily.cvd /var/lib/clamav/bytecode.cvd \
         /var/lib/clamav/main.cld /var/lib/clamav/daily.cld /var/lib/clamav/bytecode.cld; do
    [ -f "$f" ] && sigtool --info "$f" 2>/dev/null | grep -E "Build time|Version" | sed "s|^|$f: |"
done

#------------------------------------------------------------------------------
section "フルスキャン実行 (除外: モデル / Docker / 自身のログ)"
echo "  結果ログ: $SCANLOG"
echo ""

# モデルディレクトリ(数百GB)、Docker レイヤ、本スクリプトのログは除外
# --max-filesize / --max-scansize で巨大ファイル(モデルshard 漏れ等)を早期スキップ
clamscan -r --infected \
    --exclude-dir='^/sys' \
    --exclude-dir='^/proc' \
    --exclude-dir='^/dev' \
    --exclude-dir='^/var/lib/docker' \
    --exclude-dir='^/var/lib/containerd' \
    --exclude-dir="^${REPO_DIR}/models" \
    --exclude-dir="^${REPO_DIR}/logs" \
    --exclude-dir='^/opt/llens/models' \
    --max-filesize=500M \
    --max-scansize=2000M \
    --log="$SCANLOG" \
    / || true

# スキャンログもユーザー所有に戻す (clamscan が root で書き直すため)
if [ -n "${SUDO_USER:-}" ]; then
    chown "$SUDO_USER:$SUDO_GID" "$SCANLOG" 2>/dev/null || true
    chmod 600 "$SCANLOG"
fi

#------------------------------------------------------------------------------
section "スキャン結果サマリ"
tail -20 "$SCANLOG"

INFECTED=$(grep -E "^Infected files:" "$SCANLOG" | awk '{print $3}')
echo ""
echo "=============================================================="
if [ "$INFECTED" = "0" ]; then
    echo " [OK] 感染ファイルなし (Infected files: 0)"
    echo " 実行ログ: $LOGFILE"
    echo " 詳細ログ: $SCANLOG"
    echo "=============================================================="
    exit 0
else
    echo " [NG] 感染検知あり (Infected files: $INFECTED) — 搬入中止"
    echo " 実行ログ: $LOGFILE"
    echo " 詳細ログ: $SCANLOG"
    echo "=============================================================="
    exit 2
fi

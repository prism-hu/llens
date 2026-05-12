#!/bin/bash
#==============================================================================
# preflight-apply.sh
#   搬入前作業の構成適用スクリプト
#   全操作はべき等。何度叩いても同じ結果になる
#
# 使い方:
#   make preflight-apply
#   または: sudo bash scripts/preflight-apply.sh
#
# 出力:
#   <repo>/logs/preflight-apply_<TS>.log
#
# 含まれるもの:
#   A. アプリ構成 (恒久設定)
#     A2  kernel / nvidia パッケージの apt-mark hold
#     A3  nvidia-persistenced の有効化
#     ※ A1 (時刻同期) は院内NTP情報が必要なため audit で確認のみ、手動対応
#   B. 不要設定の omit (通信抑止)
#     B1  OS 自動更新の停止
#     B2  Snap 自動更新の保留
#     B3  テレメトリ・クラッシュレポート系の削除
#     B4  motd-news の無効化
#     B5  ClamAV freshclam の停止
#     B6  Ubuntu Pro / ESM タイマーの停止
#==============================================================================

set -uo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: root権限で実行してください (make preflight-apply を推奨)"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
LOGDIR="$REPO_DIR/logs"
TS=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/preflight-apply_${TS}.log"

mkdir -p "$LOGDIR"
chmod 700 "$LOGDIR"
: > "$LOGFILE"
chmod 600 "$LOGFILE"

if [ -n "${SUDO_USER:-}" ]; then
    SUDO_GID=$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")
    chown "$SUDO_USER:$SUDO_GID" "$LOGDIR" "$LOGFILE" 2>/dev/null || true
fi

exec > >(tee -a "$LOGFILE") 2>&1

section() {
    echo ""
    echo "------ $* ------"
}

echo "=============================================================="
echo " preflight-apply.sh   $(date '+%Y-%m-%d %H:%M:%S')"
echo " host=$(hostname)   invoker=${SUDO_USER:-root}"
echo " ※ 全操作はべき等 — 再実行しても安全"
echo "=============================================================="

#==============================================================================
# A. アプリ構成
#==============================================================================
section "[A2] kernel / nvidia パッケージの apt-mark hold"

KERNEL_PKGS="linux-image-generic linux-headers-generic"
RUNNING_KERNEL="linux-image-$(uname -r) linux-headers-$(uname -r)"
NVIDIA_PKGS=$(dpkg -l 'nvidia-driver-*' 'nvidia-utils-*' 'libnvidia-*' 2>/dev/null \
              | awk '/^ii/ {print $2}' | tr '\n' ' ')

TARGETS="$KERNEL_PKGS $RUNNING_KERNEL $NVIDIA_PKGS"
echo "対象: $TARGETS"
# apt-mark hold は対象が既に hold でも exit 0、未インストールパッケージは無視されるためべき等
# shellcheck disable=SC2086
apt-mark hold $TARGETS || true

echo "現在の hold 一覧:"
apt-mark showhold || true

#------------------------------------------------------------------------------
section "[A3] nvidia-persistenced 有効化"
if systemctl list-unit-files nvidia-persistenced.service 2>/dev/null | grep -q nvidia-persistenced; then
    systemctl enable --now nvidia-persistenced
    echo "  enabled / active: $(systemctl is-active nvidia-persistenced)"
else
    echo "[SKIP] nvidia-persistenced 未インストール (NVIDIAドライバ標準同梱、要確認)"
fi

#==============================================================================
# B. 不要設定の omit
#==============================================================================
section "[B1] OS 自動更新の停止"
systemctl disable --now unattended-upgrades 2>/dev/null || true
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
echo "  unattended-upgrades:    $(systemctl is-enabled unattended-upgrades 2>/dev/null || echo n/a)"
echo "  apt-daily.timer:        $(systemctl is-enabled apt-daily.timer 2>/dev/null || echo n/a)"
echo "  apt-daily-upgrade.timer:$(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || echo n/a)"

#------------------------------------------------------------------------------
section "[B2] Snap 自動更新の保留"
if command -v snap >/dev/null 2>&1; then
    snap refresh --hold || true
    snap refresh --time 2>/dev/null | grep -iE "hold|next" || true
else
    echo "[SKIP] snap 未インストール"
fi

#------------------------------------------------------------------------------
section "[B3] テレメトリ・クラッシュレポート系の削除"
apt-get remove -y --purge popularity-contest apport whoopsie 2>/dev/null || true
systemctl disable --now apport.service 2>/dev/null || true
for pkg in popularity-contest apport whoopsie; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        echo "  $pkg: still installed (要確認)"
    else
        echo "  $pkg: removed"
    fi
done

#------------------------------------------------------------------------------
section "[B4] motd-news の無効化"
if [ -f /etc/default/motd-news ]; then
    sed -i 's/^ENABLED=1/ENABLED=0/' /etc/default/motd-news
    grep -E "^ENABLED=" /etc/default/motd-news
else
    echo "[SKIP] /etc/default/motd-news なし"
fi

#------------------------------------------------------------------------------
section "[B5] ClamAV freshclam 自動更新の停止"
if systemctl list-unit-files 2>/dev/null | grep -q '^clamav-freshclam'; then
    systemctl disable --now clamav-freshclam 2>/dev/null || true
    echo "  clamav-freshclam: $(systemctl is-enabled clamav-freshclam 2>/dev/null || echo n/a)"
else
    echo "[SKIP] clamav-freshclam 未インストール"
fi

#------------------------------------------------------------------------------
section "[B6] Ubuntu Pro / ESM 関連タイマーの停止"
for unit in ua-timer.timer esm-cache.service apt-news.service; do
    if systemctl list-unit-files "$unit" 2>/dev/null | grep -q "$unit"; then
        systemctl disable --now "$unit" 2>/dev/null || true
        echo "  $unit: $(systemctl is-enabled "$unit" 2>/dev/null || echo n/a)"
    else
        echo "  $unit: not-installed"
    fi
done

echo ""
echo "=============================================================="
echo " 完了 (べき等処理のため再実行しても結果は変わりません)"
echo " ログ: $LOGFILE"
echo ""
echo " 次のステップ:"
echo "   1. make preflight-audit   # 適用後の状態を確認"
echo "   2. 時刻同期 (A1) を院内NTP設定 — 手動対応"
echo "   3. シャットダウン直前: make preflight-scan"
echo "=============================================================="

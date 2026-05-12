#!/bin/bash
#==============================================================================
# preflight-audit.sh
#   搬入前作業の read-only な現状確認スクリプト
#   いつ何度実行しても安全 (副作用なし)
#
# 使い方:
#   make preflight-audit
#   または: sudo bash scripts/preflight-audit.sh
#
# 出力:
#   <repo>/logs/preflight-audit_<TS>.log
#==============================================================================

set -uo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: root権限で実行してください (make preflight-audit を推奨)"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
LOGDIR="$REPO_DIR/logs"
TS=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/preflight-audit_${TS}.log"

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
echo " preflight-audit.sh   $(date '+%Y-%m-%d %H:%M:%S')"
echo " host=$(hostname)   invoker=${SUDO_USER:-root}"
echo "=============================================================="

#------------------------------------------------------------------------------
# [A0] SSH 設定確認 (最重要 — 想定外の鍵が混じってないか目視必須)
#------------------------------------------------------------------------------
section "[A0] sshd 実効設定"
sshd -T 2>/dev/null | grep -E "^(port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication|allowusers|allowgroups) " \
    || echo "  (sshd -T 失敗)"

section "[A0] sshd LISTEN ポート"
ss -tlnp 2>/dev/null | grep sshd || echo "  (sshd LISTEN なし — 要確認)"

section "[A0] authorized_keys (フィンガープリント)"
for d in /root /home/*; do
    ak="$d/.ssh/authorized_keys"
    if [ -f "$ak" ]; then
        echo "[$ak]"
        ssh-keygen -lf "$ak" 2>/dev/null || cat "$ak"
    fi
done

section "[A0] 直近ログイン (last -n 10)"
last -n 10 -a 2>/dev/null | head -12

section "[A0] SSH 失敗ログ (直近7日)"
journalctl -u ssh --since "7 days ago" 2>/dev/null | grep -iE "fail|invalid" | tail -5 \
    || echo "  (記録なし)"

#------------------------------------------------------------------------------
# システム状態スナップショット
#------------------------------------------------------------------------------
section "有効な systemd timer"
systemctl list-timers --all --no-pager

section "cron 設定"
ls -la /etc/cron.*/ 2>/dev/null || true
cat /etc/crontab 2>/dev/null || true
for u in $(cut -f1 -d: /etc/passwd); do
    ct=$(crontab -u "$u" -l 2>/dev/null) && echo "--- user: $u ---" && echo "$ct"
done

section "現在の外向き接続"
ss -tupn state established 2>/dev/null || true

#------------------------------------------------------------------------------
# A) アプリ構成の現状
#------------------------------------------------------------------------------
section "[A1] 時刻同期"
systemctl is-active systemd-timesyncd 2>/dev/null || echo "  inactive"
if [ -f /etc/systemd/timesyncd.conf ]; then
    grep -E "^[^#]*NTP=" /etc/systemd/timesyncd.conf || echo "  NTP=未設定 (デフォルト ntp.ubuntu.com 等)"
fi

section "[A2] kernel / nvidia パッケージの hold 状況"
apt-mark showhold 2>/dev/null | grep -E "linux-|nvidia-" || echo "  (該当 hold なし)"

section "[A3] nvidia-persistenced"
echo -n "  enabled: " ; systemctl is-enabled nvidia-persistenced 2>/dev/null || echo "not-installed"
echo -n "  active:  " ; systemctl is-active  nvidia-persistenced 2>/dev/null || true

#------------------------------------------------------------------------------
# B) 余計な設定の現状
#------------------------------------------------------------------------------
section "[B1] OS 自動更新"
for unit in unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    echo "  $unit: ${state:-not-installed}"
done

section "[B2] Snap"
if command -v snap >/dev/null 2>&1; then
    snap refresh --time 2>/dev/null | grep -iE "hold|next|last" || true
else
    echo "  snap 未インストール"
fi

section "[B3] テレメトリ系インストール状況"
for pkg in popularity-contest apport whoopsie; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        echo "  $pkg: installed"
    else
        echo "  $pkg: not-installed"
    fi
done

section "[B4] motd-news"
if [ -f /etc/default/motd-news ]; then
    grep -E "^ENABLED=" /etc/default/motd-news || echo "  ENABLED= 未設定"
else
    echo "  /etc/default/motd-news なし"
fi

section "[B5] ClamAV freshclam"
state=$(systemctl is-enabled clamav-freshclam 2>/dev/null || true)
echo "  clamav-freshclam: ${state:-not-installed}"

section "[B6] Ubuntu Pro / ESM 関連"
for unit in ua-timer.timer esm-cache.service apt-news.service; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    echo "  $unit: ${state:-not-installed}"
done

echo ""
echo "=============================================================="
echo " 完了"
echo " ログ: $LOGFILE"
echo "=============================================================="

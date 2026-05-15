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
#     A4  UFW 設定 (default deny incoming + 必要 allow)
#     A5  SSH ハードニング (/etc/ssh/sshd_config.d/99-llens.conf)
#     ※ A1 (時刻同期) は院内NTP情報が必要なため audit で確認のみ、手動対応
#   B. 不要設定の omit (通信抑止 / 攻撃面削減)
#     B1  OS 自動更新の停止 (apt 系)
#     B2  Snap 自動更新の保留
#     B3  テレメトリ・クラッシュレポート系の削除
#     B4  motd-news の無効化
#     B5  不要・自動更新サービスの停止 (まとめ)
#         clamav-freshclam / ua-timer / esm-cache / apt-news /
#         rpcbind / slurmctld / slurmd / cups / cups-browsed /
#         postfix / nfs-server / nfs-kernel-server / rpc-statd
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

#------------------------------------------------------------------------------
section "[A4] UFW 設定"
# 同一ルールは ufw 内部で重複追加されないためべき等。
# default policies と --force enable も idempotent (既設定なら no-op)。
if ! command -v ufw >/dev/null 2>&1; then
    echo "[SKIP] ufw 未インストール (apt install ufw)"
else
    ufw default deny incoming  >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow 22/tcp                                comment 'SSH'              >/dev/null
    ufw allow 80/tcp                                comment 'Caddy -> OWUI'    >/dev/null
    ufw allow 9000/tcp                              comment 'Grafana'          >/dev/null
    ufw allow from 172.16.0.0/12 to any port 8000   comment 'Docker -> SGLang' >/dev/null
    ufw allow from 100.64.0.0/10 to any port 8000   comment 'Tailnet -> SGLang' >/dev/null
    ufw --force enable >/dev/null
    echo "現在の UFW ルール:"
    ufw status numbered
fi

#------------------------------------------------------------------------------
section "[A5] SSH ハードニング"
# sshd_config 本体は触らず、Include される drop-in に書き出し。
# 同内容を毎回上書きするためべき等。
SSHD_CONF=/etc/ssh/sshd_config.d/99-llens.conf
cat > "$SSHD_CONF" <<'EOF'
# Managed by preflight-apply.sh — 手動編集は次回 apply で上書きされる
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
chmod 644 "$SSHD_CONF"
echo "  書き出し: $SSHD_CONF"

if ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d' /etc/ssh/sshd_config 2>/dev/null; then
    echo "  [WARN] /etc/ssh/sshd_config が sshd_config.d を Include していない可能性 — 99-llens.conf が読まれない場合あり"
fi

if sshd -t 2>&1; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    echo "  sshd reloaded"
else
    echo "  [ERROR] sshd -t 失敗 — 設定不正、reload しません"
fi

#==============================================================================
# B. 不要設定の omit
#==============================================================================
section "[B1] OS 自動更新の停止"
systemctl disable --now unattended-upgrades 2>/dev/null || true
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
# is-enabled は disabled で非0 終了するが stdout には "disabled" を出す。
# $(... || echo X) すると stdout が "disabled\nX" になり行が崩れるので
# stdout を一旦捕まえて空のときだけ placeholder にする。
for unit in unattended-upgrades apt-daily.timer apt-daily-upgrade.timer; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null); [ -z "$state" ] && state=n/a
    printf "  %-25s %s\n" "$unit:" "$state"
done

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
section "[B5] 不要・自動更新サービスの停止"
# 存在すれば disable --now、無ければ静かにスキップ。
# disable / is-enabled は idempotent。
while read -r unit description; do
    [ -z "$unit" ] && continue
    if systemctl list-unit-files "$unit" 2>/dev/null | grep -q "$unit"; then
        systemctl disable --now "$unit" 2>/dev/null || true
        state=$(systemctl is-enabled "$unit" 2>/dev/null); [ -z "$state" ] && state=n/a
        printf "  %-32s %-12s  %s\n" "$unit" "$state" "$description"
    else
        printf "  %-32s %-12s  %s\n" "$unit" "not-found" "$description"
    fi
done <<'EOF'
clamav-freshclam.service        ClamAV 自動パターン更新 (手動運用に切替)
ua-timer.timer                  Ubuntu Pro / ESM 定期チェック
esm-cache.service               Ubuntu Pro / ESM キャッシュ
apt-news.service                APT ニュース
rpcbind.service                 RPC ポートマッパー
rpcbind.socket                  RPC ポートマッパー
slurmctld.service               Slurm (HGX vendor pre-install)
slurmd.service                  Slurm (HGX vendor pre-install)
cups.service                    CUPS プリンタサーバ
cups-browsed.service            CUPS ブラウザ
postfix.service                 Postfix MTA
nfs-server.service              NFS サーバ
nfs-kernel-server.service       NFS サーバ (旧名)
rpc-statd.service               NFS lock daemon
EOF

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

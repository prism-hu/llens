# LLENS デプロイ運用

このドキュメントは **ホスト OS の構成・搬入運用・セキュリティ** を扱う資料。
モデルや UI の使い方は [README.md](README.md) を参照。

---

## ライフサイクル

LLENS は「院外オンラインで構築 → 院内閉域で運用」を1サイクルとする。再構築時は SSD ワイプから始まる。

```
[院外 / オンライン]                     [院内 / 閉域]
  ┌─────────────────────────────┐         ┌──────────────┐
  │ 1. OS インストール          │         │              │
  │ 2. SSH 設定 (鍵投入)        │  搬入   │              │
  │ 3. repo clone               │  ───→   │  運用        │
  │ 4. NVIDIA / Docker / uv     │         │  (更新なし)  │
  │ 5. .env 作成                │         │              │
  │ 6. モデル DL                │         │              │
  │ 7. preflight apply          │         │              │
  │ 8. docker compose up        │         │              │
  │ 9. preflight audit          │         │              │
  │ 10. preflight scan          │         │              │
  └─────────────────────────────┘         └──────┬───────┘
                                                  │
                              (寿命 / リフレッシュ)│
                                                  ▼
                                          ┌──────────────┐
                                          │ SSD ワイプ   │
                                          │ 院外搬出     │
                                          └──────┬───────┘
                                                  │
                                          (再構築 = 上記 1 へ)
```

**含意**: リポジトリ + `.env` の組み合わせが「サーバを再構成可能な唯一の真実」。スクリプトを介さない手動変更は次サイクルで消える。

---

## ホスト構成

### サービス一覧と公開範囲

| サービス | ホストポート | bind | 公開範囲 | 認証 |
|---|---|---|---|---|
| Caddy (リバプロ → OWUI) | :80 | 0.0.0.0 | HINES 全体 | OWUI 側 |
| SSH (sshd) | :22 | 0.0.0.0 | HINES 全体 | 公開鍵 |
| SGLang (推論API) | :8000 | 0.0.0.0 | **Docker bridge + Tailnet のみ (UFW で制限)** | なし |
| Open WebUI | :8080 | 127.0.0.1 | localhost のみ (Caddy 経由) | OWUI 自前 |
| Docling | :5001 | 127.0.0.1 | localhost のみ (debug 用) | なし |
| Prometheus | :9090 | 127.0.0.1 | localhost のみ (debug 用) | なし |
| DCGM Exporter | :9400 | 127.0.0.1 | localhost のみ (debug 用) | なし |
| Grafana | :9000 | 0.0.0.0 | HINES 全体 | admin/(env) |

**設計原則**:
- 一般ユーザー向け = Caddy (:80) → OWUI のみ
- 管理者向け = SSH (:22) + Grafana (:9000、認証あり)
- 内部 API (SGLang, Docling, Prometheus, DCGM) は外から見えない or Tailnet のみ
- Tailscale は院外フェーズの管理アクセスに使う。閉域後は失効するが UFW ルールは互換 (該当 CGNAT へのトラフィックが消えるだけ)

### Caddy

`:80` で listen し、OWUI (`127.0.0.1:8080`) へリバプロ。Caddy 自体の設定はホスト側で別管理(リポ外)。閉域では `llens.med.hokudai.ac.jp` の DNS が引けないので、IP 直 (`http://<内部 IP>/`) で利用。

### Tailscale

院外フェーズの管理アクセスに利用 (CGNAT 帯 `100.64.0.0/10`)。

- ホスト: `100.68.171.99` (Tailscale 割当、Tailnet 内固定)
- 用途: 管理者が SGLang `:8000` 等に直接触る (デバッグ・eval ループ用)
- 院内閉域では coord/DERP に届かず失効。UFW ルールはそのままでも無害

### .env

`docker-compose.yml` は `${GRAFANA_ADMIN_PASSWORD:?...}` を要求。`.env` を `.env.example` から作成:

```bash
cp .env.example .env
# .env を編集して GRAFANA_ADMIN_PASSWORD を設定
```

`.env` は `.gitignore` 済。再構築時は新 `.env` を毎回作る (前サイクルの値を持ち越したければ別途オフライン保管)。

---

## 構築チェックリスト

院外オンラインで上から順に実行。**SSH ハードニングは preflight が担うので、最初の SSH 設定は手動で鍵を入れるだけでよい**。

```
[ ] 1. Ubuntu 24.04 LTS インストール
[ ] 2. SSH: 鍵を投入、パスワードログインで一度確認 (この後 preflight で鍵限定化)
[ ] 3. NVIDIA ドライバ + Docker + uv インストール、再起動
[ ] 4. Tailscale 加入 (院外フェーズの管理アクセス用、必須ではない)
[ ] 5. git clone <repo> ~/llens
[ ] 6. cp .env.example .env  →  GRAFANA_ADMIN_PASSWORD を設定
[ ] 7. uv sync
[ ] 8. hf auth login
[ ] 9. モデル DL (深夜バッチ、~数時間)
[ ] 10. make preflight-audit       ← 現状把握
[ ] 11. make preflight-apply       ← ホスト hardening
[ ] 12. make run-<model> &         ← SGLang 起動
[ ] 13. docker compose up -d
[ ] 14. ヘルスチェック (README 参照)
[ ] 15. make preflight-audit       ← 適用後確認
[ ] 16. 搬入直前の手動停止 (下記「搬入直前チェックリスト」)
[ ] 17. make preflight-scan        ← シャットダウン直前のフルスキャン
[ ] 18. shutdown → 院内搬入
```

---

## 搬入直前チェックリスト (手動)

preflight-apply で扱わない「構築固有」項目を搬入直前に手動で片付ける。

```
[ ] cloudflared 停止 (オンライン専用、閉域では不要)
    sudo systemctl disable --now cloudflared cloudflared-update.timer

[ ] Tailscale 停止 (オンライン専用、閉域では coord に届かず無効化)
    sudo tailscale down
    sudo systemctl disable --now tailscaled
```

### 時刻同期 (TODO)

院内 NTP サーバの情報が未確定。判明次第以下を設定:

```
[ ] 稼働中の時刻同期サービスを確認
    systemctl status systemd-timesyncd ntpsec chronyd 2>/dev/null

[ ] 院内 NTP に切替 (systemd-timesyncd を使う場合)
    sudo sed -i 's|^#\?NTP=.*|NTP=<院内 NTP サーバ>|' /etc/systemd/timesyncd.conf
    sudo systemctl enable --now systemd-timesyncd
    sudo systemctl disable --now ntpsec  # 他の同期サービスは止める
```

---

## preflight 運用

すべて `make preflight-*` から呼び出す。ログは `logs/` に自動出力 (gitignore、SUDO_USER 所有)。

| コマンド | 役割 | 副作用 |
|---|---|---|
| `make preflight-audit` | 現状確認 (SSH/timer/cron/ポート/構成項目の状態) | なし (read-only) |
| `make preflight-apply` | 構成適用 + 不要設定の omit (UFW/SSH/rpcbind/slurm 等) | あり、すべてべき等 |
| `make preflight-scan` | ClamAV 全体スキャン | パターン DB 更新のみ |

### preflight-apply が触る項目

**A. アプリ構成 (恒久設定として必要)**

| ID | 内容 |
|---|---|
| A1 | 時刻同期 (確認のみ、変更は手動) |
| A2 | kernel / nvidia パッケージの apt-mark hold |
| A3 | nvidia-persistenced 有効化 |
| A4 | UFW 設定 (default deny incoming + 必要ポート許可) |
| A5 | SSH ハードニング (`/etc/ssh/sshd_config.d/99-llens.conf`) |

**B. 不要設定の omit (通信抑止 / 攻撃面削減)**

| ID | 内容 |
|---|---|
| B1 | OS 自動更新 (unattended-upgrades, apt-daily) |
| B2 | Snap 自動更新の hold |
| B3 | テレメトリ系の削除 (popularity-contest, apport, whoopsie) |
| B4 | motd-news |
| B5 | 不要・自動更新サービスの停止 (まとめ disable、存在しなければ skip)<br>clamav-freshclam, ua-timer, esm-cache, apt-news, rpcbind, slurm{ctld,d}, cups, cups-browsed, postfix, nfs-server, nfs-kernel-server, rpc-statd |

### UFW ルール (A4 で設定)

```
default deny incoming
default allow outgoing
allow 22/tcp                                  # SSH (HINES 全体)
allow 80/tcp                                  # Caddy → OWUI (HINES 全体)
allow 9000/tcp                                # Grafana (HINES 全体)
allow from 172.16.0.0/12 to any port 8000     # Docker bridge → SGLang
allow from 100.64.0.0/10 to any port 8000     # Tailnet → SGLang
```

---

## 緊急対応

### 北大からの脆弱性検査で CRITICAL 通知が来たとき

1. メール本文の指摘内容を確認
2. 該当サービスを停止 (`docker compose stop <service>` 等)
3. 修正 (パスワード変更 / 設定見直し / ポート閉鎖)
4. `make preflight-audit` で差分確認
5. 学術情報部 (vulnerability@oicte.hokudai.ac.jp) に対応報告 + 再検査依頼

### Grafana admin/admin 疑い

```bash
curl -s -o /dev/null -w "%{http_code}\n" -u admin:admin http://localhost:9000/api/admin/users
# 401 = 安全 (パスワード変更済み)
# 200 = 即対応 (UI から変更 or .env 更新 + docker compose up -d --force-recreate grafana)
```

### SGLang が tailnet 外から触れる疑い

```bash
sudo ufw status verbose | grep 8000
# 上記 UFW ルールが無ければ make preflight-apply を再実行
```

### 認証情報漏洩疑い

- `.env` の `GRAFANA_ADMIN_PASSWORD` を変更
- `docker compose down grafana && docker volume rm llens_grafana_data && docker compose up -d grafana`
  - **ダッシュボード設定は monitoring/grafana/provisioning/ から自動復元される**
  - ユーザー設定 (個人ダッシュボード等) は失われる
- SSH 公開鍵を棚卸し: `make preflight-audit` の A0 セクションで `authorized_keys` を確認

---

## 関連ドキュメント

- [README.md](README.md) — モデル/UI の使い方、ヘルスチェック、ユーザー退避
- [docs/migration.md](docs/migration.md) — 専用ユーザー `llens` への将来移行案 (現在は enda 運用)
- [docs/evals.md](docs/evals.md) — eval phase の進捗メモ

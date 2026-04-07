# LLENS - Large Language Enhanced Nexus System

北大病院 H200x8 LLM 推論基盤。

デプロイまではオンライン。デプロイ後は病院内閉域。取り出すには SSD 初期化が必要。

## システム構成

| 項目 | 内容 |
|---|---|
| サーバー | HGX H200 x8 (141GB HBM3e/基、計 1,128GB) |
| OS | Ubuntu 24.04 LTS |
| 推論エンジン | vLLM or SGLang (uv 直接実行) — `:8000` |
| Web UI | Open WebUI (Docker) — `:8080` |
| 監視 | Prometheus (`:9090`) + Grafana (`:9000`) + DCGM Exporter (`:9400`) |

## セットアップ

### 手順

```bash
# uv インストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# クローン
git clone https://github.com/prism-hu/llens.git
cd llens

# 依存インストール
uv sync

# HuggingFace ログイン
uv run hf auth login
```

モデルのダウンロード・起動は「モデル」セクション参照。

### 起動手順

```bash
# 1. SGLang 起動（モデルのダウンロード済みであること）
./scripts/sglang-deepseek-v3.2.sh

# 2. Open WebUI + 監視スタック起動（別ターミナル）
docker compose up -d
```

これで以下が全て立ち上がる:

| サービス | URL | 用途 |
|---|---|---|
| SGLang | `http://localhost:8000` | 推論 API |
| Open WebUI | `http://localhost:8080` | チャット UI |
| Grafana | `http://localhost:9000` | 監視ダッシュボード |
| Prometheus | `http://localhost:9090` | メトリクス収集 |

### ヘルスチェック

```bash
# SGLang が応答するか
curl http://localhost:8000/v1/models

# OpenWebUI が起動しているか
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080

# 全コンテナの状態
docker compose ps
```

## モデル

試行・変更の可能性あり。

### DeepSeek V3.2 (現在のメイン)

| 項目 | 値 |
|---|---|
| パラメータ | 685B (MoE、アクティブ 37B/トークン) |
| 量子化 | FP8 (ネイティブ配布) |
| モデルサイズ | ~690GB |
| ロード後 VRAM | ~710-720GB (weights + オーバーヘッド) |
| KV キャッシュ残量 | ~408GB (util=1.0) / ~247GB (util=0.93) |
| KV キャッシュ/トークン | ~39KB (FP8 MLA) |
| 最大コンテキスト | 163,840 トークン |
| HF リポジトリ | `deepseek-ai/DeepSeek-V3.2` |
| ライセンス | MIT |

```bash
# ダウンロード
uv run hf download deepseek-ai/DeepSeek-V3.2 --local-dir ./models/DeepSeek-V3.2

# 起動 (vLLM)
./scripts/vllm-deepseek-v3.2.sh

# 起動 (SGLang)
./scripts/sglang-deepseek-v3.2.sh
```

> BF16 は ~1,340GB で 8xH200 に載らない。FP8 必須。

### Qwen3.5 (予備)

| 項目 | 値 |
|---|---|
| パラメータ | 397B (MoE、アクティブ 17B/トークン) |
| 量子化 | FP8 |
| モデルサイズ | ~403GB |
| 最大コンテキスト | 262,144 トークン |
| HF リポジトリ | `Qwen/Qwen3.5-397B-A17B-FP8` |
| ライセンス | Apache 2.0 |

```bash
# ダウンロード
uv run hf download Qwen/Qwen3.5-397B-A17B-FP8 --local-dir ./models/Qwen3.5-397B-A17B-FP8

# 起動 (SGLang)
./scripts/sglang-qwen3.5.sh
```

> DeepSeek V3.2 より更に軽量。speculative decoding (NEXTN) 対応。

### GLM-5

| 項目 | 値 |
|---|---|
| パラメータ | 744B (MoE、アクティブ 40B/トークン) |
| 量子化 | FP8 |
| モデルサイズ | ~756GB |
| ロード後 VRAM | ~860GB (weights + オーバーヘッド) |
| KV キャッシュ残量 | ~268GB (util=1.0) / ~99GB (util=0.93) |
| KV キャッシュ/トークン | ~88KB (BF16) / ~44KB (FP8) |
| 最大コンテキスト | 202,752 トークン |
| HF リポジトリ | `zai-org/GLM-5-FP8` |

```bash
# ダウンロード
uv run hf download zai-org/GLM-5-FP8 --local-dir ./models/GLM-5-FP8

# 起動 (vLLM)
./scripts/vllm-glm5.sh

# 起動 (SGLang)
./scripts/sglang-glm5.sh
```

> vLLM では 2-3 tok/s 程度しか出ない。SGLang の最適化版は Docker のみ提供で、uv 直接実行の方針と合わない。現状は採用見送り。

## 監視

SGLang 側は `--enable-metrics` 付きで起動する。

### アクセス先

| サービス | URL | 備考 |
|---|---|---|
| Grafana | `http://localhost:9000` | admin / admin |
| Prometheus | `http://localhost:9090` | 通常は直接触らない |

### Grafana の使い方

1. `http://localhost:9000` にアクセス、admin / admin でログイン
2. 左メニュー **Dashboards** → **SGLang H200 Dashboard** を開く
   - 上段: LLM パフォーマンス（TTFT、スループット、キュー長、キャッシュヒット率など）
   - 下段: GPU ハードウェア（温度、使用率、VRAM、電力、クロック、NVLink）
3. 右上の時間範囲で表示期間を変更（デフォルト: Last 1 hour）
4. 自動更新は 5 秒間隔

### 見るべき指標と判断基準

| 指標 | パネル名 | 良好 | 要注意 |
|---|---|---|---|
| 初回トークン応答時間 | TTFT | P95 < 1秒 | P95 > 3秒 |
| 生成速度 | 生成スループット | > 30 tok/s | < 15 tok/s |
| 待ち行列 | 同時実行 / 待ちキュー | Queued = 0〜数件 | 増加し続ける |
| GPU 温度 | GPU 温度 | < 75℃ | > 83℃（スロットリング） |
| VRAM | VRAM 使用量 | 余裕あり | 90% 超え |

### データソース構成

```
SGLang (:8000/metrics) ──→ Prometheus (:9090) ──→ Grafana (:9000)
DCGM Exporter (:9400)  ──→ Prometheus (:9090) ──↗
```

- Prometheus が 5 秒間隔で SGLang と DCGM Exporter からメトリクスを収集
- Grafana は Prometheus をデータソースとしてグラフを描画
- データソース・ダッシュボードは `monitoring/` 配下の設定ファイルで自動プロビジョニングされる（Grafana UI での手動設定は不要）

### トラブルシュート

```bash
# 各メトリクスエンドポイントの疎通確認
curl -s http://localhost:8000/metrics | head   # SGLang
curl -s http://localhost:9400/metrics | head   # DCGM

# Prometheus のターゲット状態確認
# http://localhost:9090/targets にアクセスし、全ターゲットが UP であることを確認

# コンテナ状態
docker compose ps
docker compose logs grafana
docker compose logs prometheus
```

> SGLang v0.5.4 以降はメトリクスプレフィックスが `sglang:` → `sglang_` に変更されている。ダッシュボードは `sglang_` 前提で作成済み。バージョンが古い場合はダッシュボード JSON 内の `sglang_` を `sglang:` に置換する。

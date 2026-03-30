# LLENS - Large Language Enhanced Nexus System

北大病院 H200x8 LLM 推論基盤。

デプロイまではオンライン。デプロイ後は病院内閉域。取り出すには SSD 初期化が必要。

## システム構成

| 項目 | 内容 |
|---|---|
| サーバー | HGX H200 x8 (141GB HBM3e/基、計 1,128GB) |
| OS | Ubuntu 24.04 LTS |
| 推論エンジン | vLLM (uv 直接実行) — `:8000` |
| Web UI | Open WebUI (Docker) — `:3000` |

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

### Open WebUI 起動

```bash
docker compose up -d
```

ブラウザで `http://localhost:3000` にアクセス。
初回アクセスで管理者アカウントを作成。

Open WebUI から vLLM に接続:
管理者パネル → 設定 → 接続 → OpenAI API に以下を設定:
- URL: `http://host.docker.internal:8000/v1`
- API Key: `EMPTY`

### ヘルスチェック

```bash
# vLLM モデル一覧
curl http://localhost:8000/v1/models

# vLLM で直接チャット
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5","messages":[{"role":"user","content":"こんにちは"}]}'

# Open WebUI
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000
```

## モデル

試行・変更の可能性あり。

### GLM-5 (現在のメイン)

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

# 起動
./scripts/vllm-glm5.sh
```

### DeepSeek V3.2 (候補)

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

> DeepSeek V3.2 は GLM-5 より ~150GB 軽く、KV キャッシュに余裕がある。
> BF16 は ~1,340GB で 8xH200 に載らない。FP8 必須。

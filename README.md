# LLENS - Large Language Enhanced Nexus System

LLENSは、北海道大学医学部PRISM-HUで開発・管理されている医療情報アシスタントAIシステムです。

600B超のフロンティアレベルのLocal LLMを北海道大学病院内オンプレミス環境で動作させることにより、病院内閉域ネットワークにAIによる高度な業務効率化基盤を提供するのが目標です。

> 構築・搬入運用・セキュリティの詳細は [DEPLOYMENT.md](DEPLOYMENT.md) を参照。

## システム構成

| 項目 | 内容 |
|---|---|
| サーバー | HGX H200 x8 (141GB HBM3e/基、計 1,128GB) |
| OS | Ubuntu 24.04 LTS |
| 推論エンジン | SGLang (uv 直接実行) — `:8000` |
| Web UI | Open WebUI (Docker) — `:8080` |
| 文書抽出 | Docling (Docker, CPU) — `:5001` |
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
make run-ds3

# 2. Open WebUI + 監視スタック起動（別ターミナル）
docker compose up -d
```

> `make help` で起動・運用ターゲット一覧を表示。

これで以下が全て立ち上がる:

| サービス | URL | 用途 |
|---|---|---|
| SGLang | `http://localhost:8000` | 推論 API |
| Open WebUI | `http://localhost:8080` | チャット UI |
| Docling | `http://localhost:5001` | 添付ファイル → Markdown 抽出 (Open WebUI から自動利用) |
| Grafana | `http://localhost:9000` | 監視ダッシュボード |
| Prometheus | `http://localhost:9090` | メトリクス収集 |

### ヘルスチェック

```bash
# SGLang が応答するか
curl http://localhost:8000/v1/models

# OpenWebUI が起動しているか
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080

# Docling が起動しているか
curl -s http://localhost:5001/health

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

# 起動 (SGLang)
make run-ds3
```

> BF16 は ~1,340GB で 8xH200 に載らない。FP8 必須。


### Kimi K2.6 (検証中)

| 項目 | 値 |
|---|---|
| パラメータ | 1.1T (MoE、アクティブ 32B/トークン) |
| エキスパート | 384個 (ルーティング 8 + 共有 1) |
| 量子化 | INT4 (QAT ネイティブ、compressed-tensors) |
| モデルサイズ | ~594GB |
| ロード後 VRAM | ~640-660GB (weights + オーバーヘッド) |
| KV キャッシュ残量 | ~470GB (util=1.0) / ~370GB (util=0.93) |
| KV キャッシュ/トークン | ~60-80KB (FP8 MLA、実測要確認) |
| 最大コンテキスト | 262,144 トークン |
| 推奨コンテキスト | 131,072 トークン (メモリ余裕確保) |
| アテンション | MLA (Multi-head Latent Attention) |
| マルチモーダル | 画像・動画入力対応 (MoonViT 400M encoder) |
| HF リポジトリ | `moonshotai/Kimi-K2.6` |
| ライセンス | Modified MIT |

```bash
# ダウンロード (~594GB、数時間かかるため深夜バッチ推奨)
uv run hf download moonshotai/Kimi-K2.6 --local-dir ./models/Kimi-K2.6

# 起動 (SGLang)
make run-kimi
```

> INT4 QAT ネイティブ量子化のため BF16 比の品質劣化はほぼ無し。H200x8 で動作する 1T クラスの現実解。SGLang v0.5.10 以降が必要。
>
> `--dp 8 --enable-dp-attention` と `--speculative-*` は K2.6 での検証が不十分なため初回は付けない。最小構成で安定稼働を確認してから段階的に追加検討。
>
> DeepSeek V3.2 との並列運用は VRAM 的に不可 (切替運用)。

#### Thinking / Instant モード運用

K2.6 はデフォルトで Thinking モードが ON。SGLang 側は 1 インスタンスで両対応なので、Open WebUI の `Settings > Connections > OpenAI API` で同じエンドポイント (`http://localhost:8000/v1`) を 2 つ登録して使い分ける。

**kimi-k2.6-instant (普段使い)**

```json
{
  "temperature": 0.6,
  "top_p": 0.95,
  "extra_body": {"chat_template_kwargs": {"thinking": false}}
}
```

**kimi-k2.6-thinking (複雑タスク用)**

```json
{
  "temperature": 1.0,
  "top_p": 0.95
}
```

動作確認:

```bash
# Thinking モード
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [{"role": "user", "content": "2+2は?"}],
    "temperature": 1.0,
    "top_p": 0.95
  }'

# Instant モード
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [{"role": "user", "content": "2+2は?"}],
    "temperature": 0.6,
    "top_p": 0.95,
    "chat_template_kwargs": {"thinking": false}
  }'
```

### GLM-5.1 (検証中)

| 項目 | 値 |
|---|---|
| パラメータ | 744B (MoE、アクティブ 40B/トークン) |
| 量子化 | FP8 (ネイティブ配布) |
| モデルサイズ | ~756GB |
| ロード後 VRAM | ~860GB (weights + オーバーヘッド) |
| KV キャッシュ残量 | ~268GB (util=1.0) / ~99GB (util=0.85) |
| KV キャッシュ/トークン | ~88KB (BF16) / ~44KB (FP8) |
| 最大コンテキスト | 202,752 トークン |
| アテンション | DSA (DeepSeek Sparse Attention) |
| HF リポジトリ | `zai-org/GLM-5.1-FP8` |
| ライセンス | MIT |

```bash
# ダウンロード (~756GB、深夜バッチ推奨)
uv run hf download zai-org/GLM-5.1-FP8 --local-dir ./models/GLM-5.1-FP8

# 起動 (SGLang)
make run-glm
```

> SGLang v0.5.10 以降で標準サポート、Docker 不要。EAGLE/MTP speculative decoding 有効化済み。
>
> Thinking モードはデフォルト ON。GLM-5 系は thinking 前提で訓練されており、簡単な質問では自動的に思考を最小化、ツール使用時は interleaved thinking でツール結果を解釈しながら推論を継続する設計のため、K2.6 のような Instant/Thinking 2エンドポイント運用は不要。
>
> FP8 チェックポイントには pre-calibrated な KV キャッシュ scaling factor が含まれていないため、KV キャッシュは FP16 のまま運用 (reasoning-heavy タスクでの精度劣化を回避)。
>
> DeepSeek V3.2 / Kimi K2.6 とは VRAM 的に並列運用不可 (切替運用)。

#### Thinking モード切替

GLM-5.1 は thinking ON のまま運用するのが基本だが、特に軽量な処理用に thinking OFF も用意可能。Open WebUI の `Settings > Connections > OpenAI API` で同じエンドポイントを 2 つ登録して使い分け。

**glm-5.1 (デフォルト、thinking ON)**
```json
{
  "temperature": 1.0,
  "top_p": 0.95
}
```

**glm-5.1-instruct (thinking OFF、軽量処理用)**
```json
{
  "temperature": 1.0,
  "top_p": 0.95,
  "extra_body": {"chat_template_kwargs": {"enable_thinking": false}}
}
```

> K2.6 のキー名 `thinking` と異なり、GLM-5 系は `enable_thinking` を使う点に注意。

動作確認:
```bash
# Thinking モード (デフォルト)
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5.1",
    "messages": [{"role": "user", "content": "2+2は?"}],
    "temperature": 1.0,
    "top_p": 0.95
  }'

# Instruct モード (thinking OFF)
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5.1",
    "messages": [{"role": "user", "content": "2+2は?"}],
    "temperature": 1.0,
    "top_p": 0.95,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

### DeepSeek V4 Pro (要検証)

| 項目 | 値 |
|---|---|
| パラメータ | 1.6T (MoE、アクティブ 49B/トークン) |
| 量子化 | FP4 + FP8 Mixed (エキスパート FP4、その他 FP8) |
| モデルサイズ | ~862GB |
| ロード後 VRAM | ~900GB (推定、weights + オーバーヘッド) |
| KV キャッシュ残量 | ~200-260GB (util=0.9、推定) |
| 最大コンテキスト | 1,000,000 トークン (Think Max は 384K 以上推奨) |
| アテンション | Hybrid (CSA + HCA) |
| HF リポジトリ | `deepseek-ai/DeepSeek-V4-Pro` |
| ライセンス | MIT |

```bash
# ダウンロード (~862GB、深夜バッチ推奨)
uv run hf download deepseek-ai/DeepSeek-V4-Pro --local-dir ./models/DeepSeek-V4-Pro

# 起動 (SGLang)
make run-ds4
```

> 1.6T 規模のフロンティアクラスを H200x8 に押し込めるのは FP4+FP8 Mixed のおかげ。ただし GLM-5 と同様に KV キャッシュは厳しい (初期設定は context-length=128K で運用)。
>
> V4 は新アーキ (CSA+HCA、mHC) かつ `encoding_dsv4` による新チャットテンプレートを採用。`--reasoning-parser` / `--tool-call-parser` は V3 系と非互換の可能性が高く、SGLang 側の対応バージョンに追従して追加する。


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
make run-qwen
```

> DeepSeek V3.2 より更に軽量。speculative decoding (NEXTN) 対応。

### ベンチマーク比較用(国産モデル)

`evals/` で国内日本語FT組と対比するためのモデル。本番運用候補ではない。

| モデル | HF |
|---|---|
| llm-jp-3 8x13B Instruct3 | [llm-jp/llm-jp-3-8x13b-instruct3](https://huggingface.co/llm-jp/llm-jp-3-8x13b-instruct3) |
| SIP-jmed-llm 3 8x13B (医療特化) | [SIP-med-LLM/SIP-jmed-llm-3-8x13b-OP-32k-R0.1](https://huggingface.co/SIP-med-LLM/SIP-jmed-llm-3-8x13b-OP-32k-R0.1) |

```bash
uv run hf download llm-jp/llm-jp-3-8x13b-instruct3 --local-dir ./models/llm-jp-3-8x13b-instruct3
uv run hf download SIP-med-LLM/SIP-jmed-llm-3-8x13b-OP-32k-R0.1 --local-dir ./models/SIP-jmed-llm-3-8x13b-OP-32k-R0.1
```

起動 (共通スクリプト、デフォルト TP=1 / GPU 0 / port 8000):

```bash
bash scripts/llm/sglang-llm-jp-3-bench.sh instruct3   # llm-jp-3-8x13b-instruct3
bash scripts/llm/sglang-llm-jp-3-bench.sh sip-jmed    # SIP-jmed-llm-3-8x13b
```

> 8x13B MoE は ~47B / FP16 ~94GB なので **1 GPU(141GB) に収まる**。NCCL 通信コスト無しでデコード最速、シングルユーザー eval に最適。
> TP は `CUDA_VISIBLE_DEVICES` の GPU 数から自動判定。
>
> 推奨サンプリング (モデルカード): `temperature 0.5`, `top_p 0.8`, `repeat_penalty 1.05`。
> ただし `evals/` での精度比較は再現性のため `temperature 0` 固定。
> プロンプト形式は `### 指示: ... ### 応答:` (Alpaca風)、stop は `<EOD|LLM-jp>` (tokenizer 設定で自動認識)。

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

### メトリクスプレフィックスについて

現環境のメトリクス名プレフィックスは `sglang:` (コロン)。Grafana ダッシュボードもこの前提で作成済み。

```bash
curl -s http://localhost:8000/metrics | head
# "sglang:..." で始まっていれば現行どおり
```

将来 SGLang のアップデートで `sglang_` (アンダースコア) に変わる可能性があるため、アップデート後は上記で必ず確認。変わっていれば以下で一括置換:

```bash
sed -i 's/sglang:/sglang_/g' monitoring/grafana/dashboards/sglang-h200-dashboard.json
sudo docker compose restart grafana
```

## ユーザー退避・復元

Open WebUI のユーザー情報 (email + パスワードハッシュ + プロフィール) だけを外部メディアに退避・復元する仕組み。SSD ワイプを挟む運用サイクルを想定。

**退避対象外**: チャット履歴、アップロードファイル、ナレッジベース、管理画面の設定。これらは再構築ごとに捨てる前提。

### 想定サイクル

1. インターネット環境で `docker compose up -d` → 初期ユーザー作成
2. イントラへ物理搬入
3. **退避**: `bash scripts/owui/backup.sh` → `./backups/` に dump 生成、外部メディアへコピー
4. SSD ワイプ
5. インターネット経由で再構築 (`docker compose up -d`) — 同じ `:v0.9.5` が pull され schema 互換
6. **復元**: `bash scripts/owui/restore.sh ./backups/owui-users-<timestamp>.sql`

復元後は JWT 鍵が変わっているため、全ユーザーは次回パスワードで再ログインが必要 (パスワード自体は bcrypt ハッシュで保持されているので通る)。

### 退避

```bash
bash scripts/owui/backup.sh
```

- `user` / `auth` 2 テーブルの中身を INSERT 文として `./backups/owui-users-<timestamp>.sql` に出力
- 同名 `.sha256` も生成 (持ち出し時の整合性確認用)
- 処理中はコンテナを一時停止 (実測数秒)
- `./backups/` は `.gitignore` 済み

### 復元

```bash
bash scripts/owui/restore.sh ./backups/owui-users-<timestamp>.sql
```

- **email で衝突判定**: 復元先に同じ email があればその行はスキップ
- `user` と `auth` はセットで挿入 (片方だけ入ることは無い)
- 既存ユーザーは上書きしない → 搬入先で手動追加したユーザーも保護される
- 同じ dump を何度流しても安全 (2 回目以降は全件 skip)

### 制約

- 退避時と復元時の Open WebUI バージョンは一致必須 (`user` / `auth` テーブルのカラム構成が変わると load 時に失敗)。`docker-compose.yml` の `:v0.9.5` ピン留めでこれを担保
- `WEBUI_SECRET_KEY` は固定していない → 復元後に全員再ログイン必要 (alpha フェーズでは許容)
- **ユーザー更新の反映は不可**: 外部環境で名前やロールを変更してもスクリプトは「無ければ足す、あれば触らない」挙動のため搬入先には反映されない。反映したい場合は該当ユーザーを一度削除してから復元する
- 環境変数 `OWUI_CONTAINER` でコンテナ名を上書き可能 (旧自動生成名 `llens-open-webui-1` 期に dump したい場合など)

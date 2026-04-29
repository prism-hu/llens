# evals

院内デプロイ候補モデルの日本語性能評価。背景・方針・フェーズは `docs/evals.md` 参照。

## セットアップ

```bash
uv sync --group evals
```

## データセット取得

```bash
./evals/scripts/fetch_datasets.sh
```

`evals/datasets/` 配下に以下を clone (gitignored、外部リポジトリのライセンスはそれぞれ参照):

| ベンチ | リポジトリ | ライセンス | 備考 |
|---|---|---|---|
| IgakuQA (2018-2022) | [jungokasai/IgakuQA](https://github.com/jungokasai/IgakuQA) | 明記なし(問題は厚労省公式) | データそのまま |
| IgakuQA119 (第119回) | [naoto-iwase/IgakuQA119](https://github.com/naoto-iwase/IgakuQA119) | code Apache-2.0 / data CC BY 4.0 | OCR済 |
| JMED-LLM | [sociocom/JMED-LLM](https://github.com/sociocom/JMED-LLM) | サブセットごと(CC-BY系混在、一部 NC) | 7タスク全部入り |
| llm-jp-eval | [llm-jp/llm-jp-eval](https://github.com/llm-jp/llm-jp-eval) | Apache-2.0 (各データセットは DATASET.md 参照) | 別途 preprocess 必要 |

llm-jp-eval は前処理スクリプトの実行が別途必要。`-d` は1タスクずつ:

```bash
cd evals/datasets/llm_jp_eval
uv sync
for task in jcommonsenseqa jemhopqa jsquad mgsm; do
  uv run python scripts/preprocess_dataset.py -d "$task" -o ./dataset
done
```

**HF認証**: 上記4タスクは認証不要(JCommonsenseQA/JEMHopQA/JSQuAD は GitHub raw、MGSM-ja は HF だが open)。

将来 HLE系タスク (`cais/hle`, `llm-jp/jhle`) を追加する場合のみフォーム承認 + ログインが必要:

```bash
uv run hf auth login    # 旧 huggingface-cli login と互換
```

## ハーネス: 動作確認

SGLang サーバー (`scripts/sglang-glm5.1.sh` 等) を起動した状態で:

```bash
uv run --group evals python -m evals.harness.client \
  --base-url http://localhost:8000 \
  --model glm-5.1 \
  --prompt "日本の首都はどこですか。一文で答えて。"
```

`--no-think` で thinking OFF。出力に TTFT / TTAT / reasoning_tokens / answer_tokens が並ぶ。

## ディレクトリ

```
evals/
├── harness/client.py            # streaming + reasoning分離クライアント
├── tasks/
│   ├── llm_jp_eval_subset/      # jcommonsenseqa, jemhopqa, jsquad, mgsm
│   ├── igakuqa/                 # IgakuQA 2018-2022
│   ├── igakuqa119/              # IgakuQA 第119回
│   └── jmed_llm/                # jmmlu_med, crade, rrtnm, smdis, jcsts
├── scripts/
│   ├── fetch_datasets.sh        # 外部データ clone
│   ├── run_phase.sh             # 1モデル × 1モードで全タスク連続実行
│   └── summarize.py             # results を Markdown テーブルに集約
├── datasets/                    # gitignored (clone先)
└── results/<subdir>/<task>.json # gitignored (実行結果)
```

## タスクランナー

各タスクは `evals.tasks.<name>.run` で叩く。共通フラグ:

```
--base-url    SGLang endpoint (default http://localhost:8000)
--model       served-model-name
--task        タスク名 or "all" (タスク族による)
--output-dir  結果JSON保存先
--limit N     先頭N問のみ (スモーク用、SMDIS/CRADE/JCSTS 等の大型データに有用)
--no-think    chat_template_kwargs.enable_thinking=False
--max-tokens  default 32768
--temperature default 0.0
```

タスク族ごとの個別フラグ:

| 族 | 個別フラグ |
|---|---|
| `tasks.llm_jp_eval_subset` | `--task {jcommonsenseqa,jemhopqa,jsquad,mgsm,all}` |
| `tasks.igakuqa` | `--years 2018 2019 ...` `--include-image` |
| `tasks.igakuqa119` | `--blocks 119A 119B ...` `--no-vision`(auto-probeをスキップして強制text-only) |
| `tasks.jmed_llm` | `--task {jmmlu_med,crade,rrtnm,smdis,jcsts,all}` (`all` は smdis 除外、smdis は明示時のみ) |

出力: `<output-dir>/<task>.json` — metrics、timing分布(median/p90/max)、token分布、全サンプル raw/extracted/正誤。

## フェーズ実行

`scripts/run_phase.sh <model> <output_subdir> [extra args...]` で全11タスクを連続実行:

```bash
# Phase 1: GLM 5.1 thinking ON (No-Img のみ)
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-on

# 公開リーダーボードの "Overall" 列も埋めたい場合 (画像問題込み)
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-on --include-image

# Phase 3: GLM 5.1 thinking OFF
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-off --no-think

# スモーク: 各タスク N=5 のみ
./evals/scripts/run_phase.sh glm-5.1 _smoke --limit 5
```

引数の振り分け:
- `--no-vision` は `igakuqa119` だけに転送(他タスクは vision 概念が無い、または画像ファイル非同梱)
- それ以外 (`--limit`, `--no-think`, `--max-tokens`, `--temperature`) は全タスクに転送

**画像問題の扱い (auto-probe)**:
- `igakuqa119` は起動時に red square 画像で multimodal capability を probe(応答に "red"/"赤" 含むかを判定)
- vision OK: 画像問題を multimodal API で評価 (Overall 列が埋まる)
- vision NG: 画像問題を自動スキップ (No-Img 列のみ)
- `igakuqa` (2018-2022) は画像ファイル非同梱のため画像問題は常時スキップ

注意: JCSTS は 3.6K行、CRADE は 1.6K行。フルランは数時間〜半日。
SMDIS は 15K行で別格(~55時間、SNSスタイルで院内利用と乖離)のため `--task all` から除外済。
明示的に `--task smdis` で叩けば実行可能。
本番ランの前に必ず `--limit N` で wiring を確認。

## 公開リーダーボードと並びの指標

各タスクは公式リーダーボードと同じ形式で集計されます(結果JSONの `leaderboard` キーに格納):

| ベンチ | 形式 | 例 |
|---|---|---|
| IgakuQA / IgakuQA119 | `Overall Score`/`Overall Acc.`/`No-Img Score`/`No-Img Acc.` | `461/500 (92.20%)` |
| JMED-LLM | `kappa(accuracy)`、CRADE/JCSTS は **線形重み付き κ** | `0.54(0.53)` |
| llm-jp-eval | 各タスクの公式メトリクス(exact_match / char_f1 / mathematical_equivalence) | `0.823` |

IgakuQA119 のスコアリング規則(`tasks/igakuqa119/run.py`):
- 必修問題 (B/E ブロック): Q1-25 = 1点、Q26-50 = **3点**
- 一般問題 (A/C/D/F): 1点
- 計500点満点 / 400問

IgakuQA (2018-2022) は各問題に `points` フィールドが含まれており、それをそのまま使用。

## 結果の確認

```bash
uv run --group evals python evals/scripts/summarize.py evals/results/glm-5.1-think-on
```

出力セクション:
- **score table**: タスクごとの精度、TTAT、think tokens
- **leaderboard rows**: 各公式リポジトリ README にそのまま貼れる Markdown 行(IgakuQA / IgakuQA119 / JMED-LLM)
- **timeline**: タスクごとの `started_at` / `ended_at` (ISO8601 + epoch_ms) — Grafana 時間レンジ指定に流用可能

`--compare <other-dir>` で別ランとの差分(score Δ、TTAT Δ、think_tokens 比較)も出る。

## Grafana との突き合わせ

各タスクJSONに以下が記録される:

```json
"started_at": "2026-04-28T14:44:07+09:00",
"ended_at": "2026-04-28T14:44:13+09:00",
"started_epoch_ms": 1777355047398,
"ended_epoch_ms": 1777355053624,
"duration_sec": 6.23,
```

`*_epoch_ms` をそのまま Grafana の Time Range (`from=...&to=...`) に貼ればその時間帯のメトリクスが出る。SGLang の `:8000/metrics` (Prometheus) や DCGM exporter の GPU 利用率/温度を後追い確認できる。

## 進捗

- [x] `harness/client.py` (streaming + reasoning分離)
- [x] `scripts/fetch_datasets.sh` (外部データクローン)
- [x] `tasks/llm_jp_eval_subset/run.py` (jcommonsenseqa, jemhopqa, jsquad, mgsm)
- [x] `tasks/igakuqa/run.py` (2018-2022、5年分)
- [x] `tasks/igakuqa119/run.py` (第119回、A-F)
- [x] `tasks/jmed_llm/run.py` (5 MCQタスク: jmmlu_med, crade, rrtnm, smdis, jcsts)
- [x] `scripts/run_phase.sh` (全タスク連続実行)
- [x] `scripts/summarize.py` (Markdown集約)
- [ ] `harness/speed.py` (並列ロード時の TTFT/throughput 測定 — Phase 1 では per-request timing で代替)
- [ ] JMED-LLM の重み付き Cohen's κ 計算 (CRADE/JCSTS、現状はaccuracyのみ; raw pred/goldは保存済み)
- [ ] JMED-LLM NER系 (CRNER/RRNER/NRNER)
- [ ] `harness/accuracy.py` (3 ランナー共通部の抽出 — 任意)

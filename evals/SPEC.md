# 評価仕様

`evals/` ハーネスのベンチ詳細・採点ルール・ランナー仕様。
最新の結果は [`README.md`](./README.md)。

## 評価方針: as-released best

完全公平より **実運用想定** を優先する。

- 各モデル公式推奨設定 + 公開済み高速化(EAGLE 等)を入れた状態で比較
- 起動 config は `scripts/sglang-*.sh` で git 管理して透明化
- 設定差は明示する(例: Kimi K2.6 は公式 EAGLE3 ドラフト未公開のため spec decoding なし)
- temperature=0、max_tokens=32768、N=1。MoE は微揺れあるが 5%以上の差なら結論可
- chat template / prompt format は各モデル公式に従う

## ベンチ一覧

| ベンチ | テスト内容 | 形式 | サイズ |
|---|---|---|---|
| **llm-jp-eval** (短縮) | 日本語汎用(常識・QA・数学) | exact_match / char_f1 / 数値一致 | 4タスク (~6K問) |
| **IgakuQA** (2018-2022) | 医師国家試験 5年分 | 配点(問題内蔵 `points`) + accuracy | 2000問 / 2485点 |
| **IgakuQA119** (第119回) | 第119回医師国家試験 (2025/2 実施) | 500点満点(必修3点)/ Overall / No-Img | 400問 / 500点 |
| **JMLE2026** (第120回) | 最新医師国家試験 (2026/2 実施)。学習データ完全未含有 | 500点満点(必修3点)/ Overall / Text-only | 400問 / 500点 |
| **JMED-LLM** (MCQ 3) | 医療QA・症例ADE判定・読影TNM分類 | `kappa(accuracy)`、CRADE は線形重み付き | 3タスク (~3K行) |

優先度: **JMLE2026**(直近・完全リーク無) > **IgakuQA119**(リーク低) > **JMED-LLM**(実務タスク網羅) > llm-jp-eval(日本語汎用底力) > IgakuQA(年次トレンド確認)。

## ベンチ詳細

### llm-jp-eval(短縮版)

[`llm-jp/llm-jp-eval`](https://github.com/llm-jp/llm-jp-eval)の前処理スクリプトで生成された 4タスクのみ。各タスクの metric は dataset JSON に記載 (`exact_match`, `char_f1`, `mathematical_equivalence`)。

- JCommonsenseQA(常識MCQ、5択)
- JEMHopQA(multi-hop QA、自由記述)
- JSQuAD(抽出QA、自由記述)
- MGSM-ja(数学計算、数値)

前処理コマンド:

```bash
cd evals/datasets/llm_jp_eval && uv sync
for t in jcommonsenseqa jemhopqa jsquad mgsm; do
  uv run python scripts/preprocess_dataset.py -d "$t" -o ./dataset
done
```

HF 認証は不要(JCQA/JEMHopQA/JSQuAD は GitHub raw、MGSM-ja は HF だが open)。HLE 系を将来追加する時のみ `uv run hf auth login`。

### IgakuQA (2018-2022)

[`jungokasai/IgakuQA`](https://github.com/jungokasai/IgakuQA) — 医師国家試験5年分。各問題に `points` フィールドが含まれており(必修問題は3点等)、`points_possible` としてそのまま使用。

**画像問題**: 元リポジトリは問題テキストのみで画像本体は同梱されていない。runner は画像問題を **常時スキップ** (`text_only=False` を除外)。

回ごとの分母:

| 年 | 回 | Overall (問/点) | No-Img (問/点) |
|---|---|---|---|
| 2018 | 第112回 | 400 / 499 | 286 / 362 |
| 2019 | 第113回 | 400 / 496 | 296 / 375 |
| 2020 | 第114回 | 400 / 496 | 287 / 365 |
| 2021 | 第115回 | 400 / 500 | 301 / 383 |
| 2022 | 第116回 | 400 / 494 | 301 / 379 |
| **計** | 5年合計 | **2000 / 2485** | **1471 / 1864** |

回ごとに必修・一般の数や配点が微妙に違うため Overall は完全な500点ではなく 494〜500 の幅(問題側 `points` をそのまま採用)。`leaderboard` に5年合算、`leaderboard_by_year` に年ごと。

### IgakuQA119 (第119回)

[`naoto-iwase/IgakuQA119`](https://github.com/naoto-iwase/IgakuQA119) — 第119回国試 (2025/2 実施)。OCR済みテキスト + 画像本体(`images/`)同梱。

**プロンプト**: default は `naoto-iwase/IgakuQA119` 公式 `src/llm_solver.py` 形式 (system + `answer:`/`confidence:`/`explanation:` 行) → 公開LB直接比較可。`--legacy` で旧独自形式 (`<answer>` タグ抽出) にフォールバック (出力は `igakuqa119_legacy.json`)。

**スコアリング規則**:
- 必修問題 (B/E ブロック): Q1-25 = 1点、**Q26-50 = 3点**
- 一般問題 (A/C/D/F): 1点
- 計500点満点 / 400問

ブロック別:

| ブロック | 種別 | 問数 | 配点 | No-Img 問数 | No-Img 配点 |
|---|---|---:|---:|---:|---:|
| 119A | 一般 | 75 | 75 | 41 | 41 |
| 119B | 必修 | 50 | 100 | 46 | 90 |
| 119C | 一般 | 75 | 75 | 60 | 60 |
| 119D | 一般 | 75 | 75 | 43 | 43 |
| 119E | 必修 | 50 | 100 | 43 | 85 |
| 119F | 一般 | 75 | 75 | 64 | 64 |
| **計** | | **400** | **500** | **297** | **383** |

A/D は画像率が高い(A=55%、D=57%が画像)。

### JMLE2026 (第120回)

[`naoto-iwase/JMLE2026-Bench`](https://github.com/naoto-iwase/JMLE2026-Bench) — 第120回医師国家試験 (2026/2 実施)。学習データに含まれない最新国試。

**プロンプト**: 公式 `benchmark.py` をそのまま採用 (system 2種 + `【回答】` 抽出) → 公開LBに直接並べられる。

**スコアリング規則** (IgakuQA119 と同じ):
- 必修問題 (B/E ブロック): Q1-25 = 1点、Q26-50 = 3点
- 一般問題 (A/C/D/F): 1点
- 計500点満点 / 400問

**ブロック別**:

| ブロック | 種別 | 問数 | 配点 |
|---|---|---:|---:|
| 120A | 一般 | 75 | 75 |
| 120B | 必修 | 50 | 100 |
| 120C | 一般 | 75 | 75 |
| 120D | 一般 | 75 | 75 |
| 120E | 必修 | 50 | 100 |
| 120F | 一般 | 75 | 75 |
| **計** | | **400** | **500** |

画像問題 98問 / Text-only 302問。連問 (`serial_group`) が50問あり、共通 `context_text` を user prompt に prepend。

**LB提出**: 結果JSONに `submission` キーで公式の `metadata`/`summary`/`results` 形式を同梱済み。`jq '.submission' jmle2026.json > <model>.json` で公式 PR にそのまま使える。

### JMED-LLM (MCQ 3タスク)

[`sociocom/JMED-LLM`](https://github.com/sociocom/JMED-LLM) のうち 3タスクを採用:

- **JMMLU-Med**: 医療MCQ (5科目: professional_medicine, medical_genetics, clinical_knowledge, anatomy, college_medicine)
- **CRADE**: 症例報告から ADE(有害事象)の可能性を 4段階で分類。**ordinal で線形重み付き κ**
- **RRTNM**: 読影レポートから TNM 分類予測

評価形式は公式LBに合わせて `κ(accuracy)`。CRADE は ordinal の線形重み付き κ、JMMLU-Med / RRTNM は標準の Cohen's κ。

`κ` 計算は `evals/tasks/jmed_llm/run.py:cohen_kappa` で実装(numpy なし、stdlib のみ)。OOV(出力が選択肢にマッチしない)は最遠カテゴリと同等にカウント。

## スコアリング詳細

### Score と Acc. の違い

| | 計算 |
|---|---|
| **Acc.** (Accuracy) | 正解数 / 問題数。全問同じ重み |
| **Score** | 獲得点 / 満点。**必修問題は3点扱い**(IgakuQA119 の B/E ブロック Q26-50) |

医師国家試験は必修問題が重く、必修には別途足切り(8割以上必須)がある。Score は実質「必修重視の総合点」、Acc. は「素の正答率」。同じ正答数でも必修を多く取りこぼすと **Score だけ大きく下がる**。リーダーボードで両方並ぶのはこのため。

例: Gemini-2.5-Pro Overall は 485/500 (97.00%) / 389/400 (97.25%)。400問中11問外したが配点では15点減 → 必修3点問題2問・一般1点問題9問の取りこぼしと逆算 (2×3 + 9×1 = 15)。

### vision auto-probe(画像問題の自動判定)

`igakuqa119` runner は起動時に **synthetic な red square PNG を送って色を質問**し、応答に `red`/`赤`/`まっか` が含まれるかで multimodal 対応を判定:

- **vision OK** → 画像問題を multimodal API (`type: "image_url"` で base64 PNG)で評価、**Overall 列が埋まる**
- **vision NG** → 画像問題を自動スキップ、**No-Img 列のみ**

reasoning モデル考慮で `max_tokens=512` に余裕を持たせ、`reasoning_content` も検査対象に含める。

`--no-vision` で probe 強制スキップ可能。`igakuqa` (2018-2022) は画像本体非同梱のため画像問題は常時スキップ。

### 公開LB並列形式

各タスクは公式リーダーボードと同じ列形式で集計され、結果JSONの `leaderboard` キーに格納。`summarize.py` の出力に **leaderboard rows** セクションが含まれ、公式リポジトリ README にそのまま貼れる Markdown 行が出る。

| ベンチ | 形式 | 例 |
|---|---|---|
| IgakuQA / IgakuQA119 | `Overall Score` / `Overall Acc.` / `No-Img Score` / `No-Img Acc.` | `461/500 (92.20%)` |
| JMLE2026 | `Overall Score` / `Overall Acc.` / `Text-only Score` / `Text-only Acc.` | `486/500 (97.20%)` |
| JMED-LLM | `kappa(accuracy)`、CRADE は線形重み付き κ | `0.54(0.53)` |
| llm-jp-eval | exact_match / char_f1 / mathematical_equivalence | `0.823` |

## 計測項目

### 速度

各リクエストごとに記録:

- **TTFT** (Time To First Token): プロンプト送信→最初のトークン
- **TTAT** (Time To Answer Token): プロンプト送信→`</think>` 直後の回答開始(reasoning時の体感)
- **total_time_ms** / **prompt_tokens** / **reasoning_tokens** / **answer_tokens**
- **decode tok/s**: `(reasoning + answer) / (total - ttft)` を `summarize.py` で事後計算

並列スループット(同時 4/8/16 ユーザー)は本ハーネスでは未測定。シングルクライアント前提。

### thinking 量

- `reasoning_tokens` 中央値・p90(per task)
- `reasoning_tokens / answer_tokens` 比
- accuracy vs `reasoning_tokens` トレードオフ(同精度なら think 短い方が運用上有利)

SGLang の `--reasoning-parser` で OpenAI互換APIの `reasoning_content` / `content` および `usage.reasoning_tokens` で取得。

## ハーネス使い方詳細

### タスクランナー共通フラグ

```
--base-url    SGLang endpoint (default http://localhost:8000)
--model       served-model-name
--task        タスク名 or "all" (タスク族による)
--output-dir  結果JSON保存先
--limit N     先頭N問のみ (スモーク用)
--no-think    chat_template_kwargs.enable_thinking=False
--max-tokens  default 32768
--temperature default 0.0
```

タスク族ごとの個別フラグ:

| 族 | 個別フラグ |
|---|---|
| `tasks.llm_jp_eval_subset` | `--task {jcommonsenseqa,jemhopqa,jsquad,mgsm,all}` |
| `tasks.igakuqa` | `--years 2018 2019 ...` |
| `tasks.igakuqa119` | `--blocks 119A 119B ...` `--no-vision`(auto-probe強制スキップ) `--legacy`(旧 `<answer>` タグ形式) |
| `tasks.jmle2026` | `--blocks A B ...` `--no-vision`(auto-probe強制スキップ) |
| `tasks.jmed_llm` | `--task {jmmlu_med,crade,rrtnm,smdis,jcsts,all}` (`all` は smdis/jcsts 除外、両者明示時のみ実行可) |

出力: `<output-dir>/<task>.json` — metrics、timing 分布、token 分布、`leaderboard`、全サンプル raw/extracted/正誤、started_at / ended_at。

### フェーズ実行 (`scripts/run_phase.sh`)

```bash
./evals/scripts/run_phase.sh <model> <output_subdir> [extra args...]
```

例:

```bash
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-on
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-off --no-think
./evals/scripts/run_phase.sh glm-5.1 _smoke --limit 5
```

引数振り分け:
- `--no-vision` は `igakuqa119` と `jmle2026` に転送 (両者とも vision タスク)
- `--legacy` は `igakuqa119` だけに転送 (旧 `<answer>` タグ形式へのフォールバック)
- それ以外 (`--limit`, `--no-think`, `--max-tokens`, `--temperature`, `--base-url`) は全タスクに転送

実行されるタスク: `llm-jp-eval-subset` の4タスク + `igakuqa` + `igakuqa119` + `jmle2026` + `jmed-llm` の3タスク = **計10タスク**。

### 結果集計 (`scripts/summarize.py`)

```bash
uv run --group evals python evals/scripts/summarize.py evals/results/<subdir>
# 別ランとの差分:
uv run --group evals python evals/scripts/summarize.py <a> --compare <b>
```

出力セクション:
- **score table**: タスクごとの精度、`tok/s p50`、TTAT、think tokens
- **leaderboard rows**: 公式 README にそのまま貼れる Markdown 行
- **timeline**: タスクごとの `started_at` / `ended_at`(ISO8601 + epoch_ms)

### Grafana 連携

各タスクJSONに記録される:

```json
"started_at": "2026-04-28T14:44:07+09:00",
"ended_at": "2026-04-28T14:44:13+09:00",
"started_epoch_ms": 1777355047398,
"ended_epoch_ms": 1777355053624,
"duration_sec": 6.23
```

`*_epoch_ms` を Grafana の Time Range (`from=...&to=...`) に貼れば SGLang `:8000/metrics` (Prometheus) や DCGM exporter (GPU 利用率/温度) の該当時間帯メトリクスを後追い確認できる。

## 補足: 本評価から除外したタスク

JMED-LLM の以下2タスクは Phase 1 で除外。Phase 2 以降も同様(全フェーズで揃える)。除外しても **JMED-LLM の MCQ 3タスク相対比較は成立**する。

### SMDIS (除外)

- **規模**: 15,360 行(他タスクの一桁多い、JMED-LLM 全体の 67%)
- **コスト**: 13.7 s/q × 15,360 = **約 55 時間 / 1モデル**(全Phaseで ~220h)
- **データ性質**: 模擬SNS投稿から「投稿者が1日以内に X病だったか」を A/B 判定。87.5% が「B」(陰性)で **強くインバランス**
- **院内利用との乖離**: SNSスタイル日本語で実カルテ・読影レポート・問診と別系統
- **判断**: コスト過大 / 弱インバランス / 院内非関連の三重で除外

### JCSTS (除外)

- **規模**: 3,670 行 / 19.5 s/q × 3,670 = **約 20 時間 / 1モデル**(全Phaseで ~80h)
- **データ性質**: 医療文の意味的類似度判定(6段階 ordinal、線形重み付き κ)
- **判断材料**:
  - 重要度 ★ (低)。類似度判定能力は他 MCQ で間接的に測れる
  - GLM-5.1 で 19% 進捗時点の acc は 0.349(参考値、kappa 換算で公開LB GPT-4o 0.60 を下回る見込み)
  - 「JMED-LLM 4タスク Average を出したい」という単一目的で ~80h は採算が合わない
- **判断**: 個別タスク値だけ欲しい時は `--task jcsts` で個別実行可能

両タスクとも `evals/tasks/jmed_llm/run.py` の `ALL_TASKS` リストでコメントアウト済み。**`--task all` を使う限り自動的にスキップ**される。明示すれば実行可能なので、時間に余裕がある時に 3モデル一括で改めて取得する方針。

## 後続(本ドキュメント範囲外)

- **院内ガイドラインMCQ**: 医師監修で50〜100問、機械採点
- **自院カルテ要約**: 医師による自由記述評価(N=30〜50)
- **長文性能**: Needle-in-a-Haystack JP (64K〜128K)
- **安全性**: PII漏洩・過剰拒否・プロンプトインジェクション
- **並列スループット**: 同時 4/8/16 ユーザー時の TTFT/throughput 劣化(`sglang.bench_serving` で別測)
- **JMED-LLM NER系** (CRNER/RRNER/NRNER): F1 計算実装が必要

これらは閉域化前後で別途追加、または個別検討。

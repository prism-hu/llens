# evals — 院内デプロイ候補モデルの日本語性能評価

フロンティアOSS LLM(GLM-5.1 / DeepSeek V3.2 / Kimi K2.6)の日本語+医療性能を、
公開リーダーボード(IgakuQA119, JMED-LLM, llm-jp-eval系)と同形式で計測。

- 評価仕様の詳細(ベンチ規模、採点ルール、ランナー仕様): [`SPEC.md`](./SPEC.md)

## 結果サマリ (最新: Phase 1 = GLM-5.1 thinking ON、9タスク完了)

### IgakuQA119 (第119回医師国家試験)

公式LB の 4列形式(Overall + No-Img)。Llama 系省略、国産は参考:

| Entry | Overall Score | Overall Acc. | No-Img Score | No-Img Acc. |
|---|---|---|---|---|
| Gemini-2.5-Pro | 485/500 (97.00%) | 389/400 (97.25%) | 372/383 (97.13%) | 290/297 (97.64%) |
| OpenAI-o3 | 482/500 (96.40%) | 384/400 (96.00%) | 370/383 (96.61%) | 286/297 (96.30%) |
| Claude-Sonnet-4 | 471/500 (94.20%) | 375/400 (93.75%) | 363/383 (94.78%) | 281/297 (94.61%) |
| DeepSeek-R1-0528 | 461/500 (92.20%) | 367/400 (91.75%) | 364/383 (95.04%) | 282/297 (94.95%) |
| **Kimi K2.6 (本検証 vision)** | **455/500 (91.00%)** | **367/400 (91.75%)** | **346/383 (90.34%)** | **272/297 (91.58%)** |
| DeepSeek-R1 | 448/500 (89.60%) | 356/400 (89.00%) | 350/383 (91.38%) | 270/297 (90.91%) |
| GPT-4o-mini | 345/500 (69.00%) | 279/400 (69.75%) | 269/383 (70.23%) | 215/297 (72.39%) |
| (参考) Preferred-MedLLM-Qwen-72B (国産医療FT) | 332/500 (66.40%) | 272/400 (68.00%) | 261/383 (68.15%) | 209/297 (70.37%) |
|   |   |   |   |   |
| **GLM-5.1 (本検証 text-only)** | - | - | **357/383 (93.21%)** | **281/297 (94.61%)** |

**観察**:
- Kimi K2.6 (vision): Overall Score 455/500 (91.00%) — DeepSeek-R1-0528 (92.20%) と DeepSeek-R1 (89.60%) の間
- GLM-5.1 (text-only): No-Img Acc 281/297 (94.61%) — Claude-Sonnet-4 (94.61%) と同点
- 同じ No-Img 列で比較すると **GLM-5.1 (94.61%) > Kimi K2.6 (91.58%)** で約3pt 差

### JMED-LLM (MCQ 3タスク、`κ(accuracy)` 形式) — Avg κ で並び替え

| Entry | jmmlu_med | crade | rrtnm | Avg κ |
|---|---|---|---|---|
| **GLM-5.1 (本検証)** | **0.89(0.92)** | **0.64(0.81)** | **0.89(0.92)** | **0.807** |
| gpt-4o-2024-08-06 | 0.82(0.87) | 0.54(0.53) | 0.85(0.90) | 0.737 |
| gpt-4o-mini | 0.77(0.83) | 0.21(0.37) | 0.58(0.71) | 0.520 |
| gemma-2-9b-it | 0.52(0.64) | 0.33(0.42) | 0.54(0.68) | 0.463 |
| (参考) Llama-3-ELYZA-JP-8B (国産日本語FT) | 0.34(0.51) | 0.01(0.26) | 0.29(0.52) | 0.213 |

JMED-LLM 公式 LB に Claude 4系/GPT-5/Gemini 2.5+ の評価は無く、現状 GPT-4o が最新クラウド baseline。SMDIS/JCSTS は除外(`SPEC.md`)。

### IgakuQA (2018-2022、5年合算) — No-Img

| Entry | No-Img Score | No-Img Acc. |
|---|---|---|
| 学生(多数決) | 1784/1864 (95.71%) | 1388/1471 (94.36%) |
| **GLM-5.1 (本検証)** | **1742/1864 (93.45%)** | **1368/1471 (93.00%)** |
| GPT-4 (2023, Kasai+) | 1557/1864 (83.53%) | 1213/1471 (82.46%) |
| ChatGPT (2023, Kasai+) | 1093/1864 (58.64%) | 860/1471 (58.46%) |

注: Claude 4系 / GPT-5 / Gemini 2.5+ の IgakuQA 2018-2022 直接評価値は publicly に存在しない(2026-04 時点)。IgakuQA119 が最新クラウドモデルの比較ライン。

### llm-jp-eval (短縮版)

| Task | GLM-5.1 |
|---|---|
| JCommonsenseQA (exact_match) | 0.977 |
| JEMHopQA (exact_match) | 0.658 |
| JSQuAD (exact_match) | 0.812 |
| MGSM-ja (math_equiv) | 0.432 |

比較相手は **未補強**(Nejumi LB は評価条件が異なり直接引用不可)。後日 OpenRouter 等の OpenAI 互換エンドポイント経由で Claude/GPT/Gemini を本ハーネスから叩いて apples-to-apples 値を埋める方針。

## 速度参考(TTAT 中央値・decode tok/s 中央値、シングルクライアント)

各 Phase の起動構成は対応する `scripts/sglang-*.sh` を参照(EAGLE 有無等で差あり)。

### TTAT p50 (秒)

| Task | GLM-5.1 ON | Kimi K2.6 ON | DeepSeek V3.2 ON | GLM-5.1 OFF |
|---|---:|---:|---:|---:|
| jcommonsenseqa | 1.8 | 2.9 | (Phase 2) | (Phase 3) |
| jemhopqa | 3.3 | 5.1 | | |
| jsquad | 3.1 | 3.6 | | |
| mgsm | 3.1 | 5.6 | | |
| igakuqa | 6.6 | (Phase 4 残り) | | |
| igakuqa119 | 6.6 | 13.9 | | |
| jmmlu_med | 5.0 | (Phase 4 残り) | | |
| crade | 8.7 | (Phase 4 残り) | | |
| rrtnm | 7.4 | (Phase 4 残り) | | |

### decode tok/s p50

| Task | GLM-5.1 ON | Kimi K2.6 ON | DeepSeek V3.2 ON | GLM-5.1 OFF |
|---|---:|---:|---:|---:|
| jcommonsenseqa | 99.9 | 78.1 | (Phase 2) | (Phase 3) |
| jsquad | 111.5 | 78.0 | | |
| mgsm | 106.6 | 77.8 | | |
| igakuqa119 | 91.9 | 77.3 | | |
| crade | 89.1 | (Phase 4 残り) | | |

GLM-5.1 は EAGLE spec decoding 有効、Kimi K2.6 は EAGLE3 ドラフト未公開のため spec decoding 無し。EAGLE3 公開後に Kimi の速度のみ再ラン予定。

## 簡易使い方

```bash
# 1. 依存
uv sync --group evals

# 2. データセット取得 (gitignored、外部ライセンスは各リポジトリ参照)
./evals/scripts/fetch_datasets.sh

# 3. llm-jp-eval は前処理が別途必要 (詳細 SPEC.md)
cd evals/datasets/llm_jp_eval && uv sync && cd -
for t in jcommonsenseqa jemhopqa jsquad mgsm; do
  (cd evals/datasets/llm_jp_eval && uv run python scripts/preprocess_dataset.py -d "$t" -o ./dataset)
done

# 4. SGLang 起動 (例: GLM-5.1)
./scripts/sglang-glm5.1.sh   # 別ターミナル

# 5. スモーク確認 → 本ラン
./evals/scripts/run_phase.sh glm-5.1 _smoke --limit 5
./evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-on

# 6. 集計 (公開LB形式の Markdown 行も出力)
uv run --group evals python evals/scripts/summarize.py evals/results/glm-5.1-think-on
```

タスク族の個別フラグや `run_phase.sh` の引数振り分け、`summarize.py` の出力詳細は [`SPEC.md`](./SPEC.md)。

## ディレクトリ

```
evals/
├── README.md             # このファイル(結果サマリ + 簡易使い方)
├── SPEC.md               # 詳細仕様(ベンチ・採点・ランナー)
├── harness/client.py     # streaming + reasoning分離クライアント
├── tasks/
│   ├── llm_jp_eval_subset/
│   ├── igakuqa/
│   ├── igakuqa119/       # vision auto-probe 対応
│   └── jmed_llm/
├── scripts/
│   ├── fetch_datasets.sh
│   ├── run_phase.sh      # 1モデル全タスク連続実行
│   └── summarize.py      # 結果集約 (Markdown + Grafana用 timestamp)
├── datasets/             # gitignored (clone先)
└── results/<subdir>/<task>.json   # gitignored
```

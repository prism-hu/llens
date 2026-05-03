# evals — 院内デプロイ候補モデルの日本語性能評価

フロンティアOSS LLM(GLM-5.1 / DeepSeek V3.2 / Kimi K2.6)の日本語+医療性能を、
公開リーダーボード(IgakuQA119, JMED-LLM, llm-jp-eval系)と同形式で計測。

- 評価仕様の詳細(ベンチ規模、採点ルール、ランナー仕様): [`SPEC.md`](./SPEC.md)

## 結果サマリ

10タスク (llm-jp-eval-subset 4 + 国試 3 + JMED-LLM 3):

| タスク | Kimi K2.6 | GLM-5.1 | DeepSeek V3.2 |
|---|---|---|---|
| jcommonsenseqa / jemhopqa / jsquad / mgsm | ✓ | ✓ | ✓ (think_off) |
| igakuqa (2018-2022) | ✓ | ✓ | ✓ (think_off) |
| igakuqa119 | ✓ (vision) | ⚠ 旧 skip 結果、blind 再ラン待ち | ⚠ 旧 skip 結果、blind 再ラン待ち |
| jmle2026 | ✓ (vision) | ✓ (blind) | ✓ (think_off, blind) |
| jmmlu_med / crade / rrtnm | ✓ | ✓ | ✓ (think_off) |

- DeepSeek V3.2 は think_off で完走 (default 起動が think_off のため、ハーネス側 `chat_template_kwargs.thinking=true` 修正後に think_on 再ラン予定)
- igakuqa119 は scope 修正 (skip → blind、LB 流儀準拠) のため GLM-5.1 / V3.2 は再ラン待ち

### JMLE2026 (第120回医師国家試験、2026/2 実施)

公式LB の 4列形式(Overall + Text-only)。第120回は学習データに含まれない最新国試。LB上位とQwen3.5系を抜粋:

| Entry | Overall Score | Overall Acc. | Text-only Score | Text-only Acc. |
|---|---|---|---|---|
| Claude Opus 4.6 | 493/500 (98.60%) | 393/400 (98.25%) | 380/382 (99.48%) | 300/302 (99.34%) |
| Gemini 3.1 Pro Preview | 493/500 (98.60%) | 393/400 (98.25%) | 378/382 (98.95%) | 298/302 (98.68%) |
| Claude Sonnet 4.6 | 489/500 (97.80%) | 391/400 (97.75%) | 378/382 (98.95%) | 298/302 (98.68%) |
| GPT-5.2 | 486/500 (97.20%) | 386/400 (96.50%) | 376/382 (98.43%) | 296/302 (98.01%) |
| **GLM-5.1 (本検証 blind)** | **481/500 (96.20%)** | **383/400 (95.75%)** | **370/382 (96.86%)** | **292/302 (96.69%)** |
| Qwen3.5-397B-A17B | 480/500 (96.00%) | 382/400 (95.50%) | 370/382 (96.86%) | 292/302 (96.69%) |
| **Kimi K2.6 (本検証 vision)** | **480/500 (96.00%)** | **384/400 (96.00%)** | **369/382 (96.60%)** | **291/302 (96.36%)** |
| Qwen3.5-35B-A3B | 480/500 (96.00%) | 380/400 (95.00%) | 370/382 (96.86%) | 290/302 (96.03%) |
| Qwen3.5-122B-A10B | 479/500 (95.80%) | 381/400 (95.25%) | 367/382 (96.07%) | 289/302 (95.70%) |
| GPT-OSS-Swallow-120B-RL-v0.1 | 473/500 (94.60%) | 379/400 (94.75%) | 365/382 (95.55%) | 289/302 (95.70%) |
| gpt-oss-120b (high) | 468/500 (93.60%) | 374/400 (93.50%) | 362/382 (94.76%) | 286/302 (94.70%) |
| **DeepSeek V3.2 (本検証 think_off blind)** | **458/500 (91.60%)** | **364/400 (91.00%)** | **358/382 (93.72%)** | **280/302 (92.72%)** |

出典: [naoto-iwase/JMLE2026-Bench](https://github.com/naoto-iwase/JMLE2026-Bench) leaderboard (本検証行除く)

**内訳** (本検証):

| カテゴリ | Kimi K2.6 (vision) | GLM-5.1 (blind) | V3.2 (think_off blind) | 合否ライン |
|---|---|---|---|---|
| 必修 (B+E、200点満点) | 191/200 (95.50%) | 195/200 (97.50%) | 186/200 (93.00%) | 160点 |
| 一般+臨床 (A+C+D+F、300点満点) | 289/300 (96.33%) | 286/300 (95.33%) | 272/300 (90.67%) | 224点 |
| 必修 (Text-only、168点) | 163/168 (97.02%) | 163/168 (97.02%) | 162/168 (96.43%) | — |
| 一般+臨床 (Text-only、214点) | 206/214 (96.26%) | 207/214 (96.73%) | 196/214 (91.59%) | — |

ブロック別正答率:

| ブロック | Kimi K2.6 (vision) | GLM-5.1 (blind) | V3.2 (think_off) |
|---|---|---|---|
| 120A 一般 | 97.3% | 98.7% | 90.7% |
| 120B 必修 | 96.0% | 96.0% | 90.0% |
| 120C 一般 | 93.3% | 90.7% | 88.0% |
| 120D 一般 | **100.0%** | 97.3% | 92.0% |
| 120E 必修 | 94.0% | **98.0%** | 94.0% |
| 120F 一般 | 94.7% | 94.7% | 92.0% |

**観察**:
- **GLM-5.1 (blind) Overall 481/500 (96.20%) で Kimi K2.6 (vision) 480/500 を +1 で上回る** — LB 上 #5 (GPT-5.2 直下、Qwen3.5-397B-A17B 並び)
- GLM-5.1 必修 195/200 (97.50%) と Kimi K2.6 191/200 (95.50%) で **必修で +4点** が GLM 優位の主因
- GLM-5.1 画像問題 acc 92.9% (91/98) — 画像見えてないのに9割超解ける = **テキスト文脈で十分解ける問題が多い** (大半が患者背景・症状の文章記述で、画像は補助的な役割)
- 必修・一般 とも合否ライン通過 (両モデル)。120D は Kimi 全問正解、120E は GLM 98%
- frontier クラウド勢 (Claude/Gemini/GPT-5) には **Overall で 5-13点差**、Text-only に絞ってもギャップ縮まらず

### IgakuQA119 (第119回医師国家試験)

公式LB の 4列形式(Overall + No-Img)。プロンプトは `naoto-iwase/IgakuQA119` `src/llm_solver.py` 準拠 (公開LB直接比較可)。Llama 系省略、国産は参考:

| Entry | Overall Score | Overall Acc. | No-Img Score | No-Img Acc. |
|---|---|---|---|---|
| Gemini-2.5-Pro | 485/500 (97.00%) | 389/400 (97.25%) | 372/383 (97.13%) | 290/297 (97.64%) |
| OpenAI-o3 | 482/500 (96.40%) | 384/400 (96.00%) | 370/383 (96.61%) | 286/297 (96.30%) |
| Claude-Sonnet-4 | 471/500 (94.20%) | 375/400 (93.75%) | 363/383 (94.78%) | 281/297 (94.61%) |
| **Kimi K2.6 (本検証 vision)** | **465/500 (93.00%)** | **375/400 (93.75%)** | **357/383 (93.21%)** | **281/297 (94.61%)** |
| **GLM-5.1 (本検証 blind、再ラン待ち)** | 再ラン待ち | 再ラン待ち | **363/383 (94.78%)** | **285/297 (95.96%)** |
| DeepSeek-R1-0528 | 461/500 (92.20%) | 367/400 (91.75%) | 364/383 (95.04%) | 282/297 (94.95%) |
| DeepSeek-R1 | 448/500 (89.60%) | 356/400 (89.00%) | 350/383 (91.38%) | 270/297 (90.91%) |
| **DeepSeek V3.2 (本検証 think_off blind)** | **431/500 (86.20%)** | **353/400 (88.25%)** | **332/383 (86.68%)** | **266/297 (89.56%)** |
| GPT-4o-mini | 345/500 (69.00%) | 279/400 (69.75%) | 269/383 (70.23%) | 215/297 (72.39%) |
| (参考) Preferred-MedLLM-Qwen-72B (国産医療FT) | 332/500 (66.40%) | 272/400 (68.00%) | 261/383 (68.15%) | 209/297 (70.37%) |

出典: [naoto-iwase/IgakuQA119](https://github.com/naoto-iwase/IgakuQA119) leaderboard (本検証行除く)

**内訳** (本検証):

| カテゴリ | Kimi K2.6 (vision) | GLM-5.1 (旧 skip、再ラン待ち) | V3.2 (think_off blind) |
|---|---|---|---|
| 必修 (B+E、200点満点) | 182/200 (91.00%) | 再ラン待ち | 161/200 (80.50%) |
| 一般 (A+C+D+F、300点満点) | 283/300 (94.33%) | 再ラン待ち | 270/300 (90.00%) |
| 必修 (No-Img、175点) | 158/175 (90.29%) | 163/175 (93.14%) | 142/175 (81.14%) |
| 一般 (No-Img、208点) | 199/208 (95.67%) | 200/208 (96.15%) | 190/208 (91.35%) |

ブロック別正答率:

| ブロック | Kimi K2.6 | GLM-5.1 (No-Img) | V3.2 (think_off) |
|---|---|---|---|
| 119A 一般 | 97.3% | 97.6% | 90.7% |
| 119B 必修 | 92.0% | 97.8% | 86.0% |
| 119C 一般 | 92.0% | 96.7% | 84.0% |
| 119D 一般 | 92.0% | 95.4% | 92.0% |
| 119E 必修 | 92.0% | 93.0% | 80.0% |
| 119F 一般 | 96.0% | 95.3% | 93.3% |

**観察**:
- Kimi K2.6 Overall 465/500 (93.00%) — Claude-Sonnet-4 (94.20%) と DeepSeek-R1-0528 (92.20%) の間。**Acc は Claude-Sonnet-4 と同点 (375/400)**
- GLM-5.1 No-Img Score 363/383 (94.78%) で **Claude-Sonnet-4 と完全同点**、Acc は 285/297 (95.96%) で **Claude-Sonnet-4 (94.61%) を 1.3pt 上回る**
- No-Img only 比較では **GLM-5.1 (94.78%) > Kimi K2.6 (93.21%)**。119B 必修で +5.8pt の差が効いてる
- GLM-5.1 の Overall 列は scope 修正 (skip → blind) のための再ラン待ち。jmle2026 と同様、画像問題を blind で解いて Overall も埋まる予定

#### 補足: legacy プロンプト形式 (`<answer>` タグ抽出) との比較

ハーネス清書前 (旧 default = 独自 `<answer>` タグ抽出) の測定値。公式LB形式に乗り換えた際の差分確認用:

| Entry | Overall Score | Overall Acc. | No-Img Score | No-Img Acc. |
|---|---|---|---|---|
| Kimi K2.6 (legacy `<answer>` tag、vision) | 455/500 (91.00%) | 367/400 (91.75%) | 346/383 (90.34%) | 272/297 (91.58%) |
| GLM-5.1 (legacy `<answer>` tag、text-only) | - | - | 357/383 (93.21%) | 281/297 (94.61%) |

形式差分 (新 default - legacy):

| | Score | Acc. (No-Img) |
|---|---|---|
| Kimi K2.6 (No-Img) | +11 (346→357) | +9問 (272→281、+3.03pt) |
| GLM-5.1 (No-Img) | +6 (357→363) | +4問 (281→285、+1.35pt) |

**観察**: 両モデルとも公式LB形式 (`answer:` 行) で改善するが Kimi K2.6 の方が改善幅が大きい (`<answer>` タグの遵守率に差)。**順位 (GLM > Kimi on No-Img) はどちらの形式でも変わらず**、結論はロバスト。

### JMED-LLM (MCQ 3タスク、`κ(accuracy)` 形式) — Avg κ で並び替え

| Entry | jmmlu_med | crade | rrtnm | Avg κ |
|---|---|---|---|---|
| **Kimi K2.6 (本検証)** | **0.90(0.92)** | **0.67(0.81)** | **0.90(0.93)** | **0.823** |
| **GLM-5.1 (本検証)** | **0.89(0.92)** | **0.64(0.81)** | **0.89(0.92)** | **0.807** |
| gpt-4o-2024-08-06 | 0.82(0.87) | 0.54(0.53) | 0.85(0.90) | 0.737 |
| **DeepSeek V3.2 (本検証 think_off)** | **0.83(0.87)** | **0.58(0.78)** | **0.74(0.81)** | **0.717** |
| gpt-4o-mini | 0.77(0.83) | 0.21(0.37) | 0.58(0.71) | 0.520 |
| gemma-2-9b-it | 0.52(0.64) | 0.33(0.42) | 0.54(0.68) | 0.463 |
| (参考) Llama-3-ELYZA-JP-8B (国産日本語FT) | 0.34(0.51) | 0.01(0.26) | 0.29(0.52) | 0.213 |

出典: [sociocom/JMED-LLM](https://github.com/sociocom/JMED-LLM) leaderboard (本検証行除く)

JMED-LLM 公式 LB に Claude 4系/GPT-5/Gemini 2.5+ の評価は無く、現状 GPT-4o が最新クラウド baseline。SMDIS/JCSTS は除外(`SPEC.md`)。

### IgakuQA (2018-2022、5年合算)

PFN ([HF card](https://huggingface.co/pfnet/Preferred-MedLLM-Qwen-72B) / [arxiv 2504.18080](https://arxiv.org/abs/2504.18080)) の表を借用。**5年合計2485点満点、画像問題はテキストのみで盲解き** (PFN/Kasai+ と同 scope):

| Entry | 5年合計 Score | 2018 | 2019 | 2020 | 2021 | 2022 |
|---|---:|---:|---:|---:|---:|---:|
| **GLM-5.1 (本検証)** | **2283/2485 (91.87%)** | **455** | **458** | **460** | **450** | **460** |
| **Kimi K2.6 (本検証)** | **2245/2485 (90.34%)** | **441** | **454** | **450** | **449** | **451** |
| Preferred-MedLLM-Qwen-72B | 2156/2485 (86.76%) | 434 | 420 | 439 | 430 | 433 |
| GPT-4o | 2152/2485 (86.60%) | 427 | 431 | 433 | 427 | 434 |
| **DeepSeek V3.2 (本検証 think_off)** | **2053/2485 (82.62%)** | **406** | **412** | **401** | **414** | **420** |
| Qwen2.5-72B | 1992/2485 (80.16%) | 412 | 394 | 394 | 393 | 399 |
| Llama3-Preferred-MedSwallow-70B | 1976/2485 (79.52%) | 407 | 390 | 391 | 393 | 395 |
| GPT-4 | 1944/2485 (78.23%) | 382 | 385 | 387 | 398 | 392 |
| Mistral-Large-Instruct-2407 | 1880/2485 (75.65%) | 370 | 371 | 390 | 373 | 376 |
| Llama-3.1-Swallow-70B-v0.1 | 1842/2485 (74.13%) | 379 | 378 | 379 | 351 | 355 |
| Meta-Llama-3-70B | 1673/2485 (67.32%) | 353 | 340 | 348 | 314 | 318 |
| GPT-3.5 | 1366/2485 (54.97%) | 266 | 250 | 266 | 297 | 287 |
| (人間) 学生多数決 | 1784/1864 (95.71%、No-Img) | - | - | - | - | - |

出典: 比較行 = [pfnet/Preferred-MedLLM-Qwen-72B (HF card)](https://huggingface.co/pfnet/Preferred-MedLLM-Qwen-72B) / [arxiv 2504.18080](https://arxiv.org/abs/2504.18080)。学生行 = [arxiv 2303.18027](https://arxiv.org/abs/2303.18027) / [jungokasai/IgakuQA](https://github.com/jungokasai/IgakuQA) (No-Img scope のため別建て)

**注**:
- **本検証2モデルとも PFN 表トップ (Preferred-MedLLM-Qwen-72B 431.2/年、GPT-4o 430.4/年) を上回る**
  - GLM-5.1: 456.6/年 (+25.4点/年)
  - Kimi K2.6: 449.0/年 (+18.0点/年)
- 5年全てで GLM-5.1 > Kimi K2.6 (+1〜14点/年)
- 画像問題 (text-only blind) acc: GLM-5.1 85.6% / Kimi K2.6 83.2%、text問題 acc: GLM-5.1 93.5% / Kimi K2.6 91.4% → **画像問題は画像見えてないのに 8割超解けてる = リーク疑い濃厚** (2018-2022 はネット解説サイトに完全に出回っている)
- フロンティア (Claude 4系/GPT-5/Gemini 2.5+) は同様に事前学習リーク確実視で publicly な評価値も存在しない (2026-05 時点)
- 最新モデル比較ラインは IgakuQA119 / JMLE2026 に移行

### llm-jp-eval (短縮版)

| Task | GLM-5.1 | Kimi K2.6 | V3.2 (think_off) |
|---|---|---|---|
| JCommonsenseQA (exact_match) | 0.977 | 0.979 | 0.920 |
| JEMHopQA (exact_match / char_f1) | 0.658 / - | 0.617 / 0.747 | 0.300 / 0.351 |
| JSQuAD (exact_match / char_f1) | 0.812 / - | 0.806 / 0.912 | 0.815 / 0.920 |
| MGSM-ja (math_equiv) | 0.432 | **0.904** | 0.872 |

比較相手は **未補強**(Nejumi LB は評価条件が異なり直接引用不可)。後日 OpenRouter 等の OpenAI 互換エンドポイント経由で Claude/GPT/Gemini を本ハーネスから叩いて apples-to-apples 値を埋める方針。

## 速度参考(TTAT 中央値・decode tok/s 中央値、シングルクライアント)

各 Phase の起動構成は対応する `scripts/sglang-*.sh` を参照(EAGLE 有無等で差あり)。

### TTAT p50 (秒)

| Task | GLM-5.1 ON | Kimi K2.6 ON | V3.2 OFF | (V3.2 ON 待ち) |
|---|---:|---:|---:|---:|
| jcommonsenseqa | 1.8 | 2.9 | 0.1 | |
| jemhopqa | 3.3 | 5.1 | 0.2 | |
| jsquad | 3.1 | 3.6 | 0.2 | |
| mgsm | 3.1 | 5.6 | 0.1 | |
| igakuqa | 7.5 | 13.6 | 0.2 | |
| igakuqa119 | 7.3 | 16.3 | 0.1 | |
| jmle2026 | 7.4 | 16.2 | 0.1 | |
| jmmlu_med | 5.0 | 9.0 | 0.2 | |
| crade | 8.7 | 18.1 | 0.2 | |
| rrtnm | 7.4 | 15.0 | 0.2 | |

### decode tok/s p50

| Task | GLM-5.1 ON | Kimi K2.6 ON | V3.2 OFF | (V3.2 ON 待ち) |
|---|---:|---:|---:|---:|
| jcommonsenseqa | 99.9 | 78.1 | 55.5 | |
| jsquad | 111.5 | 78.0 | 89.7 | |
| mgsm | 106.6 | 77.8 | 76.8 | |
| igakuqa | 91.4 | 77.3 | 91.9 | |
| igakuqa119 | 80.7 | 63.8 | 50.1 | |
| jmle2026 | 93.0 | 63.9 | 38.6 | |
| crade | 89.1 | 64.0 | 99.8 | |
| rrtnm | 101.5 | 63.4 | 101.8 | |

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
│   ├── igakuqa/          # 画像問題は常に text-only blind (PFN/Kasai+ scope = 2485点)
│   ├── igakuqa119/       # vision auto-probe、vision NG → blind (全400問、Overall列populated)
│   ├── jmle2026/         # vision auto-probe、vision NG → blind (全400問、Overall列populated)
│   └── jmed_llm/
├── scripts/
│   ├── fetch_datasets.sh
│   ├── run_phase.sh      # 1モデル全タスク連続実行
│   └── summarize.py      # 結果集約 (Markdown + Grafana用 timestamp)
├── datasets/             # gitignored (clone先)
└── results/<subdir>/<task>.json   # gitignored
```

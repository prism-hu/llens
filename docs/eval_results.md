# 評価進捗・結果

各 Phase の進捗・実測値・公開LB との比較を記録。仕様の詳細は [`evals/SPEC.md`](../evals/SPEC.md)、最新サマリは [`evals/README.md`](../evals/README.md)。

## ステータス概要

| Phase | モデル | thinking | 状況 | 完了日 |
|---|---|---|---|---|
| 1 | GLM-5.1 | ON | **完了** | 2026-04-29 |
| 4 | Kimi K2.6 | ON | 進行中 | 2026-04-30 〜 |
| 2 | DeepSeek V3.2 | ON | 未着手 | - |
| 3 | GLM-5.1 | OFF | 未着手 | - |

Phase 4 を先行(EAGLE3 ドラフト公開待ちが ~1ヶ月見込みのため、待たず先に着手)。EAGLE3 公開後に Kimi K2.6 速度のみ再ラン予定。

各 Phase 共通条件:
- temperature=0、max_tokens=32768、N=1
- vision auto-probe あり(text-only モデルでは画像問題自動スキップ → No-Img のみ)
- SMDIS / JCSTS は除外(理由は `evals/SPEC.md` 末尾)
- 起動 config は git 管理(`scripts/sglang-*.sh`)

---

## Phase 1: GLM-5.1 thinking ON (完了)

- 起動: `scripts/sglang-glm5.1.sh`(EAGLE spec decoding 有効、TP8、context 131072、FP8)
- 実行: 2026-04-28 15:27 〜 2026-04-29 14:16(~23時間、9タスク)
- vision_used: false(text-only モデル → 画像問題は auto-skip)

### IgakuQA119 (第119回医師国家試験)

公式LB の Overall + No-Img の 4列形式で、Llama 系省略 / 国産は参考行:

| Entry | Overall Score | Overall Acc. | No-Img Score | No-Img Acc. |
|---|---|---|---|---|
| Gemini-2.5-Pro | 485/500 (97.00%) | 389/400 (97.25%) | 372/383 (97.13%) | 290/297 (97.64%) |
| OpenAI-o3 | 482/500 (96.40%) | 384/400 (96.00%) | 370/383 (96.61%) | 286/297 (96.30%) |
| Gemini-2.5-Flash | 478/500 (95.60%) | 382/400 (95.50%) | 371/383 (96.87%) | 287/297 (96.63%) |
| Claude-Sonnet-4 | 471/500 (94.20%) | 375/400 (93.75%) | 363/383 (94.78%) | 281/297 (94.61%) |
| Qwen3-235B-A22B | 462/500 (92.40%) | 366/400 (91.50%) | 356/383 (92.95%) | 274/297 (92.26%) |
| DeepSeek-R1-0528 | 461/500 (92.20%) | 367/400 (91.75%) | 364/383 (95.04%) | 282/297 (94.95%) |
| DeepSeek-R1 | 448/500 (89.60%) | 356/400 (89.00%) | 350/383 (91.38%) | 270/297 (90.91%) |
| Gemini-2.0-Flash | 436/500 (87.20%) | 352/400 (88.00%) | 333/383 (86.95%) | 263/297 (88.55%) |
| Qwen3-32B | 415/500 (83.00%) | 329/400 (82.25%) | 334/383 (87.21%) | 256/297 (86.20%) |
| GPT-4o-mini | 345/500 (69.00%) | 279/400 (69.75%) | 269/383 (70.23%) | 215/297 (72.39%) |
| (参考) Preferred-MedLLM-Qwen-72B (国産医療FT) | 332/500 (66.40%) | 272/400 (68.00%) | 261/383 (68.15%) | 209/297 (70.37%) |
| (参考) MedGemma-27B-Q6_K | 324/500 (64.80%) | 250/400 (62.50%) | 254/383 (66.32%) | 194/297 (65.32%) |
| (参考) PLaMo-2.0-Prime (国産) | 286/500 (57.20%) | 228/400 (57.00%) | 229/383 (59.79%) | 175/297 (58.92%) |
|   |   |   |   |   |
| **GLM-5.1 (本検証、text-only)** | - | - | **357/383 (93.21%)** | **281/297 (94.61%)** |
| **Kimi K2.6 (本検証、vision)** | (Phase 4 進行中) | (Phase 4 進行中) | (Phase 4 進行中) | (Phase 4 進行中) |
| DeepSeek V3.2 (text-only) | (Phase 2 未着手) | (Phase 2 未着手) | (Phase 2 未着手) | (Phase 2 未着手) |

(出典: https://github.com/naoto-iwase/IgakuQA119 README、2026-04-28時点)

**GLM-5.1 (text-only) の No-Img Acc. は Claude-Sonnet-4 と完全同点**(281/297, 94.61%)。Overall 列は text-only モデルなので "-"(画像問題は auto-skip)。

**Kimi K2.6 は vision OK 検出済み → Phase 4 完走で Overall 列も埋まる予定**。Gemini 2.5 / o3 等の vision 付き frontier モデルとの直接比較が初めて可能になる。

### IgakuQA (2018-2022、5年合算)

GLM-5.1 は **No-Img** で評価(text-only モデル、画像問題は auto-skip)。比較対象として:
- 古いベース(Kasai+ 2023) は **No-Img / `points` 加重** で本ハーネスと同条件再採点(下記表)
- PFN paper 値は **Overall (5年平均 / 500点満点)** ベースで条件異種(下記注)

| Entry | No-Img Score | No-Img Acc. |
|---|---|---|
| 学生(多数決) | 1784/1864 (95.71%) | 1388/1471 (94.36%) |
| **GLM-5.1 (本検証)** | **1742/1864 (93.45%)** | **1368/1471 (93.00%)** |
| GPT-4 (Kasai+ 2023) | 1557/1864 (83.53%) | 1213/1471 (82.46%) |
| ChatGPT (Kasai+ 2023) | 1093/1864 (58.64%) | 860/1471 (58.46%) |

(GPT-4/ChatGPT/学生の値は `evals/datasets/igakuqa/baseline_results/` の予測ファイルを本ハーネスと同じ採点規則で集計)

#### Overall ベース参考(条件異種、PFN paper 2025)

PFN の論文 [arXiv:2504.18080](https://arxiv.org/abs/2504.18080) は **Overall(画像問題込みの5年平均 / 500点満点)** で評価。GLM-5.1 とは分母が異なるが、最新クラウドモデルの参考値として:

| Entry | Overall Acc (5年平均) | Overall Score (5年平均) |
|---|---|---|
| **(参考) Preferred-MedLLM-Qwen-72B** | 0.868 | 431.2 / 500 |
| GPT-4o (3-shot) | 0.866 | 430.4 / 500 |
| GPT-4-Turbo | 0.812 | - |
| Qwen2.5-72B-Instruct | 0.802 | 398.4 / 500 |
| GPT-4 (2023) | - | 388.8 / 500 |

**Claude Opus/Sonnet 4系・GPT-5系・Gemini 2.5+ の IgakuQA 2018-2022 直接評価は公開されていない**(検索範囲)。最新クラウドモデルの位置付けは IgakuQA119 (上記表) で代用。

参考 Suzuki+ 2026: **国試の別問題セット (n=793, 2019+2025年)** での比較値 — Gemini 2.5 Pro 97.2% / GPT-5 96.3% / Claude Opus 4.1 96.1% / Grok-4 95.6%。これは IgakuQA 2018-2022 とは別ベンチだが、最新クラウドモデル間の相対序列の参考になる。

### JMED-LLM (MCQ 3タスク、`κ(accuracy)` 形式 / CRADE 線形重み付き κ)

公式 LB から MCQ 3タスク分を抜粋(Llama 系は省略、gemma 系と国産医療FTを参考行に)。**Avg κ で並び替え**:

| Entry | jmmlu_med | crade | rrtnm | Avg κ |
|---|---|---|---|---|
| **GLM-5.1 (本検証)** | **0.89(0.92)** | **0.64(0.81)** | **0.89(0.92)** | **0.807** |
| gpt-4o-2024-08-06 | 0.82(0.87) | 0.54(0.53) | 0.85(0.90) | 0.737 |
| gpt-4o-mini-2024-07-18 | 0.77(0.83) | 0.21(0.37) | 0.58(0.71) | 0.520 |
| google/gemma-2-9b-it | 0.52(0.64) | 0.33(0.42) | 0.54(0.68) | 0.463 |
| google/gemma-2-2b-it | 0.17(0.38) | 0.00(0.25) | 0.24(0.43) | 0.137 |
| **(参考) elyza/Llama-3-ELYZA-JP-8B (国産日本語FT)** | 0.34(0.51) | 0.01(0.26) | 0.29(0.52) | 0.213 |

(GLM-5.1 以外: 出典 [sociocom/JMED-LLM](https://github.com/sociocom/JMED-LLM) README LB)

**GLM-5.1 が κ Average で全モデルを上回り堂々の1位**(GPT-4o 比 +0.07)。

**注**: JMED-LLM 公式 LB には Claude 4系 / GPT-5 / Gemini 2.5 等の最新クラウドモデル評価が無く、現状 GPT-4o が利用可能な最新クラウド baseline。本来 8タスク (MCQ 5 + NER 3) の Average 評価だが、本検証は MCQ 3 のみ(SMDIS/JCSTS 除外、NER 未実装)で直接 Average 比較不可。

SMDIS / JCSTS の除外理由は `evals/SPEC.md` 末尾参照。時間に余裕がある時に **3モデル(GLM-5.1 / DeepSeek V3.2 / Kimi K2.6)で改めて取得予定**。

### llm-jp-eval (短縮版、4タスク)

| Task | n | Metric | GLM-5.1 |
|---|---:|---|---|
| JCommonsenseQA | 1119 | exact_match | 0.977 |
| JEMHopQA | 120 | exact_match | 0.658 |
| JSQuAD | 4442 | exact_match | 0.812 |
| MGSM-ja | 250 | math_equiv | 0.432 |

(MGSM-ja は数学計算問題、温度0でも揺れあり)

**比較対象モデルの状況**:

llm-jp-eval 系の最新クラウドモデル評価は [Nejumi LLM Leaderboard 4](https://wandb.ai/llm-leaderboard) (W&B、2025-08 更新) にあるが、**W&B Tables の JS 動的描画**で値が直接抽出できず、また評価条件(few-shot N、prompt template、jaster バージョン)が本検証と異なる。直接引用ではなく以下の方針:

1. **クラウドAPI 自前評価(推奨)**: Claude/GPT/Gemini を OpenRouter 等の OpenAI 互換エンドポイント経由で本ハーネスから叩く。`--base-url https://openrouter.ai/api/v1` に変えるだけで Phase 1 と同条件で測れる。9タスク × 1モデルで API代 ~数百円〜数千円。後日着手予定
2. **国産モデル ローカル実走**: `llm-jp-3-8x13b-instruct3` / `SIP-jmed-llm-3-8x13b` を Phase 4 後にローカル実走 (起動 script 準備済み、TP=1 で数時間)
3. **Nejumi LB 引用は保留**: 評価条件が異なるため直接並列は非推奨

現状 llm-jp-eval セクションの比較相手は薄い(GLM-5.1 単独)。優先度は 医療系(IgakuQA/JMED-LLM)が高いため、llm-jp-eval は全体方針が固まってから補強する。

### 速度参考値 (TTAT 中央値、シングルリクエスト、H200x8、EAGLE 有効)

| Task | tok/s p50 | TTAT p50 | TTAT p90 | think_tok p50 | answer_tok p50 |
|---|---:|---:|---:|---:|---:|
| jcommonsenseqa | 99.9 | 1.8 s | 4.0 s | 168 | 2 |
| jemhopqa | 96.8 | 3.3 s | 10.1 s | 310 | 10 |
| jsquad | 111.5 | 3.1 s | 5.0 s | 328 | 11 |
| mgsm | 106.6 | 3.1 s | 9.2 s | 309 | 4 |
| igakuqa | 92.2 | 6.6 s | 14.2 s | 598 | 7 |
| igakuqa119 | 91.9 | 6.6 s | 12.7 s | 585 | 7 |
| jmmlu_med | 93.7 | 5.0 s | 12.7 s | 457 | 7 |
| crade | 89.1 | 8.7 s | 29.3 s | 774 | 7 |
| rrtnm | 101.5 | 7.4 s | 14.7 s | 734 | 7 |

decode tok/s 中央値 ~95 token/s(EAGLE spec decoding 有効)。

### Phase 1 含意

候補1である **GLM-5.1 が、日本語特化FT組や同規模クラスのオープンモデルを既存ベンチで広く上回り、フロンティア閉源モデル(Claude-Sonnet-4、Gemini系下位)に肉薄する水準** を text-only ベンチ (No-Img) で達成。

院内デプロイ候補としての一次資料に十分なシグナルあり。次は本命の **Kimi K2.6 (Phase 4 を先行、vision込み Overall 列も埋める)**、その後 DeepSeek V3.2、GLM-5.1 think OFF版で最終比較。

---

## Phase 4: Kimi K2.6 thinking ON (進行中、2026-04-30 〜)

- 起動: `scripts/sglang-kimi-k2.6.sh`(spec decoding 無し、TP8、context 131072、INT4 QAT)
- 期待: vision auto-probe **OK**(MoonViT 内蔵)→ **IgakuQA119 Overall 列も初めて埋まる**
- 推定完走時間: ~30-40h(EAGLE3 無し + 1.1T params + 画像問題込みのため Phase 1 より長め)

EAGLE3 ドラフト公開待ち中だが、~1ヶ月見込みのため待たず先行。EAGLE3 公開後に **速度のみ再ラン**(精度は spec decoding に影響されないので再ラン不要)。

完走後にここに結果追記。

---

## Phase 2: DeepSeek V3.2 thinking ON (未着手)

- 起動予定: `scripts/sglang-deepseek-v3.2.sh`
- spec decoding (MTP) 適用可否を要確認

---

## Phase 3: GLM-5.1 thinking OFF (未着手)

- Phase 1 と同重み、`--no-think` (`enable_thinking: false`) で Phase 1 との差分を計測
- 主目的: thinking が精度・速度にどれだけ寄与しているかの定量化

---

## 備考

### Score / Acc. の使い分け

- **Acc.**: 正解数/問題数(全問同重み)→ モデルの素の正答率
- **Score**: 配点(必修3点等)を加味した加重総合点 → 試験合否に近い指標

医師国家試験の必修問題には別途足切り(8割以上必須)があり、Score はそれを反映した重み付け。同じ正答数でも必修取りこぼしは Score を大きく削る。リーダーボードで両方並ぶのはこのため。詳細は `evals/SPEC.md`。

### Overall vs No-Img の使い分け

- **Overall**: 400問全部(画像問題含む)/ 500点満点
- **No-Img**: 画像なし問題のみ(297問 / 383点)

text-only モデル(GLM/DeepSeek)は画像問題が解けないため、runner の vision auto-probe で自動スキップ → No-Img 列のみ埋まる。Gemini-2.5-Pro 等は vision で画像を実際に解いて Overall 97% を出しているため、text-only モデルと同じ列で並べるのはアンフェア。

vision モデル(Kimi K2.6 等)は probe で **vision OK** 検出 → 画像問題も評価 → Overall 列も埋まる。

### 評価条件(全Phase 共通)

- 起動 config を git 管理(`scripts/sglang-*.sh`)、設定差は明示
- 各モデル公式推奨設定 + 公開済み高速化(EAGLE 等)を入れた "as-released best"
- temperature=0、max_tokens=32768、N=1(MoE は微揺れあるが 5%以上の差なら結論可能)
- 単一クライアント計測(並列スループットは別途、本ハーネス範囲外)
- 詳細仕様は `evals/SPEC.md`

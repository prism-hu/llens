# 評価結果(暫定)

**Phase 1 (GLM-5.1 thinking ON) 進行中**。本ドキュメントはランが完走する前の **暫定報告**です。完走後に上書き更新。

- 起動構成: `scripts/sglang-glm5.1.sh` (EAGLE spec decoding 有効、TP8、context 131072、FP8)
- thinking ON、temperature=0、max_tokens=32768
- 実行: 2026-04-28 ~ 進行中
- 全11タスク中 **9タスク完了**(残: `smdis`, `jcsts`)

## ハイライト

### IgakuQA119 (第119回医師国家試験) — No-Img

| Entry | No-Img Score | No-Img Acc. |
|---|---|---|
| Gemini-2.5-Pro | 372/383 (97.13%) | 290/297 (97.64%) |
| Gemini-2.5-Flash | 371/383 (96.87%) | 287/297 (96.63%) |
| OpenAI-o3 | 370/383 (96.61%) | 286/297 (96.30%) |
| DeepSeek-R1-0528 | 364/383 (95.04%) | 282/297 (94.95%) |
| Claude-Sonnet-4 | 363/383 (94.78%) | 281/297 (94.61%) |
| **GLM-5.1 (本検証)** | **357/383 (93.21%)** | **281/297 (94.61%)** |
| Qwen3-235B-A22B | 356/383 (92.95%) | 274/297 (92.26%) |
| DeepSeek-R1 | 350/383 (91.38%) | 270/297 (90.91%) |
| Llama4-Maverick | 336/383 (87.73%) | 260/297 (87.54%) |
| Qwen3-32B | 334/383 (87.21%) | 256/297 (86.20%) |
| ... | ... | ... |
| Preferred-MedLLM-Qwen-72B | 261/383 (68.15%) | 209/297 (70.37%) |

(出典: https://github.com/naoto-iwase/IgakuQA119 README、2026-04-28時点)

**No-Img Score では Qwen3-235B-A22B / DeepSeek-R1 / Llama4-Maverick / Qwen3-32B より上、Claude-Sonnet-4 とほぼ同等**。No-Img Acc. は Claude-Sonnet-4 と完全同点 (281/297, 94.61%)。

国内日本語FT勢 (Preferred-MedLLM-Qwen-72B 等) を **20%以上の差で引き離している**。

### IgakuQA (2018-2022、5年合算) — No-Img

| Entry | No-Img Score | No-Img Acc. |
|---|---|---|
| **GLM-5.1 (本検証)** | **1742/1864 (93.45%)** | **1368/1471 (93.00%)** |

(原リポジトリ jungokasai/IgakuQA は 2023年以降の活発なリーダーボード更新なし。比較対象は別途調査)

### JMED-LLM (5タスク中3完了)

公式リーダーボード形式: `kappa(accuracy)`、CRADE/JCSTS は線形重み付き κ。

| Entry | jmmlu_med | crade | rrtnm | smdis | jcsts | Average |
|---|---|---|---|---|---|---|
| **GLM-5.1 (本検証、進行中)** | **0.89(0.92)** | **0.64(0.81)** | **0.89(0.92)** | (実行中) | (実行中) | (確定待ち) |
| gpt-4o-2024-08-06 | 0.82(0.87) | 0.54(0.53) | 0.85(0.90) | 0.76(0.88) | 0.60(0.48) | 0.61(0.53)\* |
| gpt-4o-mini-2024-07-18 | 0.77(0.83) | 0.21(0.37) | 0.58(0.71) | 0.56(0.78) | 0.57(0.51) | 0.52(0.48)\* |
| gemma-2-9b-it | 0.52(0.64) | 0.33(0.42) | 0.54(0.68) | 0.62(0.81) | 0.16(0.24) | 0.49(0.46)\* |

\* JMED-LLM 公式 Average は MCQ 5タスク + NER 3タスクの計8タスク平均。本検証は MCQ 5 のみ (NER 未実装)、直接比較不可。

**現時点の3タスクで GPT-4o を全て上回っている**:
- jmmlu_med: +0.07 (κ)
- crade: +0.10 (κ)
- rrtnm: +0.04 (κ)

### llm-jp-eval (短縮版)

| Task | n | Metric | GLM-5.1 |
|---|---:|---|---|
| JCommonsenseQA | 1119 | exact_match | 0.977 |
| JEMHopQA | 120 | exact_match | 0.658 |
| JSQuAD | 4442 | exact_match | 0.812 |
| MGSM-ja | 250 | math_equiv | 0.432 |

(MGSM-ja は数学計算問題、温度0でも揺れあり)

## 速度参考値 (TTAT 中央値、シングルリクエスト)

| Task | TTAT p50 | TTAT p90 | think_tok p50 | answer_tok p50 |
|---|---:|---:|---:|---:|
| jcommonsenseqa | 1.8 s | 4.0 s | 168 | 2 |
| igakuqa119 | 6.6 s | 12.7 s | 585 | 7 |
| igakuqa | 6.6 s | 14.2 s | 598 | 7 |
| jmmlu_med | 5.0 s | 12.7 s | 457 | 7 |
| crade | 8.7 s | 29.3 s | 774 | 7 |
| rrtnm | 7.4 s | 14.7 s | 734 | 7 |

H200x8、EAGLE spec decoding 有効、シングルクライアント。

## 含意

候補1である **GLM-5.1 が、日本語特化FT組や同規模クラスのオープンモデルを既存ベンチで広く上回り、フロンティア閉源モデル(Claude-Sonnet-4、Gemini系下位)に肉薄する水準** を text-only ベンチ (No-Img) で達成。

院内デプロイ候補としての一次資料に十分なシグナルあり。本命の Kimi K2.6 (公式EAGLE3公開後)、比較対象の DeepSeek V3.2、think OFF版で同様にフルラン後、最終比較を行う。

## ステータス

- [x] jcommonsenseqa
- [x] jemhopqa
- [x] jsquad
- [x] mgsm
- [x] igakuqa (2018-2022、5年合算)
- [x] igakuqa119
- [x] jmmlu_med
- [x] crade
- [x] rrtnm
- [ ] smdis (実行中)
- [ ] jcsts (実行中)

## 備考

### Score と Acc. の違い

| | 計算 |
|---|---|
| **Acc.** (Accuracy) | 正解数 / 問題数。全問同じ重み |
| **Score** | 獲得点 / 満点。**必修問題は3点扱い**(IgakuQA119 の B/E ブロック Q26-50) |

医師国家試験は必修問題が重く(他は1点)、必修には別途足切り(8割以上必須)がある。Score は実質「必修重視の総合点」、Acc. は「素の正答率」。同じ正答数でも必修を多く取りこぼすと **Score だけ大きく下がる**。リーダーボードで両方並ぶのはこのため。

例: Gemini-2.5-Pro Overall は 485/500 (97.00%) / 389/400 (97.25%)。400問中11問を外したが、配点では15点減 → 外した11問のうち必修3点問題が2問・一般1点問題が9問あったと逆算できる(2×3 + 9×1 = 15)。

GLM-5.1 (本検証) は No-Img Score 93.21% < No-Img Acc. 94.61% で、Acc. の方がやや高い = 必修を多めに外している傾向(ただし誤差レベル)。

### なぜ Overall を出していないか

text-only モデル(GLM/Kimi/DeepSeek)は画像問題が解けない。`--include-image` で実行すれば Overall (500点満点・400問) が埋まるが、画像問題は "見えないまま推測" となり ~25% (ランダム相当) しか取れない。Gemini-2.5-Pro 等は vision で画像を実際に解いて Overall 97% を出しているため、同じ列で並べるのはアンフェア。**No-Img 列で比較するのが text-only モデルにとって公正**。

### 評価条件

- 起動 config を git 管理 (`scripts/sglang-glm5.1.sh`)、設定差は明示
- 各モデルは公式推奨設定 + 公開済み高速化(EAGLE等)を入れた "as-released best"。完全公平より実運用想定を優先
- temperature=0、max_tokens=32768。N=1 (MoE は微揺れあるが、5%以上の差なら結論可能)
- 単一クライアント計測(並列スループットは別途)
- 詳細は `docs/evals.md` 参照

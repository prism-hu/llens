# 評価メモ

院内デプロイモデル選定のため、フロンティアOSS LLM の日本語性能を計測する。

- 設計・方針: 本ドキュメント
- 実測結果(Phase ごと、公開LB比較): [`docs/eval_results.md`](./eval_results.md)
- ハーネス使い方: [`evals/README.md`](../evals/README.md)

## ベンチ一覧

| ベンチ | テスト内容 | 形式 | サイズ |
|---|---|---|---|
| **llm-jp-eval** (短縮) | 日本語汎用(常識・QA・数学) | exact_match / char_f1 / 数値一致 | 4タスク (~6K問) |
| **IgakuQA** (2018-2022) | 医師国家試験 5年分 | 配点(問題内蔵 `points`) + accuracy | 2000問 / 2485点 |
| **IgakuQA119** (第119回) | 最新医師国家試験。学習データに含まれにくい新問 | 500点満点(必修3点) / Overall / No-Img | 400問 / 500点 |
| **JMED-LLM** (MCQ 3) | 医療QA・症例ADE判定・読影TNM分類 | `kappa(accuracy)`、CRADEは線形重み付き | 3タスク (~3K行、SMDIS/JCSTS除外 → 末尾の補足参照) |

優先度: **IgakuQA119**(最新・リーク低) > **JMED-LLM**(実務タスク網羅) > llm-jp-eval(日本語汎用底力) > IgakuQA(年次トレンド確認)。

## 簡易スコア (Phase 1 = GLM-5.1 thinking ON、9タスク完了)

| ベンチ | 結果 |
|---|---|
| IgakuQA119 No-Img | **357/383 (93.21%)** Score / **281/297 (94.61%)** Acc |
| IgakuQA 5年合算 No-Img | **1742/1864 (93.45%)** Score / **1368/1471 (93.00%)** Acc |
| JMED-LLM | jmmlu_med 0.89(0.92) / crade 0.64(0.81) / rrtnm 0.89(0.92) |
| JCommonsenseQA | 0.977 |
| JEMHopQA | 0.658 |
| JSQuAD | 0.812 |
| MGSM-ja | 0.432 |

公開リーダーボードとの並列比較・含意・備考は `docs/eval_results.md` 参照。

## 背景

候補モデル: **GLM 5.1 / DeepSeek V3.2 / Kimi K2.6**。いずれも 1Tクラス前後のOSS。

**Kimi K2.6 が本命**(動作確認済み)。ただし公式 EAGLE3 ドラフトが未公開で spec decoding を適用できず、EAGLE有効な GLM 5.1 と並べると不公平になるため、**EAGLE3 公開待ち**で計測順を後ろに置く。

公開ベンチでこれらの **日本語 × 医療** スコアが揃っていない:

- IgakuQA / IgakuQA119 / JMED-LLM の主な公開結果は GPT-4 / Claude / Gemini / 国産ファインチューン (ELYZA-Med, Preferred-MedLLM, Llama3-Preferred-MedSwallow 等) 中心
- 中国系フロンティアOSSは日本側で測るインセンティブが薄く、ホストできる組織も限定的
- H200x8 を持ち実運用前提で動かしている立場で測る価値あり

院内利用前のスクリーニングが第一目的。**副次的に、現状の日本語FT中心リーダーボードに対してフロンティアOSSのスコアを並べて掲載提案できる材料を作る**ことも狙い。各タスクの集計形式は対応する公式リーダーボードと同形式に揃える(IgakuQA/IgakuQA119: 500点満点制、JMED-LLM: linear weighted κ 等)。

## 評価方針: as-released best

完全公平より **実運用想定** を優先する。

- 各モデル公式推奨設定 + 公開済み高速化(EAGLEなど)を入れた状態で比較
- 起動configは `scripts/sglang-*.sh` でgit管理して透明化
- 設定差は明示する(例: Kimi K2.6 は公式 EAGLE3 ドラフト未公開のため spec decoding なし)

## 計測項目

### 速度

- **TTFT** (Time To First Token): 最初のトークン出力まで
- **TTAT** (Time To Answer Token): `</think>` 直後 = 回答開始まで。reasoning時の体感はこっち
- **decode tok/s**: think部 / answer部 を分離計測
- **同時並列での劣化**: 1 / 4 / 8 ユーザー時の TTAT・throughput

### thinking 量

- **reasoning_tokens** 中央値・p90 (per task)
- **reasoning_tokens / answer_tokens 比**
- **accuracy vs reasoning_tokens トレードオフ**: 同精度なら think 短い方が運用上有利

SGLang の `--reasoning-parser` を介して OpenAI互換APIの `reasoning_content` / `content` および `usage.reasoning_tokens` で取得できる。lm-evaluation-harness 等のデフォルト集計には入らないので自前で拾う。

### 精度(機械採点完結、各公式リーダーボードと同形式)

| ベンチ | 内容 | 採点 |
|---|---|---|
| llm-jp-eval 短縮版 | JCommonsenseQA, JEMHopQA, JSQuAD, MGSM-ja | exact_match / char_f1 / mathematical_equivalence |
| IgakuQA (2018-2022) | 医師国家試験 5年分 | 配点(問題内蔵 `points`) + accuracy、Overall/No-Img |
| IgakuQA119 (第119回) | 必修3点/一般1点、計500点満点 | Overall Score / Overall Acc. / No-Img Score / No-Img Acc. |
| JMED-LLM (MCQ 3タスク) | JMMLU-Med, CRADE, RRTNM | `kappa(accuracy)`、CRADE は線形重み付き κ |

#### Score と Acc. の分母

| | 分子 | 分母 |
|---|---|---|
| **Score** | 正解した問題の `points_possible` 合計 | 出題された問題の `points_possible` 合計(配点制) |
| **Acc.** | 正解した問題数 | 出題された問題数(無加重カウント) |

Score は **必修問題が3点扱い**(IgakuQA119 では B/E ブロック Q26-50)なので、必修を落とすと Acc. より Score が大きく下がる。

#### IgakuQA119 (第119回)、ブロック別

| ブロック | 種別 | 問数 | 配点 | No-Img 問数 | No-Img 配点 |
|---|---|---:|---:|---:|---:|
| 119A | 一般 | 75 | 75 | 41 | 41 |
| 119B | 必修 | 50 | 100 | 46 | 90 |
| 119C | 一般 | 75 | 75 | 60 | 60 |
| 119D | 一般 | 75 | 75 | 43 | 43 |
| 119E | 必修 | 50 | 100 | 43 | 85 |
| 119F | 一般 | 75 | 75 | 64 | 64 |
| **計** | | **400** | **500** | **297** | **383** |

- 必修問題 (B/E、計100問/200点): Q1-25 が 1点、**Q26-50 が 3点**
- 一般問題 (A/C/D/F、計300問/300点): 各1点
- A/D ブロックは画像率高め(Aは55%、Dは57%が画像問題)

#### IgakuQA (2018-2022)、回ごと

| 年 | 回 | Overall (問/点) | No-Img (問/点) |
|---|---|---|---|
| 2018 | 第112回 | 400 / 499 | 286 / 362 |
| 2019 | 第113回 | 400 / 496 | 296 / 375 |
| 2020 | 第114回 | 400 / 496 | 287 / 365 |
| 2021 | 第115回 | 400 / 500 | 301 / 383 |
| 2022 | 第116回 | 400 / 494 | 301 / 379 |
| **計** | 5年合計 | **2000 / 2485** | **1471 / 1864** |

`leaderboard_by_year` に年ごとの集計が、`leaderboard` に5年合算が入る。回ごとに必修・一般の数や配点が微妙に違うため Overall は完全な500点ではなく494〜500の幅がある(問題側の `points` フィールドをそのまま採用)。

LLM-as-a-judge は本フェーズでは使わない(機械採点で完結する範囲に限定)。

## フェーズ

| Phase | モデル | thinking | 備考 |
|---|---|---|---|
| 1 | GLM 5.1 | ON | 現行 `scripts/sglang-glm5.1.sh`、EAGLE有効 |
| 2 | DeepSeek V3.2 | ON | spec decoding 適用可否を確認 |
| 3 | GLM 5.1 | OFF | 同重みで `enable_thinking: false`、Phase 1との差分を見る |
| 4 | Kimi K2.6 | ON | **本命**。公式 EAGLE3 ドラフト公開後にフェアな条件で計測 |

## ディレクトリ構成

```
evals/
├── README.md            # 再現手順
├── configs/             # モデル × モード ごとのYAML
├── harness/
│   ├── client.py        # streaming + reasoning_content分離
│   ├── speed.py         # TTFT/TTAT/tok/s/think_tokens
│   └── accuracy.py      # 各タスクrunner
├── tasks/
│   ├── igakuqa/
│   ├── jmed_llm/
│   └── llm_jp_eval_subset/
├── results/<model>-<mode>/
│   ├── speed.json
│   ├── accuracy.json
│   └── meta.json        # config, git sha, 起動コマンド
└── run.sh
```

依存は pyproject の `[dependency-groups]` evals に切る。`uv sync --group evals` で取得。

## 設計上の注意

- **chat template / prompt format** は各モデル公式に従う
- **temperature / top_p** はタスク種別で固定: 知識QA = 0、生成系 = 0.7
- **N=3〜5 中央値**: MoE は温度0でも揺れがある
- **context length** は全モデル統一(128K想定、必要に応じ短縮)
- 起動configをモデル切替時に必ずgit反映
- 評価データのライセンスを `tasks/<name>/LICENSE.md` に明記

## 後続(本ドキュメント範囲外)

- **院内ガイドラインMCQ**: 医師監修で50〜100問、機械採点
- **自院カルテ要約**: 医師による自由記述評価(N=30〜50)
- **長文性能**: Needle-in-a-Haystack JP (64K〜128K)
- **安全性**: PII漏洩・過剰拒否・プロンプトインジェクション

これらは閉域化前後で別途追加。

## 補足: 本評価から除外したタスク

JMED-LLM の以下2タスクは Phase 1 で除外。Phase 2 以降も同様(全フェーズで揃える)。除外しても **個別タスク値は得られないが、JMED-LLM の MCQ 3タスク相対比較は成立**する。

### SMDIS (除外)

- **規模**: 15,360 行(他タスクの一桁多い、JMED-LLM 全体の 67%)
- **試算コスト**: 13.7 s/q × 15,360 = **約 55 時間 / 1モデル**(全Phaseで ~220h)
- **データ性質**: SNS模擬投稿(本物のSNSでもなく架空)から「投稿者が1日以内に X病だったか」を A/B 判定。87.5% が「B」(陰性)で **強くインバランス**、"全部B" 戦略で 87.5% acc 取れる
- **院内利用との乖離**: SNSスタイル日本語で実カルテ・読影レポート・問診と別系統
- **判断**: コスト過大 / 弱インバランス / 院内非関連の三重で除外

### JCSTS (除外)

- **規模**: 3,670 行 / 19.5 s/q × 3,670 = **約 20 時間 / 1モデル**(全Phaseで ~80h)
- **データ性質**: 医療文の意味的類似度判定(6段階 ordinal、線形重み付き κ で評価)
- **院内利用との乖離は小**: RAG/検索系の構築には類似度判定能力が必要
- **判断材料**:
  - 重要度 ★ (低)。類似度判定は他 MCQ で間接的に測れる
  - GLM-5.1 で 19% 進捗時点の acc は 0.349(参考値、kappa 換算で公開LB GPT-4o 0.60 を下回る見込み)
  - 「JMED-LLM 4タスク Average を出したい」という単一目的で ~80h は採算が合わない
- **判断**: 個別タスク値だけ欲しい時は `--task jcsts` で個別実行可能、`--task all` には入れない

両タスクとも `evals/tasks/jmed_llm/run.py` の `ALL_TASKS` リストでコメントアウト済み。**`--task all` を使う限り自動的にスキップ**される。明示すれば実行可能なので将来必要になれば復活可能。

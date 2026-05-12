# 評価進捗・作業計画

各 Phase の進捗・作業計画。**結果数値(精度・速度・公開LB比較)は [`evals/README.md`](../evals/README.md)**、仕様は [`evals/SPEC.md`](../evals/SPEC.md)。

## ステータス概要

| Phase | モデル | thinking | 状況 | 完了日 |
|---|---|---|---|---|
| 1 | GLM-5.1 | ON | **完了** | 2026-04-29 |
| 4 | Kimi K2.6 | ON | 進行中 | 2026-04-30 〜 |
| 2 | DeepSeek V3.2 | ON | 未着手 | - |
| 3 | GLM-5.1 | OFF | 未着手 | - |

Phase 4 を先行(EAGLE3 ドラフト公開待ちが ~1ヶ月見込みのため、待たず先に着手)。EAGLE3 公開後に Kimi K2.6 速度のみ再ラン予定(精度は spec decoding 非依存)。

各 Phase 共通条件:
- temperature=0、max_tokens=32768、N=1
- vision auto-probe あり(text-only モデルは画像問題自動スキップ → No-Img のみ)
- SMDIS / JCSTS は除外(理由は `evals/SPEC.md` 末尾)
- 起動 config は git 管理(`scripts/llm/sglang-*.sh`)

## Phase 1: GLM-5.1 thinking ON (完了)

- 起動: `make run-glm` (`scripts/llm/sglang-glm5.1.sh`、EAGLE spec decoding 有効、TP8、context 131072、FP8)
- 実行: 2026-04-28 15:27 〜 2026-04-29 14:16(~23時間、9タスク完走)
- vision_used: false(text-only モデル → 画像問題は auto-skip)

**観察**: IgakuQA119 No-Img Acc 281/297 (94.61%) が Claude-Sonnet-4 と同点。JMED-LLM MCQ 3タスクは GPT-4o を上回る κ。詳細は `evals/README.md`。

## Phase 4: Kimi K2.6 thinking ON (進行中、2026-04-30 〜)

- 起動: `make run-kimi` (`scripts/llm/sglang-kimi-k2.6.sh`、spec decoding 無し、TP8、context 131072、INT4 QAT)
- vision auto-probe **OK**(MoonViT 内蔵 → IgakuQA119 Overall 列が埋まった)
- 完了: jcommonsenseqa, jemhopqa, jsquad, mgsm, **igakuqa119**(計5タスク)
- 残: igakuqa, jmmlu_med, crade, rrtnm

**観察**(完了タスクのみ):
- MGSM-ja: Kimi 0.904 vs GLM 0.432
- jcommonsenseqa: Kimi 0.979 vs GLM 0.977(誤差)
- jsquad exact_match: Kimi 0.806 vs GLM 0.812(誤差)
- jemhopqa exact_match: Kimi 0.617 vs GLM 0.658
- IgakuQA119 Overall: 455/500 (91.00%)、No-Img: 346/383 (90.34%)
- IgakuQA119 No-Img Acc は Kimi 91.58% < GLM 94.61%
- 速度: TTAT p50 が GLM-5.1 の約2倍、decode tok/s 中央値 ~78 (GLM ~95)。EAGLE3 ドラフト未公開のため spec decoding 無し

## Phase 2: DeepSeek V3.2 thinking ON (未着手)

- 起動予定: `make run-ds3` (`scripts/llm/sglang-deepseek-v3.2.sh`)
- spec decoding (MTP) 適用可否を要確認

## Phase 3: GLM-5.1 thinking OFF (未着手)

- Phase 1 と同重み、`--no-think` (`enable_thinking: false`) で Phase 1 との差分計測
- 主目的: thinking が精度・速度にどれだけ寄与しているかの定量化

## ハーネス変種: igakuqa119_official

`tasks/igakuqa119/run.py --official` で **naoto-iwase/IgakuQA119 公式 `src/llm_solver.py` と同じ system prompt + `answer:` 行形式** に切替可能。出力は `igakuqa119_official.json`(既存 `igakuqa119.json` と並列保存)。

差分:
- system prompt 付与(persona「優秀で論理的な医療アシスタント」+ 「2つ選べ」等の詳細ルール)
- 画像問題に「has_image=True は参考情報」の明示
- 出力形式 `answer: X` 行 + confidence + explanation
- 抽出は `answer:` 行を最優先、フォールバックで `<answer>` タグ

`run_phase.sh` は `--official` フラグを igakuqa119 だけに転送(`--no-vision` と同じルーティング)。`summarize.py` の TASK_ORDER に追加済みで、leaderboard rows セクションに `igakuqa119` と `igakuqa119_official` が並列表示される。

公式LBと apples-to-apples 比較する時に使用。デフォルト(--official なし)は変更せず、Phase 1/4 の既存 `igakuqa119.json` は引き続き有効。

## 残タスク・次のアクション(優先順位順)

1. **Phase 4 完走待ち**(残り4タスク: igakuqa, jmmlu_med, crade, rrtnm)
2. **Phase 2 着手**(DeepSeek V3.2)
3. **Phase 3 着手**(GLM-5.1 thinking OFF)
4. **クラウドAPI 自前評価**: Claude Opus/Sonnet 4系 / GPT-5系 / Gemini 2.5+ を OpenRouter 経由 (`--base-url https://openrouter.ai/api/v1`) で本ハーネスから評価。数千円〜程度
5. **国産モデルローカル実走**: `llm-jp-3-8x13b-instruct3` / `SIP-jmed-llm-3-8x13b` を TP=1 で実行、apples-to-apples で日本語FT勢の参考値を取得
6. **EAGLE3 公開後**: Kimi K2.6 速度のみ再ラン
7. **JCSTS / SMDIS 補完**(時間に余裕がある時): 3モデル一括で改めて取得
8. **JMED-LLM NER系**(CRNER/RRNER/NRNER): 採点ロジック実装が必要
9. **並列スループット**: 同時 4/8/16 ユーザー時の TTFT/throughput 劣化(`sglang.bench_serving` で別測)

## 後続(本ドキュメント範囲外)

- 院内ガイドラインMCQ(医師監修50〜100問、機械採点)
- 自院カルテ要約(医師による自由記述評価)
- 長文性能(Needle-in-a-Haystack JP、64K〜128K)
- 安全性(PII漏洩・過剰拒否・プロンプトインジェクション)

これらは閉域化前後で別途検討。

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
- 起動 config は git 管理(`scripts/sglang-*.sh`)

## Phase 1: GLM-5.1 thinking ON (完了)

- 起動: `scripts/sglang-glm5.1.sh`(EAGLE spec decoding 有効、TP8、context 131072、FP8)
- 実行: 2026-04-28 15:27 〜 2026-04-29 14:16(~23時間、9タスク完走)
- vision_used: false(text-only モデル → 画像問題は auto-skip)

**含意**: GLM-5.1 が日本語特化FT組や同規模オープンモデルを既存ベンチで広く上回り、フロンティア閉源モデル(Claude-Sonnet-4、Gemini系下位)に肉薄する水準を No-Img ベンチで達成。次は Kimi K2.6 で **vision 込み Overall 列** を埋めて、frontier 閉源モデルとの直接 Overall 比較。

## Phase 4: Kimi K2.6 thinking ON (進行中、2026-04-30 〜)

- 起動: `scripts/sglang-kimi-k2.6.sh`(spec decoding 無し、TP8、context 131072、INT4 QAT)
- vision auto-probe **OK**(MoonViT 内蔵 → IgakuQA119 Overall 列も初めて埋まる)
- 推定完走時間: ~30-40h(EAGLE3 無し + 1.1T params + 画像問題込みのため Phase 1 より長め)

**暫定観察**(4/9タスク完了時点):
- **MGSM-ja で Kimi が GLM-5.1 を倍以上上回る**(0.90 vs 0.43): 数学推論力が顕著
- jcommonsenseqa はほぼ同点、jsquad / jemhopqa は GLM-5.1 が微優位(誤差レベル)
- 残り5タスク(医療系)が本番、特に **IgakuQA119 で Overall列** が初めて埋まる

EAGLE3 ドラフト公開後に **速度のみ再ラン**(精度は spec decoding に影響されない)。

## Phase 2: DeepSeek V3.2 thinking ON (未着手)

- 起動予定: `scripts/sglang-deepseek-v3.2.sh`
- spec decoding (MTP) 適用可否を要確認

## Phase 3: GLM-5.1 thinking OFF (未着手)

- Phase 1 と同重み、`--no-think` (`enable_thinking: false`) で Phase 1 との差分計測
- 主目的: thinking が精度・速度にどれだけ寄与しているかの定量化

## 残タスク・次のアクション(優先順位順)

1. **Phase 4 完走待ち**(残り5タスク、特に igakuqa119 で Overall列を埋める)
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

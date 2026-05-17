#!/usr/bin/env bash
set -euo pipefail

# EAGLE3 + Kimi K2.6 (MLA) で long context が MLA chunked_kv_core 経路に分岐すると、
# その中の MHA sub-call (flashattention_backend.py:771) で
#   assert not get_global_server_args().disable_chunked_prefix_cache
# を踏んで落ちる SGLang 0.5.10 のバグ。
# - --attention-backend flashmla: draft (Llama 系 EAGLE3) の init で kv_lora_rank
#   属性を要求して別 crash
# - --attention-backend fa3: 内部的に同じ flashattention_backend を経由するため
#   同じ assert を踏む (実測でハーフコンテキスト級で再現)
# 残る回避策として dispatcher が chunked_prefix 経路を選ばないように明示。
export SGLANG_ENABLE_SPEC_V2=1

exec uv run sglang serve \
  --model-path ./models/Kimi-K2.6 \
  --tp 8 \
  --disable-chunked-prefix-cache \
  --mem-fraction-static 0.9 \
  --context-length 262144 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 16 \
  --trust-remote-code \
  --speculative-algorithm EAGLE3 \
  --speculative-draft-model-path ./models/Kimi-K2.6-eagle3 \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --reasoning-parser kimi_k2 \
  --tool-call-parser kimi_k2 \
  --served-model-name kimi-k2.6 \
  --enable-metrics \
  --host 0.0.0.0 \
  --port 8000

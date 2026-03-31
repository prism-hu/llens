#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/DeepSeek-V3.2 \
  --tp 8 \
  --dp 8 \
  --enable-dp-attention \
  --mem-fraction-static 0.85 \
  --context-length 98304 \
  --chunked-prefill-size 16384 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 8 \
  --reasoning-parser deepseek-v3 \
  --tool-call-parser deepseekv32 \
  --speculative-algorithm EAGLE \
  --speculative-num-steps 1 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 2 \
  --served-model-name deepseek-v3.2 \
  --host 0.0.0.0 \
  --port 8000

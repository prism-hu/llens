#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/DeepSeek-V3.2 \
  --tp 8 \
  --dp 8 \
  --enable-dp-attention \
  --mem-fraction-static 0.90 \
  --context-length 131072 \
  --reasoning-parser deepseek-v3 \
  --tool-call-parser deepseekv32 \
  --speculative-algo EAGLE \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --served-model-name deepseek-v3.2 \
  --host 0.0.0.0 \
  --port 8000

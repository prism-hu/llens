#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/Qwen3.5-397B-A17B-FP8 \
  --tp 8 \
  --dp 8 \
  --enable-dp-attention \
  --mem-fraction-static 0.90 \
  --context-length 200000 \
  --chunked-prefill-size 16384 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 8 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --speculative-algo NEXTN \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --served-model-name qwen3.5 \
  --enable-metrics \
  --host 0.0.0.0 \
  --port 8000

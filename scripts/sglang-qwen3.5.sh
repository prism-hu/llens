#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/Qwen3.5-397B-A17B-FP8 \
  --tp 8 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --speculative-algo NEXTN \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --mem-fraction-static 0.90 \
  --context-length 262144 \
  --served-model-name qwen3.5 \
  --host 0.0.0.0 \
  --port 8000

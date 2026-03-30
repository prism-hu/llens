#!/usr/bin/env bash
set -euo pipefail

exec uv run vllm serve ./models/GLM-5-FP8 \
  --tensor-parallel-size 8 \
  --gpu-memory-utilization 0.93 \
  --max-model-len 200000 \
  --kv-cache-dtype fp8 \
  --max-num-batched-tokens 4096 \
  --speculative-config.method mtp \
  --speculative-config.num_speculative_tokens 1 \
  --enable-prefix-caching \
  --tool-call-parser glm45 \
  --reasoning-parser glm45 \
  --enable-auto-tool-choice \
  --served-model-name glm-5 \
  --host 0.0.0.0 \
  --port 8000

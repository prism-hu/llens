#!/usr/bin/env bash
set -euo pipefail

exec uv run vllm serve ./models/GLM-5-FP8 \
  --tensor-parallel-size 8 \
  --gpu-memory-utilization 0.93 \
  --max-model-len 200000 \
  --kv-cache-dtype fp8 \
  --max-num-batched-tokens 4096 \
  --served-model-name glm-5 \
  --host 0.0.0.0 \
  --port 8000

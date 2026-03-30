#!/usr/bin/env bash
set -euo pipefail

exec uv run vllm serve ./models/DeepSeek-V3.2 \
  --tensor-parallel-size 8 \
  --gpu-memory-utilization 0.93 \
  --max-model-len 65536 \
  --kv-cache-dtype fp8 \
  --max-num-batched-tokens 4096 \
  --enable-prefix-caching \
  --tokenizer-mode deepseek_v32 \
  --tool-call-parser deepseek_v32 \
  --reasoning-parser deepseek_v3 \
  --enable-auto-tool-choice \
  --served-model-name deepseek-v3.2 \
  --host 0.0.0.0 \
  --port 8000

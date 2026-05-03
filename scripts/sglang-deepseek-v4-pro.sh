#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/DeepSeek-V4-Pro \
  --tp 8 \
  --mem-fraction-static 0.9 \
  --context-length 131072 \
  --chunked-prefill-size 16384 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 8 \
  --cuda-graph-max-bs 8 \
  --reasoning-parser deepseek-v3 \
  --tool-call-parser deepseekv32 \
  --trust-remote-code \
  --served-model-name deepseek-v4-pro \
  --enable-metrics \
  --host 0.0.0.0 \
  --port 8000

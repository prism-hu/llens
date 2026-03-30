#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/DeepSeek-V3.2 \
  --tp 8 \
  --mem-fraction-static 0.90 \
  --context-length 65536 \
  --served-model-name deepseek-v3.2 \
  --host 0.0.0.0 \
  --port 8000

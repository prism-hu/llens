#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/GLM-5-FP8 \
  --tp 8 \
  --mem-fraction-static 0.90 \
  --context-length 200000 \
  --served-model-name glm-5 \
  --host 0.0.0.0 \
  --port 8000

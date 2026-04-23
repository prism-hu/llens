#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/Kimi-K2.6 \
  --tp 8 \
  --mem-fraction-static 0.9 \
  --context-length 131072 \
  --chunked-prefill-size 16384 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 16 \
  --trust-remote-code \
  --reasoning-parser kimi_k2 \
  --tool-call-parser kimi_k2 \
  --served-model-name kimi-k2.6 \
  --enable-metrics \
  --host 0.0.0.0 \
  --port 8000

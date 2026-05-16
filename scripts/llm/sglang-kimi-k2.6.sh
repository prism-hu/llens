#!/usr/bin/env bash
set -euo pipefail

exec uv run sglang serve \
  --model-path ./models/Kimi-K2.6 \
  --tp 8 \
  --mem-fraction-static 0.9 \
  --context-length 262144 \
  --chunked-prefill-size 16384 \
  --schedule-conservativeness 1.5 \
  --max-running-requests 16 \
  --trust-remote-code \
  --speculative-algorithm EAGLE3 \
  --speculative-draft-model-path ./models/Kimi-K2.6-eagle3 \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --reasoning-parser kimi_k2 \
  --tool-call-parser kimi_k2 \
  --served-model-name kimi-k2.6 \
  --enable-metrics \
  --host 0.0.0.0 \
  --port 8000

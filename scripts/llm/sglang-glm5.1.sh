#!/usr/bin/env bash

set -euo pipefail

export SGLANG_ENABLE_SPEC_V2=1

exec uv run sglang serve \
  --model-path ./models/GLM-5.1-FP8 \
  --tp 8 \
  --mem-fraction-static 0.85 \
  --context-length 131072 \
  --chunked-prefill-size 16384 \
  --reasoning-parser glm45 \
  --tool-call-parser glm47 \
  --speculative-algorithm EAGLE \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --served-model-name glm-5.1 \
  --enable-metrics \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 8000

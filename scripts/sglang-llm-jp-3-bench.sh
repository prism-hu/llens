#!/usr/bin/env bash
# llm-jp-3-8x13b 系(ベンチマーク比較用)。
# Usage:   ./scripts/sglang-llm-jp-3-bench.sh {instruct3|sip-jmed}
# Env:     CUDA_VISIBLE_DEVICES (default "0,1")  PORT (default 8000)
#
# 同時並列で2モデル走らせる例(GPU 0-1 と 2-3 に分ける):
#   CUDA_VISIBLE_DEVICES=0,1 PORT=8000 ./scripts/sglang-llm-jp-3-bench.sh instruct3 &
#   CUDA_VISIBLE_DEVICES=2,3 PORT=8001 ./scripts/sglang-llm-jp-3-bench.sh sip-jmed  &
#   wait
set -euo pipefail

case "${1:-}" in
  instruct3)
    MODEL_PATH=./models/llm-jp-3-8x13b-instruct3
    SERVED_NAME=llm-jp-3-8x13b-instruct3
    ;;
  sip-jmed)
    MODEL_PATH=./models/SIP-jmed-llm-3-8x13b-OP-32k-R0.1
    SERVED_NAME=sip-jmed-llm-3-8x13b
    ;;
  *)
    echo "usage: $0 {instruct3|sip-jmed}" >&2
    exit 1
    ;;
esac

GPUS="${CUDA_VISIBLE_DEVICES:-0,1}"
TP=$(echo "$GPUS" | tr ',' '\n' | grep -c .)
PORT="${PORT:-8000}"

exec env CUDA_VISIBLE_DEVICES="$GPUS" uv run sglang serve \
  --model-path "$MODEL_PATH" \
  --tp "$TP" \
  --mem-fraction-static 0.85 \
  --context-length 32768 \
  --served-model-name "$SERVED_NAME" \
  --enable-metrics \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port "$PORT"

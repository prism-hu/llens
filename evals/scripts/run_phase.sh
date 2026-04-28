#!/usr/bin/env bash
# Run all evaluation tasks for a single (model, mode) combination.
#
# Usage:
#   evals/scripts/run_phase.sh <model> <output_subdir> [extra args...]
#
# Examples:
#   evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-on
#   evals/scripts/run_phase.sh glm-5.1 glm-5.1-think-off --no-think
#   evals/scripts/run_phase.sh glm-5.1 _smoke --limit 5
#
# Extra args (e.g., --no-think, --limit N) are forwarded to every task runner.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <model> <output_subdir> [extra args...]" >&2
  exit 1
fi

MODEL="$1"
SUBDIR="$2"
shift 2
EXTRA=("$@")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/evals/results/$SUBDIR"
mkdir -p "$OUT"

run() {
  local label="$1"; shift
  echo
  echo "============================================================"
  echo "[$label] -> $OUT"
  echo "============================================================"
  uv run --group evals python "$@" --model "$MODEL" --output-dir "$OUT" "${EXTRA[@]}"
}

cd "$ROOT"

run llm-jp-eval-subset -m evals.tasks.llm_jp_eval_subset.run --task all
run igakuqa            -m evals.tasks.igakuqa.run
run igakuqa119         -m evals.tasks.igakuqa119.run
run jmed-llm           -m evals.tasks.jmed_llm.run --task all

echo
echo "[done] phase complete -> $OUT"

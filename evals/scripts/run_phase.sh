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

# Vision capability is auto-probed inside igakuqa119 / jmle2026 (sends one test
# image at startup; falls back to text-only if rejected).
# --no-vision は両 vision タスクに転送、--official は igakuqa119 のみ。
COMMON_ARGS=()
VISION_ARGS=()
IGAKUQA119_ONLY_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --no-vision) VISION_ARGS+=("$arg") ;;
    --official) IGAKUQA119_ONLY_ARGS+=("$arg") ;;
    *) COMMON_ARGS+=("$arg") ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/evals/results/$SUBDIR"
mkdir -p "$OUT"

run() {
  local label="$1"; shift
  echo
  echo "============================================================"
  echo "[$label] -> $OUT"
  echo "============================================================"
  uv run --group evals python "$@" --model "$MODEL" --output-dir "$OUT"
}

cd "$ROOT"

run llm-jp-eval-subset -m evals.tasks.llm_jp_eval_subset.run --task all "${COMMON_ARGS[@]}"
run igakuqa            -m evals.tasks.igakuqa.run            "${COMMON_ARGS[@]}"
run igakuqa119         -m evals.tasks.igakuqa119.run         "${COMMON_ARGS[@]}" "${VISION_ARGS[@]}" "${IGAKUQA119_ONLY_ARGS[@]}"
run jmle2026           -m evals.tasks.jmle2026.run           "${COMMON_ARGS[@]}" "${VISION_ARGS[@]}"
run jmed-llm           -m evals.tasks.jmed_llm.run --task all "${COMMON_ARGS[@]}"

echo
echo "[done] phase complete -> $OUT"

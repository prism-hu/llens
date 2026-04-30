#!/usr/bin/env bash
# Fetch external evaluation datasets into evals/datasets/<name>/.
# Idempotent: re-running skips repos that are already cloned.
#
# Each repo is external; its own LICENSE applies (see datasets/<name>/).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/datasets"
mkdir -p "$DATA"

clone_or_skip() {
  local url="$1" target="$2"
  if [[ -d "$DATA/$target/.git" ]]; then
    echo "[skip]  $target already present"
    return
  fi
  echo "[clone] $url -> datasets/$target"
  git clone --depth 1 "$url" "$DATA/$target"
}

clone_or_skip https://github.com/jungokasai/IgakuQA.git           igakuqa
clone_or_skip https://github.com/naoto-iwase/IgakuQA119.git       igakuqa119
clone_or_skip https://github.com/naoto-iwase/JMLE2026-Bench.git   jmle2026
clone_or_skip https://github.com/sociocom/JMED-LLM.git            jmed_llm
clone_or_skip https://github.com/llm-jp/llm-jp-eval.git           llm_jp_eval

cat <<'NOTE'

------------------------------------------------------------
Datasets cloned under evals/datasets/.

llm-jp-eval requires an additional preprocessing step to
materialize task JSONs. Run separately:

  cd evals/datasets/llm_jp_eval
  uv sync
  uv run python scripts/preprocess_dataset.py \
    --dataset-name jcommonsenseqa,jemhopqa,jsquad,mgsm \
    --output-dir ./dataset

Some llm-jp-eval tasks pull from HuggingFace and may require
`huggingface-cli login` first.
------------------------------------------------------------
NOTE

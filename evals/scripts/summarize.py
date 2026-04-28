"""Summarize result JSONs in a directory into a Markdown table.

Walks every *.json file produced by the task runners and emits one row per
task with the headline metric, latency percentiles, and token usage.

Usage:
  uv run --group evals python evals/scripts/summarize.py results/glm-5.1-think-on
  uv run --group evals python evals/scripts/summarize.py results/glm-5.1-think-on \\
    --compare results/glm-5.1-think-off
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PRIMARY_METRIC = {
    "jcommonsenseqa": "exact_match",
    "jemhopqa": "exact_match",
    "jsquad": "exact_match",
    "mgsm": "mathematical_equivalence",
    "igakuqa": "accuracy",
    "igakuqa119": "accuracy",
    "jmmlu_med": "accuracy",
    "crade": "accuracy",
    "rrtnm": "accuracy",
    "smdis": "accuracy",
    "jcsts": "accuracy",
}

TASK_ORDER = list(PRIMARY_METRIC.keys())


def load_dir(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        task = data.get("task")
        if task:
            out[task] = data
    return out


def fmt(x: float | None, *, decimals: int = 0) -> str:
    if x is None:
        return "-"
    return f"{x:.{decimals}f}"


def get_metric(d: dict[str, Any]) -> float | None:
    metrics = d.get("metrics", {})
    primary = PRIMARY_METRIC.get(d["task"])
    if primary and primary in metrics:
        return metrics[primary]
    if metrics:
        return next(iter(metrics.values()))
    return None


def render_table(results: dict[str, dict[str, Any]], label: str) -> str:
    header = f"## {label}\n\n"
    cols = [
        "task", "n", "metric", "score",
        "ttat_p50 (ms)", "ttat_p90 (ms)",
        "think_p50", "answer_p50",
    ]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for task in TASK_ORDER:
        if task not in results:
            continue
        d = results[task]
        n = d.get("n", "-")
        primary = PRIMARY_METRIC.get(task, "?")
        score = get_metric(d)
        timing = d.get("timing", {}) or {}
        tokens = d.get("tokens", {}) or {}
        ttat = timing.get("ttat_ms") or {}
        think = tokens.get("reasoning_tokens") or {}
        ans = tokens.get("answer_tokens") or {}
        lines.append("| " + " | ".join([
            task,
            str(n),
            primary,
            f"{score:.3f}" if score is not None else "-",
            fmt(ttat.get("median")),
            fmt(ttat.get("p90")),
            fmt(think.get("median")),
            fmt(ans.get("median")),
        ]) + " |")
    return header + "\n".join(lines) + "\n"


def render_compare(
    base: dict[str, dict[str, Any]],
    other: dict[str, dict[str, Any]],
    base_label: str,
    other_label: str,
) -> str:
    header = f"## diff: {other_label} - {base_label}\n\n"
    cols = ["task", f"score ({base_label})", f"score ({other_label})", "Δscore",
            f"ttat_p50 ({base_label})", f"ttat_p50 ({other_label})", "Δttat_p50",
            f"think_p50 ({base_label})", f"think_p50 ({other_label})"]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for task in TASK_ORDER:
        if task not in base or task not in other:
            continue
        b = base[task]
        o = other[task]
        bs = get_metric(b)
        os_ = get_metric(o)
        b_ttat = ((b.get("timing") or {}).get("ttat_ms") or {}).get("median")
        o_ttat = ((o.get("timing") or {}).get("ttat_ms") or {}).get("median")
        b_think = ((b.get("tokens") or {}).get("reasoning_tokens") or {}).get("median")
        o_think = ((o.get("tokens") or {}).get("reasoning_tokens") or {}).get("median")
        d_score = (os_ - bs) if (bs is not None and os_ is not None) else None
        d_ttat = (o_ttat - b_ttat) if (b_ttat is not None and o_ttat is not None) else None
        lines.append("| " + " | ".join([
            task,
            f"{bs:.3f}" if bs is not None else "-",
            f"{os_:.3f}" if os_ is not None else "-",
            (f"{d_score:+.3f}" if d_score is not None else "-"),
            fmt(b_ttat),
            fmt(o_ttat),
            (f"{d_ttat:+.0f}" if d_ttat is not None else "-"),
            fmt(b_think),
            fmt(o_think),
        ]) + " |")
    return header + "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--compare", type=Path, default=None,
                        help="another results dir for side-by-side comparison")
    args = parser.parse_args()

    base = load_dir(args.input_dir)
    base_label = args.input_dir.name
    print(render_table(base, base_label))

    if args.compare:
        other = load_dir(args.compare)
        other_label = args.compare.name
        print(render_table(other, other_label))
        print(render_compare(base, other, base_label, other_label))
    return 0


if __name__ == "__main__":
    sys.exit(main())

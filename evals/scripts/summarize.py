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
    "igakuqa119_official": "accuracy",
    "jmle2026": "accuracy",
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


def render_leaderboard(results: dict[str, dict[str, Any]], label: str) -> str:
    """Render rows aligned with each benchmark's public leaderboard format."""
    out = [f"## leaderboard rows: {label}\n"]

    # IgakuQA / IgakuQA119: Overall Score | Overall Acc. | No-Img Score | No-Img Acc.
    # Detect whether image questions were included by checking samples; when not,
    # render "-" in Overall columns (text-only model, fair comparison via No-Img).
    for task in ("igakuqa", "igakuqa119", "igakuqa119_official"):
        d = results.get(task)
        if not d or "leaderboard" not in d:
            continue
        lb = d["leaderboard"]
        image_included = any(s.get("has_image") for s in d.get("samples", []))
        out.append(f"### {task} (https://github.com/naoto-iwase/IgakuQA119 style)\n")
        cols = ["Entry", "Overall Score", "Overall Acc.", "No-Img Score", "No-Img Acc."]
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join(["---"] * len(cols)) + "|")
        if image_included:
            overall_score = lb["overall"]["score_str"]
            overall_acc = lb["overall"]["accuracy_str"]
        else:
            overall_score = "-"
            overall_acc = "-"
        out.append("| " + " | ".join([
            f"{label}",
            overall_score,
            overall_acc,
            lb["no_image"]["score_str"],
            lb["no_image"]["accuracy_str"],
        ]) + " |")
        if not image_included:
            out.append("\n(注: text-only モデルで画像問題は未評価のため Overall は `-`。No-Img 列で比較)\n")
        else:
            out.append("")

    # JMLE2026: Overall Score | Overall Acc. | Text-only Score | Text-only Acc.
    # (matches https://github.com/naoto-iwase/JMLE2026-Bench leaderboard table)
    d = results.get("jmle2026")
    if d and "leaderboard" in d:
        lb = d["leaderboard"]
        image_included = any(s.get("has_image") for s in d.get("samples", []))
        out.append("### jmle2026 (https://github.com/naoto-iwase/JMLE2026-Bench style)\n")
        cols = ["Entry", "Overall Score", "Overall Acc.", "Text-only Score", "Text-only Acc."]
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join(["---"] * len(cols)) + "|")
        if image_included:
            overall_score = lb["overall"]["score_str"]
            overall_acc = lb["overall"]["accuracy_str"]
        else:
            overall_score = "-"
            overall_acc = "-"
        out.append("| " + " | ".join([
            f"{label}",
            overall_score,
            overall_acc,
            lb["text_only"]["score_str"],
            lb["text_only"]["accuracy_str"],
        ]) + " |")
        if not image_included:
            out.append("\n(注: text-only モデルで画像問題は未評価のため Overall は `-`。Text-only 列で比較)\n")
        else:
            out.append("")

    # JMED-LLM: kappa(accuracy) per task, plus average (per their README)
    jmed_tasks = ["jmmlu_med", "crade", "rrtnm", "smdis", "jcsts"]
    jmed_present = [t for t in jmed_tasks if t in results and "leaderboard" in results[t]]
    if jmed_present:
        out.append("### JMED-LLM (https://github.com/sociocom/JMED-LLM style)\n")
        cols = ["Entry"] + jmed_present + ["Average"]
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join(["---"] * len(cols)) + "|")
        kappas, accs = [], []
        cells = [label]
        for t in jmed_present:
            lb = results[t]["leaderboard"]
            cells.append(lb["display"])
            kappas.append(lb["kappa"])
            accs.append(lb["accuracy"])
        if kappas:
            avg = f"{sum(kappas) / len(kappas):.2f}({sum(accs) / len(accs):.2f})"
        else:
            avg = "-"
        cells.append(avg)
        out.append("| " + " | ".join(cells) + " |\n")
        out.append("(注: 上は MCQ 5タスクのみ。NER 系 (CRNER/RRNER/NRNER) は未実装)\n")

    return "\n".join(out) + "\n"


def render_timeline(results: dict[str, dict[str, Any]], label: str) -> str:
    header = f"## timeline: {label}\n\n"
    cols = ["task", "started_at", "ended_at", "duration"]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    rows = []
    for task in TASK_ORDER:
        if task not in results:
            continue
        d = results[task]
        rows.append((d.get("started_epoch_ms") or 0, task, d))
    rows.sort()
    for _, task, d in rows:
        dur = d.get("duration_sec")
        if dur is None:
            dur_s = "-"
        elif dur >= 3600:
            dur_s = f"{dur / 3600:.2f}h"
        elif dur >= 60:
            dur_s = f"{dur / 60:.1f}m"
        else:
            dur_s = f"{dur:.0f}s"
        lines.append("| " + " | ".join([
            task,
            d.get("started_at", "-"),
            d.get("ended_at", "-"),
            dur_s,
        ]) + " |")
    return header + "\n".join(lines) + "\n"


def per_sample_decode_tok_s(s: dict[str, Any]) -> float | None:
    """Decode rate over the whole generation (think + answer):
    (reasoning_tokens + answer_tokens) / (total_time - ttft).
    Returns None when timing/tokens are missing.
    """
    ttft = s.get("ttft_ms")
    total = s.get("total_time_ms")
    rt = (s.get("reasoning_tokens") or 0)
    at = (s.get("answer_tokens") or 0)
    n_tok = rt + at
    if ttft is None or total is None or total <= ttft or n_tok == 0:
        return None
    return n_tok / ((total - ttft) / 1000)


def decode_tok_s_stats(samples: list[dict[str, Any]]) -> dict[str, float | None]:
    rates = sorted(r for r in (per_sample_decode_tok_s(s) for s in samples) if r is not None)
    if not rates:
        return {"median": None, "p90": None}
    return {
        "median": rates[len(rates) // 2],
        "p90": rates[min(int(len(rates) * 0.9), len(rates) - 1)],
    }


def render_table(results: dict[str, dict[str, Any]], label: str) -> str:
    header = f"## {label}\n\n"
    cols = [
        "task", "n", "metric", "score",
        "tok/s p50", "ttat p50 (ms)", "ttat p90 (ms)",
        "think p50", "answer p50",
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
        rate = decode_tok_s_stats(d.get("samples", []))
        lines.append("| " + " | ".join([
            task,
            str(n),
            primary,
            f"{score:.3f}" if score is not None else "-",
            f"{rate['median']:.1f}" if rate["median"] is not None else "-",
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
    print(render_leaderboard(base, base_label))
    print(render_timeline(base, base_label))

    if args.compare:
        other = load_dir(args.compare)
        other_label = args.compare.name
        print(render_table(other, other_label))
        print(render_leaderboard(other, other_label))
        print(render_timeline(other, other_label))
        print(render_compare(base, other, base_label, other_label))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Runner for JMED-LLM (sociocom/JMED-LLM) — 5 MCQ tasks.

Covers JMMLU-Med, CRADE, RRTNM, SMDIS, JCSTS. Common CSV layout:
`tag, question, optionA, optionB[, optionC, ...], answer` where answer is a
single uppercase letter (A..F). NER subtasks (CRNER/RRNER/NRNER) are not
implemented.

Note: CRADE / JCSTS are originally scored by linearly weighted Cohen's kappa
in the JMED-LLM leaderboard. We save raw pred/gold per sample so that kappa
can be computed offline; the headline metric reported here is accuracy.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

from evals.harness.client import GenerationResult, generate

DATASET_ROOT = Path(__file__).resolve().parents[2] / "datasets" / "jmed_llm" / "datasets" / "all"

TASKS = {
    "jmmlu_med": "JMMLU-Med",
    "crade": "CRADE",
    "rrtnm": "RRTNM",
    "smdis": "SMDIS",
    "jcsts": "JCSTS",
}

# Linear-weighted κ for ordinal labels (per JMED-LLM official leaderboard).
# For RRTNM the staging axes are also ordinal. JMMLU-Med / SMDIS are nominal.
LINEAR_WEIGHTED_TASKS = {"crade", "jcsts"}

# Label order for ordinal tasks. Treated as the ordinal axis when computing
# linear-weighted κ. Matches the order options are listed in the source CSV.
ORDINAL_LABELS = {
    "crade": ["A", "B", "C", "D"],
    "jcsts": ["A", "B", "C", "D", "E", "F"],
}

OPTION_LETTERS = "ABCDEF"
EXTRACT_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)

INSTRUCTION = (
    "次の問題について、提示された選択肢から最も適切なものを1つ選び、"
    "選択肢の記号({letters})だけを <answer></answer> タグで囲んで答えてください "
    "(例: <answer>A</answer>)。"
)


def cohen_kappa(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
    *,
    weights: str = "none",
) -> float:
    """Compute Cohen's κ. weights='linear' applies linearly-weighted κ for
    ordinal labels (per JMED-LLM leaderboard convention for CRADE/JCSTS).
    Out-of-vocabulary predictions are kept and treated as a distinct miss
    (mapped to a synthetic OOV bucket — they reduce κ as expected).
    """
    if not y_true:
        return 0.0
    # Map labels to indices; out-of-vocab predictions get index n_labels (OOV)
    idx_of = {l: i for i, l in enumerate(labels)}
    n = len(labels)
    n_with_oov = n + 1
    cm = [[0] * n_with_oov for _ in range(n_with_oov)]
    for t, p in zip(y_true, y_pred):
        ti = idx_of.get(t, n)
        pi = idx_of.get(p, n)
        cm[ti][pi] += 1

    total = sum(sum(row) for row in cm)
    if total == 0:
        return 0.0
    # Weights: linear for ordinal axis (only over the n real labels).
    # Treat OOV as the most distant class (weight = 1) for both linear and unweighted.
    def w(i: int, j: int) -> float:
        if i == j:
            return 0.0
        if i == n or j == n:
            return 1.0
        if weights == "linear":
            return abs(i - j) / max(n - 1, 1)
        return 1.0  # unweighted: any disagreement counts equally

    row_marg = [sum(cm[i]) / total for i in range(n_with_oov)]
    col_marg = [sum(cm[i][j] for i in range(n_with_oov)) / total for j in range(n_with_oov)]

    obs_disagree = 0.0
    exp_disagree = 0.0
    for i in range(n_with_oov):
        for j in range(n_with_oov):
            wij = w(i, j)
            obs_disagree += wij * (cm[i][j] / total)
            exp_disagree += wij * (row_marg[i] * col_marg[j])
    if exp_disagree == 0:
        return 0.0
    return 1.0 - obs_disagree / exp_disagree


@dataclass
class SampleResult:
    idx: int
    tag: str
    gold: str
    extracted: str
    raw: str
    correct: bool
    ttft_ms: float | None
    ttat_ms: float | None
    total_time_ms: float | None
    reasoning_tokens: int
    answer_tokens: int
    finish_reason: str | None


def load_rows(task: str) -> list[dict[str, str]]:
    name = TASKS[task]
    with (DATASET_ROOT / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def available_letters(row: dict[str, str]) -> list[str]:
    return [L for L in OPTION_LETTERS if row.get(f"option{L}")]


def build_messages(row: dict[str, str]) -> list[dict[str, Any]]:
    letters = available_letters(row)
    options = "\n".join(f"{L}. {row[f'option{L}']}" for L in letters)
    instruction = INSTRUCTION.format(letters="/".join(letters))
    user = f"{instruction}\n\n問題: {row['question']}\n\n選択肢:\n{options}"
    return [{"role": "user", "content": user}]


def extract_letter(text: str, valid: list[str]) -> str:
    m = EXTRACT_RE.search(text)
    inside = (m.group(1) if m else text).upper()
    for c in inside:
        if c in valid:
            return c
    return ""


def run_task(
    task: str,
    *,
    base_url: str,
    model: str,
    output_dir: Path,
    limit: int | None,
    no_think: bool,
    max_tokens: int,
    temperature: float,
) -> Path:
    rows = load_rows(task)
    if limit:
        rows = rows[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    correct_count = 0
    start_dt = datetime.datetime.now().astimezone()

    pbar = tqdm(rows, desc=task, unit="q")
    for i, row in enumerate(pbar):
        valid = available_letters(row)
        msgs = build_messages(row)
        gen: GenerationResult = generate(
            base_url,
            model,
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        extracted = extract_letter(gen.content, valid)
        gold = row["answer"].strip().upper()
        correct = extracted == gold
        if correct:
            correct_count += 1
        results.append(
            SampleResult(
                idx=i,
                tag=row.get("tag", ""),
                gold=gold,
                extracted=extracted,
                raw=gen.content,
                correct=correct,
                ttft_ms=gen.ttft_ms,
                ttat_ms=gen.ttat_ms,
                total_time_ms=gen.total_time_ms,
                reasoning_tokens=gen.reasoning_tokens,
                answer_tokens=gen.answer_tokens,
                finish_reason=gen.finish_reason,
            )
        )
        pbar.set_postfix(acc=f"{correct_count / len(results):.3f}")

    end_dt = datetime.datetime.now().astimezone()
    aggregate = aggregate_results(task, model, no_think, results, start_dt, end_dt)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{task}.json"
    out_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return out_path


def percentile(xs: list[float | None], p: float) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def aggregate_results(
    task: str,
    model: str,
    no_think: bool,
    samples: list[SampleResult],
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
) -> dict[str, Any]:
    def stat(field: str) -> dict[str, float | None]:
        vals = [getattr(s, field) for s in samples]
        vals = [v for v in vals if v is not None]
        return {
            "median": statistics.median(vals) if vals else None,
            "p90": percentile(vals, 0.9),
            "max": max(vals) if vals else None,
        }

    by_tag: dict[str, list[bool]] = {}
    for s in samples:
        if s.tag:
            by_tag.setdefault(s.tag, []).append(s.correct)

    # JMED-LLM leaderboard: κ(accuracy). Linear-weighted κ for CRADE/JCSTS, unweighted otherwise.
    weights = "linear" if task in LINEAR_WEIGHTED_TASKS else "none"
    labels = ORDINAL_LABELS.get(task) or sorted({s.gold for s in samples})
    accuracy = sum(s.correct for s in samples) / len(samples) if samples else 0.0
    kappa = cohen_kappa(
        [s.gold for s in samples],
        [s.extracted for s in samples],
        labels,
        weights=weights,
    )

    return {
        "task": task,
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "n": len(samples),
        "metrics": {
            "accuracy": accuracy,
            "cohen_kappa": kappa,
            "kappa_weighting": weights,
        },
        "leaderboard": {
            "kappa": kappa,
            "accuracy": accuracy,
            "weighting": weights,
            "display": f"{kappa:.2f}({accuracy:.2f})",
        },
        "accuracy_by_tag": {
            t: {"n": len(v), "accuracy": sum(v) / len(v)}
            for t, v in sorted(by_tag.items())
        },
        "timing": {
            "ttft_ms": stat("ttft_ms"),
            "ttat_ms": stat("ttat_ms"),
            "total_time_ms": stat("total_time_ms"),
        },
        "tokens": {
            "reasoning_tokens": stat("reasoning_tokens"),
            "answer_tokens": stat("answer_tokens"),
        },
        "finish_reasons": _count([s.finish_reason for s in samples]),
        "started_at": start_dt.isoformat(timespec="seconds"),
        "ended_at": end_dt.isoformat(timespec="seconds"),
        "started_epoch_ms": int(start_dt.timestamp() * 1000),
        "ended_epoch_ms": int(end_dt.timestamp() * 1000),
        "duration_sec": round((end_dt - start_dt).total_seconds(), 2),
        "samples": [asdict(s) for s in samples],
    }


def _count(xs: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--task",
        required=True,
        choices=[*TASKS.keys(), "all"],
        help="task to run (jmmlu_med, crade, rrtnm, smdis, jcsts) or 'all'",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None,
                        help="cap rows per task (SMDIS/CRADE/JCSTS are large)")
    parser.add_argument("--no-think", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    tasks = list(TASKS.keys()) if args.task == "all" else [args.task]
    for t in tasks:
        out = run_task(
            t,
            base_url=args.base_url,
            model=args.model,
            output_dir=args.output_dir,
            limit=args.limit,
            no_think=args.no_think,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        print(f"[done] {t} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

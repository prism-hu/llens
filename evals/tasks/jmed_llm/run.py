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
import json
import re
import statistics
import sys
import time
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

OPTION_LETTERS = "ABCDEF"
EXTRACT_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)

INSTRUCTION = (
    "次の問題について、提示された選択肢から最も適切なものを1つ選び、"
    "選択肢の記号({letters})だけを <answer></answer> タグで囲んで答えてください "
    "(例: <answer>A</answer>)。"
)


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

    aggregate = aggregate_results(task, model, no_think, results)
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

    return {
        "task": task,
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "n": len(samples),
        "metrics": {
            "accuracy": sum(s.correct for s in samples) / len(samples) if samples else 0.0,
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
        "samples": [asdict(s) for s in samples],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
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

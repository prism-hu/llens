"""Runner for llm-jp-eval subset (jcommonsenseqa, jemhopqa, jsquad, mgsm).

Reads task JSONs produced by llm-jp-eval `preprocess_dataset.py` and runs them
against an SGLang OpenAI-compatible endpoint, capturing accuracy, timing, and
think-token statistics.
"""

from __future__ import annotations

import argparse
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


DATASET_ROOT = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "llm_jp_eval"
    / "dataset"
    / "datasets"
    / "2.1.3"
    / "evaluation"
    / "test"
)

# (extract regex, hint to append to instruction)
ANSWER_PATTERNS: dict[str, tuple[str, str]] = {
    "choice_only_jp": (
        r"(?s)^\s*([0-9０-９])",
        "選択肢の番号のみで回答してください。",
    ),
    "answer_tags_jp": (
        r"<answer>(.*?)</answer>",
        "<answer></answer>タグで囲んで回答してください。",
    ),
    "latex_boxed_jp": (
        r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
        "最終的な答えを $\\boxed{}$ に入れてください。",
    ),
}


def extract_answer(text: str, pattern_id: str) -> str:
    regex, _ = ANSWER_PATTERNS[pattern_id]
    m = re.search(regex, text, re.DOTALL)
    return ("".join(m.groups()).strip() if m else "").strip()


def char_f1(pred: str, gold: str) -> float:
    if not pred or not gold:
        return 0.0
    p, g = list(pred), list(gold)
    common = sum(min(p.count(c), g.count(c)) for c in set(p))
    if common == 0:
        return 0.0
    precision = common / len(p)
    recall = common / len(g)
    return 2 * precision * recall / (precision + recall)


def math_equiv(pred: str, gold: str) -> float:
    def to_num(s: str) -> float | None:
        s = s.replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            m = re.search(r"-?\d+(?:\.\d+)?", s)
            return float(m.group()) if m else None

    pn, gn = to_num(pred), to_num(gold)
    if pn is None or gn is None:
        return 0.0
    return 1.0 if abs(pn - gn) < 1e-6 else 0.0


METRIC_FNS = {
    "exact_match": lambda p, g: 1.0 if p.strip() == g.strip() else 0.0,
    "char_f1": char_f1,
    "mathematical_equivalence": math_equiv,
}


@dataclass
class SampleResult:
    idx: int
    input: str
    gold: str
    raw: str
    extracted: str
    metrics: dict[str, float]
    ttft_ms: float | None
    ttat_ms: float | None
    total_time_ms: float | None
    reasoning_tokens: int
    answer_tokens: int
    finish_reason: str | None


def build_messages(instruction: str, hint: str, sample_input: str) -> list[dict[str, Any]]:
    user = f"{instruction}\n\n{hint}\n\n{sample_input}"
    return [{"role": "user", "content": user}]


def run_task(
    task_name: str,
    *,
    base_url: str,
    model: str,
    output_dir: Path,
    limit: int | None,
    no_think: bool,
    max_tokens: int,
    temperature: float,
) -> Path:
    src = DATASET_ROOT / f"{task_name}.json"
    if not src.exists():
        raise FileNotFoundError(f"Task data not found: {src} (did you run preprocess_dataset.py?)")
    data = json.loads(src.read_text())

    instruction = data["instruction"]
    metrics = data["metrics"]
    pattern_id = data["answer_pattern_id"]
    if pattern_id not in ANSWER_PATTERNS:
        raise ValueError(f"Unsupported answer_pattern_id={pattern_id} for task {task_name}")
    _, hint = ANSWER_PATTERNS[pattern_id]
    samples = data["samples"]
    if limit:
        samples = samples[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    metric_totals: dict[str, list[float]] = {m: [] for m in metrics}

    pbar = tqdm(samples, desc=f"{task_name}", unit="q")
    for i, sample in enumerate(pbar):
        msgs = build_messages(instruction, hint, sample["input"])
        gen: GenerationResult = generate(
            base_url,
            model,
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        extracted = extract_answer(gen.content, pattern_id)
        gold = sample["output"]
        per_sample_metrics: dict[str, float] = {}
        for m in metrics:
            score = METRIC_FNS[m](extracted, gold)
            per_sample_metrics[m] = score
            metric_totals[m].append(score)

        results.append(
            SampleResult(
                idx=i,
                input=sample["input"],
                gold=gold,
                raw=gen.content,
                extracted=extracted,
                metrics=per_sample_metrics,
                ttft_ms=gen.ttft_ms,
                ttat_ms=gen.ttat_ms,
                total_time_ms=gen.total_time_ms,
                reasoning_tokens=gen.reasoning_tokens,
                answer_tokens=gen.answer_tokens,
                finish_reason=gen.finish_reason,
            )
        )
        pbar.set_postfix({m: f"{statistics.mean(metric_totals[m]):.3f}" for m in metrics})

    aggregate = aggregate_results(task_name, model, no_think, metrics, metric_totals, results)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{task_name}.json"
    out_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return out_path


def percentile(xs: list[float], p: float) -> float | None:
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
    metrics: list[str],
    metric_totals: dict[str, list[float]],
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

    return {
        "task": task,
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "n": len(samples),
        "metrics": {m: statistics.mean(scores) if scores else 0.0 for m, scores in metric_totals.items()},
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
        choices=["jcommonsenseqa", "jemhopqa", "jsquad", "mgsm", "all"],
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="run only first N samples (smoke test)")
    parser.add_argument("--no-think", action="store_true", help="disable thinking mode via chat_template_kwargs")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    tasks = ["jcommonsenseqa", "jemhopqa", "jsquad", "mgsm"] if args.task == "all" else [args.task]
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

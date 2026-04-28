"""Runner for IgakuQA119 (naoto-iwase/IgakuQA119) — 119th medical licensing exam.

400 problems across blocks A-F. Choices come pre-prefixed (e.g. "a. ..."). A
small number of problems (~4) are numeric calculation problems with empty
`choices`; we score those by parsed numeric equality. Image-bearing problems
(has_image=true) are skipped by default.
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

ROOT = Path(__file__).resolve().parents[2] / "datasets" / "igakuqa119"
QUESTIONS_DIR = ROOT / "questions"
ANSWERS_CSV = ROOT / "results" / "correct_answers.csv"

LETTERS = "abcdefghij"
EXTRACT_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)

INSTRUCTION_MCQ = (
    "以下は日本の第119回医師国家試験の問題です。選択肢から正解を選び、"
    "答えだけを <answer></answer> タグで囲んで返してください。"
    "複数の選択肢が正解の場合は記号を連結してください(例: <answer>ac</answer>)。"
)
INSTRUCTION_NUMERIC = (
    "以下は日本の第119回医師国家試験の計算問題です。"
    "解答(数値)だけを <answer></answer> タグで囲んで返してください(例: <answer>42</answer>)。"
)


@dataclass
class SampleResult:
    problem_id: str
    block: str
    is_numeric: bool
    gold: str
    extracted: str
    extracted_set: list[str]
    raw: str
    correct: bool
    ttft_ms: float | None
    ttat_ms: float | None
    total_time_ms: float | None
    reasoning_tokens: int
    answer_tokens: int
    finish_reason: str | None


def load_problems() -> list[dict[str, Any]]:
    answers: dict[str, str] = {}
    with ANSWERS_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            answers[row["問題番号"]] = row["解答"].strip().lower()

    items: list[dict[str, Any]] = []
    for path in sorted(QUESTIONS_DIR.glob("119*_json.json")):
        block = path.stem.replace("_json", "")
        for q in json.loads(path.read_text()):
            q["block"] = block
            q["gold"] = answers.get(q["number"], "")
            items.append(q)
    return items


def build_messages(problem: dict[str, Any]) -> list[dict[str, Any]]:
    is_numeric = not problem["choices"]
    if is_numeric:
        user = f"{INSTRUCTION_NUMERIC}\n\n問題: {problem['question']}"
    else:
        choices = "\n".join(problem["choices"])
        user = f"{INSTRUCTION_MCQ}\n\n問題: {problem['question']}\n\n選択肢:\n{choices}"
    return [{"role": "user", "content": user}]


def extract_match(text: str) -> str:
    m = EXTRACT_RE.search(text)
    return (m.group(1).strip() if m else text).strip()


def score(problem: dict[str, Any], extracted: str) -> tuple[bool, list[str]]:
    is_numeric = not problem["choices"]
    gold = problem["gold"]
    if is_numeric:
        # Parse the first numeric token from extracted; compare as float.
        m = re.search(r"-?\d+(?:\.\d+)?", extracted)
        if not m:
            return False, []
        try:
            return abs(float(m.group()) - float(gold)) < 1e-6, [m.group()]
        except ValueError:
            return False, []
    # MCQ: compare letter sets
    pred_letters = sorted({c for c in extracted.lower() if c in LETTERS})
    gold_letters = sorted({c for c in gold.lower() if c in LETTERS})
    return pred_letters == gold_letters, pred_letters


def run(
    *,
    base_url: str,
    model: str,
    output_dir: Path,
    blocks: list[str],
    include_image: bool,
    limit: int | None,
    no_think: bool,
    max_tokens: int,
    temperature: float,
) -> Path:
    problems = load_problems()
    problems = [p for p in problems if p["block"] in blocks]
    if not include_image:
        problems = [p for p in problems if not p.get("has_image", False)]
    if limit:
        problems = problems[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    correct_count = 0
    start_dt = datetime.datetime.now().astimezone()

    pbar = tqdm(problems, desc="igakuqa119", unit="q")
    for p in pbar:
        msgs = build_messages(p)
        gen: GenerationResult = generate(
            base_url,
            model,
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        extracted = extract_match(gen.content)
        correct, ext_set = score(p, extracted)
        if correct:
            correct_count += 1
        results.append(
            SampleResult(
                problem_id=p["number"],
                block=p["block"],
                is_numeric=not p["choices"],
                gold=p["gold"],
                extracted=extracted,
                extracted_set=ext_set,
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
    aggregate = aggregate_results(model, no_think, blocks, results, start_dt, end_dt)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "igakuqa119.json"
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
    model: str,
    no_think: bool,
    blocks: list[str],
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

    by_block: dict[str, list[bool]] = {}
    for s in samples:
        by_block.setdefault(s.block, []).append(s.correct)

    return {
        "task": "igakuqa119",
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "blocks": blocks,
        "n": len(samples),
        "metrics": {
            "accuracy": sum(s.correct for s in samples) / len(samples) if samples else 0.0,
        },
        "accuracy_by_block": {
            b: {"n": len(v), "accuracy": sum(v) / len(v)} for b, v in sorted(by_block.items())
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


ALL_BLOCKS = ["119A", "119B", "119C", "119D", "119E", "119F"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blocks", nargs="+", default=ALL_BLOCKS, choices=ALL_BLOCKS)
    parser.add_argument("--include-image", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-think", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    out = run(
        base_url=args.base_url,
        model=args.model,
        output_dir=args.output_dir,
        blocks=args.blocks,
        include_image=args.include_image,
        limit=args.limit,
        no_think=args.no_think,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    print(f"[done] igakuqa119 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Runner for IgakuQA (jungokasai/IgakuQA) — Japanese medical licensing exam.

Five years (2018-2022), ~400 problems each. Multi-letter answers (e.g., "ac")
are scored by exact set match. Image-bearing problems (text_only=False) are
skipped by default.
"""

from __future__ import annotations

import argparse
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

DATASET_ROOT = Path(__file__).resolve().parents[2] / "datasets" / "igakuqa" / "data"
ALL_YEARS = ["2018", "2019", "2020", "2021", "2022"]

LETTERS = "abcdefghij"  # supports up to 10 choices; usual is 5

INSTRUCTION = (
    "以下は日本の医師国家試験の問題です。選択肢の記号({letters})から正解を選び、"
    "答えだけを <answer></answer> タグで囲んで返してください。"
    "複数の選択肢が正解の場合は記号を連結してください(例: <answer>ac</answer>)。"
)

EXTRACT_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


@dataclass
class SampleResult:
    problem_id: str
    year: str
    category: str
    has_image: bool
    points_possible: int
    gold: list[str]
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


def load_problems(years: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for year in years:
        ydir = DATASET_ROOT / year
        # Pair every problem file with its metadata file (if present).
        for prob_path in sorted(ydir.glob("*.jsonl")):
            if "metadata" in prob_path.name or "translate" in prob_path.name:
                continue
            meta_path = prob_path.with_name(prob_path.stem + "_metadata.jsonl")
            meta_by_id: dict[str, dict[str, Any]] = {}
            if meta_path.exists():
                for line in meta_path.read_text().splitlines():
                    if not line.strip():
                        continue
                    m = json.loads(line)
                    meta_by_id[m["problem_id"]] = m
            for line in prob_path.read_text().splitlines():
                if not line.strip():
                    continue
                p = json.loads(line)
                p["year"] = year
                p["category"] = meta_by_id.get(p["problem_id"], {}).get("category", "")
                items.append(p)
    return items


def build_messages(problem: dict[str, Any]) -> list[dict[str, Any]]:
    n = len(problem["choices"])
    letters = LETTERS[:n]
    choice_lines = "\n".join(f"{letters[i]}. {c}" for i, c in enumerate(problem["choices"]))
    instruction = INSTRUCTION.format(letters="/".join(letters))
    user = (
        f"{instruction}\n\n"
        f"問題: {problem['problem_text']}\n\n"
        f"選択肢:\n{choice_lines}"
    )
    return [{"role": "user", "content": user}]


def extract_letters(text: str) -> tuple[str, list[str]]:
    """Return (raw match, sorted unique letter list)."""
    m = EXTRACT_RE.search(text)
    raw = m.group(1).strip() if m else ""
    # Fallback: search the whole text if no tag
    if not raw:
        raw = text
    letters_found = sorted({c for c in raw.lower() if c in LETTERS})
    return raw, letters_found


def run(
    *,
    base_url: str,
    model: str,
    output_dir: Path,
    years: list[str],
    include_image: bool,
    limit: int | None,
    no_think: bool,
    max_tokens: int,
    temperature: float,
) -> Path:
    problems = load_problems(years)
    if not include_image:
        problems = [p for p in problems if p.get("text_only", True)]
    if limit:
        problems = problems[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    correct_count = 0
    start_dt = datetime.datetime.now().astimezone()

    pbar = tqdm(problems, desc="igakuqa", unit="q")
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
        raw_match, letters_found = extract_letters(gen.content)
        gold_set = sorted(set(a.lower() for a in p["answer"]))
        correct = letters_found == gold_set
        if correct:
            correct_count += 1
        try:
            pts = int(p.get("points", 1) or 1)
        except (ValueError, TypeError):
            pts = 1
        results.append(
            SampleResult(
                problem_id=p["problem_id"],
                year=p["year"],
                category=p.get("category", ""),
                has_image=not p.get("text_only", True),
                points_possible=pts,
                gold=gold_set,
                extracted=raw_match,
                extracted_set=letters_found,
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
    aggregate = aggregate_results(model, no_think, years, results, start_dt, end_dt)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "igakuqa.json"
    out_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return out_path


def _bucket(samples: list[SampleResult]) -> dict[str, Any]:
    correct = sum(s.correct for s in samples)
    total = len(samples)
    score = sum(s.points_possible for s in samples if s.correct)
    possible_score = sum(s.points_possible for s in samples)
    return {
        "correct": correct,
        "total": total,
        "accuracy": (correct / total) if total else 0.0,
        "score": score,
        "possible_score": possible_score,
        "score_rate": (score / possible_score) if possible_score else 0.0,
        "score_str": f"{score}/{possible_score} ({100 * score / possible_score:.2f}%)" if possible_score else "0/0 (-)",
        "accuracy_str": f"{correct}/{total} ({100 * correct / total:.2f}%)" if total else "0/0 (-)",
    }


def compute_leaderboard(samples: list[SampleResult]) -> dict[str, Any]:
    """IgakuQA leaderboard format. Each problem already carries a `points`
    field in the source data (typically 1, occasionally 3 for 必修問題).
    """
    no_image = [s for s in samples if not s.has_image]
    return {
        "overall": _bucket(samples),
        "no_image": _bucket(no_image),
    }


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
    years: list[str],
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

    by_year: dict[str, list[bool]] = {}
    by_category: dict[str, list[bool]] = {}
    for s in samples:
        by_year.setdefault(s.year, []).append(s.correct)
        if s.category:
            by_category.setdefault(s.category, []).append(s.correct)

    leaderboard = compute_leaderboard(samples)

    return {
        "task": "igakuqa",
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "years": years,
        "n": len(samples),
        "metrics": {
            "accuracy": sum(s.correct for s in samples) / len(samples) if samples else 0.0,
        },
        "leaderboard": leaderboard,
        "leaderboard_by_year": {
            y: compute_leaderboard([s for s in samples if s.year == y])
            for y in sorted({s.year for s in samples})
        },
        "accuracy_by_year": {
            y: {"n": len(v), "accuracy": sum(v) / len(v)} for y, v in sorted(by_year.items())
        },
        "accuracy_by_category": {
            c: {"n": len(v), "accuracy": sum(v) / len(v)}
            for c, v in sorted(by_category.items(), key=lambda kv: -len(kv[1]))
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
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--years", nargs="+", default=ALL_YEARS, choices=ALL_YEARS)
    parser.add_argument("--include-image", action="store_true",
                        help="include problems with images (text_only=false). Default: skip.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-think", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    out = run(
        base_url=args.base_url,
        model=args.model,
        output_dir=args.output_dir,
        years=args.years,
        include_image=args.include_image,
        limit=args.limit,
        no_think=args.no_think,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    print(f"[done] igakuqa -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

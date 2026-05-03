"""Runner for JMLE2026-Bench (naoto-iwase/JMLE2026-Bench) — 第120回医師国家試験。

400 problems / blocks A-F / 500-pt scale (B/E Q26-50 = 3pt, others = 1pt).
Prompt format mirrors upstream `benchmark.py` so results are directly
comparable to the public leaderboard at github.com/naoto-iwase/JMLE2026-Bench.

Vision auto-probe: red-square synthetic image probe at startup.
- vision OK: image-bearing problems passed multimodally → `Overall (All 400)` 列が埋まる
- vision NG / --no-vision: image-bearing problems も **テキストのみで盲解き** (LB の `image_mode=blind` default に準拠) → `Overall` 列も埋まるが Text-only モデルの数値として記録
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import re
import statistics
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

from evals.harness.client import GenerationResult, generate

ROOT = Path(__file__).resolve().parents[2] / "datasets" / "jmle2026"
DATASET_JSON = ROOT / "jmle2026_dataset.json"
IMAGES_DIR = ROOT / "images"

ALL_BLOCKS = ["A", "B", "C", "D", "E", "F"]
REQUIRED_BLOCKS = {"B", "E"}
LETTERS = "abcde"

# Upstream benchmark.py system prompts (verbatim) — required for LB parity.
SYSTEM_PROMPT_CHOICE = """\
あなたは医師国家試験を解く医学の専門家です。
問題を読み、正解を{n}つ選んでください。

最終回答は必ず以下の形式で出力してください:
【回答】{example}"""

SYSTEM_PROMPT_CALC = """\
あなたは医師国家試験を解く医学の専門家です。
問題を読み、数値で回答してください。

最終回答は必ず以下の形式で出力してください:
【回答】3.14"""

ANSWER_PATTERN = re.compile(r"【回答】\s*(.+)")


@dataclass
class SampleResult:
    question_id: str
    block: str
    question_type: str       # "multiple_choice" | "calculation"
    is_required: bool        # B/E blocks
    has_image: bool
    image_files: list[str]   # filenames passed to the model (vision mode); empty otherwise
    points_possible: int     # 1 or 3 per official scoring
    serial_group_id: str | None
    gold: list[str]
    extracted: list[str]
    parse_success: bool
    raw: str
    correct: bool
    ttft_ms: float | None
    ttat_ms: float | None
    total_time_ms: float | None
    reasoning_tokens: int
    answer_tokens: int
    finish_reason: str | None


def load_problems() -> list[dict[str, Any]]:
    return json.loads(DATASET_JSON.read_text(encoding="utf-8"))


def points_for(entry: dict[str, Any]) -> int:
    """Official scoring: 必修 (B/E) Q26-50 = 3pt, それ以外 1pt。"""
    if entry["block"] not in REQUIRED_BLOCKS:
        return 1
    return 3 if 26 <= entry["number"] <= 50 else 1


def encode_data_url(path: Path) -> str:
    suffix = path.suffix.lstrip(".").lower() or "png"
    if suffix == "jpg":
        suffix = "jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{b64}"


def get_system_prompt(entry: dict[str, Any]) -> str:
    if entry["question_type"] == "calculation":
        return SYSTEM_PROMPT_CALC
    n = entry["num_choices_to_select"]
    example = ",".join(list("ace")[:n])
    return SYSTEM_PROMPT_CHOICE.format(n=n, example=example)


def build_messages(
    entry: dict[str, Any], *, vision: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (messages, image_filenames). Mirrors upstream benchmark.py."""
    parts: list[str] = []
    if entry.get("serial_group"):
        parts.append(entry["serial_group"]["context_text"])
        parts.append("")
    parts.append(entry["question_text"])
    text = "\n".join(parts)

    image_filenames: list[str] = []
    user_content: Any = text
    if vision and entry.get("requires_image"):
        items: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for name in entry.get("clinical_images", []):
            p = IMAGES_DIR / name
            if not p.exists():
                continue
            items.append({
                "type": "image_url",
                "image_url": {"url": encode_data_url(p)},
            })
            image_filenames.append(name)
        if len(items) > 1:
            user_content = items

    return [
        {"role": "system", "content": get_system_prompt(entry)},
        {"role": "user", "content": user_content},
    ], image_filenames


def parse_answer(raw: str, question_type: str) -> tuple[list[str], bool]:
    """Extract the answer in upstream format. Returns (tokens, parse_success)."""
    m = ANSWER_PATTERN.search(raw)
    if not m:
        return [], False
    ans = m.group(1).strip()
    if question_type == "calculation":
        return [ans], True
    cleaned = re.sub(r"[*_`#]", "", ans).strip()
    tokens = re.split(r"[,、\s]+", cleaned)
    picks = sorted({t.lower() for t in tokens if re.fullmatch(r"[a-eA-E]", t)})
    return picks, bool(picks)


def is_correct(predicted: list[str], gold: list[str], question_type: str) -> bool:
    if question_type == "calculation":
        if len(predicted) != 1:
            return False
        try:
            return float(predicted[0]) == float(gold[0])
        except ValueError:
            return False
    return sorted(predicted) == sorted(gold)


def _solid_red_png(size: int = 32) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    row = b"\x00" + (b"\xff\x00\x00" * size)
    idat = chunk(b"IDAT", zlib.compress(row * size))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def probe_vision(base_url: str, model: str) -> bool:
    img_b64 = base64.b64encode(_solid_red_png()).decode("ascii")
    msg = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "What single color is shown in this image? Answer with one word."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
        ],
    }]
    try:
        r = generate(base_url, model, msg, max_tokens=512, timeout=120.0)
    except Exception:
        return False
    full = ((r.reasoning_content or "") + " " + (r.content or "")).lower()
    return "red" in full or "赤" in full or "まっか" in full


def run(
    *,
    base_url: str,
    model: str,
    output_dir: Path,
    blocks: list[str],
    no_vision: bool,
    limit: int | None,
    no_think: bool,
    max_tokens: int,
    temperature: float,
) -> Path:
    problems = load_problems()
    problems = [p for p in problems if p["block"] in blocks]

    image_problems = [p for p in problems if p.get("requires_image", False)]
    if no_vision or not image_problems:
        vision_supported = False
        probe_status = "skipped (no_vision flag) → image_mode=blind" if no_vision else "skipped (no image problems)"
    else:
        vision_supported = probe_vision(base_url, model)
        probe_status = "vision OK → image_mode=vision" if vision_supported else "vision NG → image_mode=blind (LB default)"
    print(f"[probe] {probe_status}")

    # LB default = blind: vision 不可でも画像問題は除外せず、テキストのみで強制解答させる。
    # build_messages() 側で vision=False ならテキストのみ送る挙動になっている。
    if limit:
        problems = problems[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    correct_count = 0
    start_dt = datetime.datetime.now().astimezone()

    pbar = tqdm(problems, desc="jmle2026", unit="q")
    for p in pbar:
        msgs, image_files = build_messages(p, vision=vision_supported)
        gen: GenerationResult = generate(
            base_url,
            model,
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        extracted, parse_ok = parse_answer(gen.content, p["question_type"])
        correct = is_correct(extracted, p["answer"], p["question_type"])
        if correct:
            correct_count += 1
        results.append(SampleResult(
            question_id=p["question_id"],
            block=p["block"],
            question_type=p["question_type"],
            is_required=p["block"] in REQUIRED_BLOCKS,
            has_image=p.get("requires_image", False),
            image_files=image_files,
            points_possible=points_for(p),
            serial_group_id=(p.get("serial_group") or {}).get("group_id"),
            gold=list(p["answer"]),
            extracted=extracted,
            parse_success=parse_ok,
            raw=gen.content,
            correct=correct,
            ttft_ms=gen.ttft_ms,
            ttat_ms=gen.ttat_ms,
            total_time_ms=gen.total_time_ms,
            reasoning_tokens=gen.reasoning_tokens,
            answer_tokens=gen.answer_tokens,
            finish_reason=gen.finish_reason,
        ))
        pbar.set_postfix(acc=f"{correct_count / len(results):.3f}")

    end_dt = datetime.datetime.now().astimezone()
    aggregate = aggregate_results(model, no_think, blocks, vision_supported, results, start_dt, end_dt)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "jmle2026.json"
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
    text_only = [s for s in samples if not s.has_image]
    return {
        "overall": _bucket(samples),
        "text_only": _bucket(text_only),
        "required": _bucket([s for s in samples if s.is_required]),
        "general": _bucket([s for s in samples if not s.is_required]),
        "text_only_required": _bucket([s for s in text_only if s.is_required]),
        "text_only_general": _bucket([s for s in text_only if not s.is_required]),
    }


def percentile(xs: list[float | None], p: float) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _count(xs: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


def build_submission_view(
    model: str, vision_used: bool, no_think: bool, samples: list[SampleResult]
) -> dict[str, Any]:
    """Mirror upstream `benchmark.py` JSON shape (metadata/summary/results) so
    the file can be lifted out and PR'd to the JMLE2026-Bench leaderboard with
    a small jq selection. We do not write a separate file — it's stored under
    the `submission` key of our standard output."""
    image_mode = "vision" if vision_used else "blind"
    overall = _bucket(samples)
    text_only = _bucket([s for s in samples if not s.has_image])
    required = _bucket([s for s in samples if s.is_required])
    general = _bucket([s for s in samples if not s.is_required])

    by_block: dict[str, dict[str, Any]] = {}
    for s in samples:
        b = by_block.setdefault(s.block, {"correct": 0, "total": 0})
        b["correct"] += int(s.correct)
        b["total"] += 1
    for b in by_block.values():
        b["accuracy"] = round(b["correct"] / b["total"], 4) if b["total"] else 0.0

    by_type: dict[str, dict[str, Any]] = {}
    for s in samples:
        t = by_type.setdefault(s.question_type, {"correct": 0, "total": 0})
        t["correct"] += int(s.correct)
        t["total"] += 1
    for t in by_type.values():
        t["accuracy"] = round(t["correct"] / t["total"], 4) if t["total"] else 0.0

    summary = {
        "accuracy": round(overall["accuracy"], 4),
        "correct": overall["correct"],
        "incorrect": overall["total"] - overall["correct"],
        "score": overall["score"],
        "score_max": overall["possible_score"],
        "score_pct": round(overall["score_rate"], 4),
        "text_only_score": text_only["score"],
        "text_only_score_max": text_only["possible_score"],
        "text_only_score_pct": round(text_only["score_rate"], 4),
        "required_score": required["score"],
        "required_score_max": required["possible_score"],
        "required_score_pct": round(required["score_rate"], 4),
        "general_score": general["score"],
        "general_score_max": general["possible_score"],
        "general_score_pct": round(general["score_rate"], 4),
        "required_pass": required["score"] >= 160,
        "general_pass": general["score"] >= 224,
        "parse_failures": sum(1 for s in samples if not s.parse_success),
        "errors": 0,
        "by_block": by_block,
        "by_type": by_type,
        "by_image": {
            "text_only": {
                "correct": text_only["correct"],
                "total": text_only["total"],
                "accuracy": round(text_only["accuracy"], 4),
            },
            "with_image": {
                "correct": overall["correct"] - text_only["correct"],
                "total": overall["total"] - text_only["total"],
                "accuracy": round(
                    (overall["correct"] - text_only["correct"])
                    / max(overall["total"] - text_only["total"], 1), 4
                ),
            },
        },
    }

    metadata = {
        "model": model,
        "image_mode": image_mode,
        "no_think": no_think,
        "total_questions": len(samples),
        "attempted": len(samples),
        "skipped_image": 0,
    }

    records = [
        {
            "question_id": s.question_id,
            "predicted": s.extracted,
            "gold": s.gold,
            "correct": s.correct,
            "raw_response": s.raw,
            "parse_success": s.parse_success,
            "error": None,
        }
        for s in samples
    ]
    return {"metadata": metadata, "summary": summary, "results": records}


def aggregate_results(
    model: str,
    no_think: bool,
    blocks: list[str],
    vision_used: bool,
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
        "task": "jmle2026",
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "vision_used": vision_used,
        "blocks": blocks,
        "n": len(samples),
        "metrics": {
            "accuracy": sum(s.correct for s in samples) / len(samples) if samples else 0.0,
        },
        "leaderboard": compute_leaderboard(samples),
        "submission": build_submission_view(model, vision_used, no_think, samples),
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blocks", nargs="+", default=ALL_BLOCKS, choices=ALL_BLOCKS)
    parser.add_argument("--no-vision", action="store_true",
                        help="vision auto-probe をスキップし、画像問題を最初から除外する")
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
        no_vision=args.no_vision,
        limit=args.limit,
        no_think=args.no_think,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    print(f"[done] jmle2026 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Runner for IgakuQA119 (naoto-iwase/IgakuQA119) — 119th medical licensing exam.

400 problems across blocks A-F. Choices come pre-prefixed (e.g. "a. ..."). A
small number of problems (~4) are numeric calculation problems with empty
`choices`; we score those by parsed numeric equality.

**Vision auto-detect**: at start of run, sends one test image to the served
model. If accepted, image-bearing problems (has_image=true) are included with
multimodal content (vision evaluation). If rejected (text-only model),
image problems are skipped automatically (No-Img only). `--no-vision` to
force skip the probe and run text-only.
"""

from __future__ import annotations

import argparse
import base64
import csv
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

ROOT = Path(__file__).resolve().parents[2] / "datasets" / "igakuqa119"
QUESTIONS_DIR = ROOT / "questions"
IMAGES_DIR = ROOT / "images"
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

# Default モード: naoto-iwase/IgakuQA119 の src/llm_solver.py と同じ
# system prompt + user prompt + 出力形式を採用。公式 LB と直接比較可能。
# `--legacy` で旧 `<answer>` タグ形式に切替 (歴史的互換用)。
OFFICIAL_SYSTEM_PROMPT = """\
あなたは医師国家試験問題を解く優秀で論理的なアシスタントです。
以下のルールを守って、問題文と選択肢(または数値入力の指示)を確認し、回答してください。

【ルール】
1. 明示的な指示がない場合は、単一選択肢のみ選ぶ(例: "a", "d")。
2. 「2つ選べ」「3つ選べ」などとあれば、その数だけ選択肢をアルファベット順で列挙する(例: "ac", "bd")。
3. 選択肢が存在せず数値入力が求められる場合は、指定がない限りそのままの数値を答える(例: answer: 42)。
4. 画像(has_image=True)は参考情報とし、特別な形式は不要。
5. 不要な装飾やMarkdown記法は含めず、以下の形式に従って厳密に出力してください:

answer: [選んだ回答(単数/複数/数値)]
confidence: [0.0〜1.0の確信度]
explanation: [選択理由や重要な根拠を簡潔に]

【answerについて注意】
- 問題は単数選択、複数選択、数値入力のいずれかであり、問題文からその形式を判断する。
- 「どれか。」で終わる選択問題で数が明記されていない場合は、五者択一を意味するので選択肢を必ず1つだけ選び小文字のアルファベットで回答する。(単数選択)
- 「2つ選べ」「3つ選べ」などと書いてある場合に限り、指定された数だけの複数選択肢を選び、小文字のアルファベット順(abcde順)に並び替えて列挙する。(複数選択)
- 選択肢が存在しない場合は、小数や四捨五入など、問題文で特に指示があればそれに従い、選択肢記号ではなく数値を回答する。(数値入力)
- 問題に関連しない余計な文は書かず、指定のキー(answer, confidence, explanation)を上記の出力に従って厳密に出力する。
"""

OFFICIAL_ANSWER_RE = re.compile(r"^\s*answer\s*[:：]\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


@dataclass
class SampleResult:
    problem_id: str
    block: str
    is_numeric: bool
    is_required: bool   # B/E blocks
    has_image: bool
    image_files: list[str]  # filenames passed to the model (vision mode); empty otherwise
    points_possible: int  # 1 or 3 per official scoring
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


def find_image_paths(number: str) -> list[Path]:
    """Locate image files for a problem.

    Convention in naoto-iwase/IgakuQA119: single -> {number}.png,
    multiple -> {number}-1.png, {number}-2.png, ...
    """
    single = IMAGES_DIR / f"{number}.png"
    if single.exists():
        return [single]
    return sorted(IMAGES_DIR.glob(f"{number}-*.png"))


def encode_data_url(path: Path) -> str:
    suffix = path.suffix.lstrip(".").lower() or "png"
    if suffix == "jpg":
        suffix = "jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{b64}"


def build_messages(
    problem: dict[str, Any], *, vision: bool, official: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (messages, image_filenames). image_filenames is empty unless
    vision=True and the problem has images.

    official=True: naoto-iwase/IgakuQA119 と同じ system + user 構成 + 出力形式。
    """
    is_numeric = not problem["choices"]

    if official:
        if is_numeric:
            text = f"問題:{problem['question']}\n\n回答を指定された形式で出力してください。"
        else:
            choices = "\n".join(problem["choices"])
            text = (
                f"問題:{problem['question']}\n\n"
                f"選択肢:\n{choices}\n\n"
                f"回答を指定された形式で出力してください。"
            )
    else:
        if is_numeric:
            text = f"{INSTRUCTION_NUMERIC}\n\n問題: {problem['question']}"
        else:
            choices = "\n".join(problem["choices"])
            text = f"{INSTRUCTION_MCQ}\n\n問題: {problem['question']}\n\n選択肢:\n{choices}"

    image_filenames: list[str] = []
    if vision and problem.get("has_image", False):
        paths = find_image_paths(problem["number"])
        if paths:
            user_content: Any = [{"type": "text", "text": text}]
            for p in paths:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": encode_data_url(p)},
                })
                image_filenames.append(p.name)
        else:
            user_content = text
    else:
        user_content = text

    if official:
        return [
            {"role": "system", "content": OFFICIAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ], image_filenames
    return [{"role": "user", "content": user_content}], image_filenames


def extract_match(text: str, *, official: bool = False) -> str:
    if official:
        m = OFFICIAL_ANSWER_RE.search(text)
        if m:
            return m.group(1).strip().strip('"\'`')
        # fallback: タグ形式 / 全文
        m2 = EXTRACT_RE.search(text)
        return (m2.group(1).strip() if m2 else text).strip()
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


def _solid_red_png(size: int = 32) -> bytes:
    """Hand-craft a tiny solid-red PNG with stdlib only (no Pillow)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    row = b"\x00" + (b"\xff\x00\x00" * size)  # filter byte + RGB
    idat = chunk(b"IDAT", zlib.compress(row * size))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def probe_vision(base_url: str, model: str) -> bool:
    """Probe whether the served model truly handles images.

    Sends a synthetic solid-red PNG and asks for the color. A genuine
    multimodal pathway returns "red" / "赤" / similar. Text-only models that
    silently strip the image return arbitrary text (or refuse), so we check
    the response content rather than just HTTP success.
    """
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
        # reasoning モデルは thinking で max_tokens を消費するので余裕を持たせる
        r = generate(base_url, model, msg, max_tokens=512, timeout=120.0)
    except Exception:
        return False
    # reasoning_content と content の両方を見て "red"/"赤" 系のキーワードを探す
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
    legacy: bool = False,
) -> Path:
    # Default = `naoto-iwase/IgakuQA119` 公式形式 (LB直接比較可)。
    # `--legacy` 指定時のみ独自 `<answer>` タグ形式。
    official = not legacy
    problems = load_problems()
    problems = [p for p in problems if p["block"] in blocks]

    # Auto-detect vision capability via a synthetic colored-square probe.
    # Text-only servers either reject or silently ignore the image; we check
    # the response content (must mention "red"/"赤") to avoid false positives.
    image_problems = [p for p in problems if p.get("has_image", False)]
    if no_vision or not image_problems:
        vision_supported = False
        probe_status = "skipped (no_vision flag)" if no_vision else "skipped (no image problems)"
    else:
        vision_supported = probe_vision(base_url, model)
        probe_status = "vision OK" if vision_supported else "vision NG → image問題スキップ"
    print(f"[probe] {probe_status}")

    if not vision_supported:
        problems = [p for p in problems if not p.get("has_image", False)]
    if limit:
        problems = problems[:limit]

    extra_body: dict[str, Any] = {}
    if no_think:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    results: list[SampleResult] = []
    correct_count = 0
    start_dt = datetime.datetime.now().astimezone()

    desc = "igakuqa119_legacy" if legacy else "igakuqa119"
    pbar = tqdm(problems, desc=desc, unit="q")
    for p in pbar:
        msgs, image_files = build_messages(p, vision=vision_supported, official=official)
        gen: GenerationResult = generate(
            base_url,
            model,
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        extracted = extract_match(gen.content, official=official)
        correct, ext_set = score(p, extracted)
        if correct:
            correct_count += 1
        results.append(
            SampleResult(
                problem_id=p["number"],
                block=p["block"],
                is_numeric=not p["choices"],
                is_required=p["block"] in REQUIRED_BLOCKS,
                has_image=p.get("has_image", False),
                image_files=image_files,
                points_possible=points_for(p["number"], p["block"]),
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
    task_name = "igakuqa119_legacy" if legacy else "igakuqa119"
    aggregate = aggregate_results(model, no_think, blocks, vision_supported, results, start_dt, end_dt, task_name=task_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{task_name}.json"
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
    """Build IgakuQA119 leaderboard-format breakdown.

    Mirrors columns: Overall Score | Overall Acc. | No-Img Score | No-Img Acc.
    Plus required/general split. Note: if image questions were skipped at run
    time, "overall" reflects only the questions that were actually scored;
    use --include-image to populate the full 500-pt overall.
    """
    no_image = [s for s in samples if not s.has_image]
    return {
        "overall": _bucket(samples),
        "no_image": _bucket(no_image),
        "required": _bucket([s for s in samples if s.is_required]),
        "general": _bucket([s for s in samples if not s.is_required]),
        "no_image_required": _bucket([s for s in no_image if s.is_required]),
        "no_image_general": _bucket([s for s in no_image if not s.is_required]),
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
    blocks: list[str],
    vision_used: bool,
    samples: list[SampleResult],
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    task_name: str = "igakuqa119",
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

    leaderboard = compute_leaderboard(samples)

    return {
        "task": task_name,
        "model": model,
        "mode": "think_off" if no_think else "think_on",
        "vision_used": vision_used,
        "blocks": blocks,
        "n": len(samples),
        "metrics": {
            "accuracy": sum(s.correct for s in samples) / len(samples) if samples else 0.0,
        },
        "leaderboard": leaderboard,
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
REQUIRED_BLOCKS = {"119B", "119E"}


def points_for(problem_id: str, block: str) -> int:
    """Official IgakuQA119 scoring:
    必修 (B/E blocks): Q1-25 = 1pt, Q26-50 = 3pt
    一般 (A/C/D/F):    1pt
    """
    if block not in REQUIRED_BLOCKS:
        return 1
    # extract numeric suffix from e.g. "119B26"
    suffix = problem_id[len(block):]
    digits = "".join(c for c in suffix if c.isdigit())
    n = int(digits) if digits else 0
    return 3 if 26 <= n <= 50 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blocks", nargs="+", default=ALL_BLOCKS, choices=ALL_BLOCKS)
    parser.add_argument("--no-vision", action="store_true",
                        help="vision capability の auto-probe をスキップし、画像問題を最初から除外する(text-only モデル前提)")
    parser.add_argument("--legacy", action="store_true",
                        help="独自 `<answer>` タグ形式で実行 (旧 default、歴史的互換用)。default は naoto-iwase/IgakuQA119 公式 LB 形式。出力は igakuqa119_legacy.json")
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
        legacy=args.legacy,
        limit=args.limit,
        no_think=args.no_think,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    label = "igakuqa119_legacy" if args.legacy else "igakuqa119"
    print(f"[done] {label} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

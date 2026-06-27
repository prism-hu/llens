"""large-v3-turbo (CTranslate2) を CPU で文字起こしし RTF を測る簡易ベンチ。

使い方:
    uv run --with faster-whisper evals/stt/bench.py <audio> [<audio> ...]

RTF (実時間係数) = 処理秒 / 音声秒。1.0 未満なら実時間より速い。
"""

import sys
import time
import subprocess

from faster_whisper import WhisperModel

MODEL = "models/whisper/faster-whisper-large-v3-turbo-ct2"


def audio_sec(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def run(model, path):
    t = time.perf_counter()
    segments, info = model.transcribe(path, language="ja", vad_filter=True)
    text = "".join(s.text for s in segments)  # generator なので消費して計測確定
    return time.perf_counter() - t, text


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit("audio ファイルを渡してください")

    t = time.perf_counter()
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    load = time.perf_counter() - t
    print(f"model load (CPU/int8): {load:.1f}s\n")

    print(f"{'audio':<24}{'音声秒':>8}{'処理秒':>8}{'RTF':>8}  倍速")
    for p in paths:
        run(model, p)                 # warmup (1回目は確保等の overhead)
        sec, text = run(model, p)
        dur = audio_sec(p)
        rtf = sec / dur
        print(f"{p.split('/')[-1]:<24}{dur:>8.1f}{sec:>8.1f}{rtf:>8.3f}  {1/rtf:.1f}x")
        print(f"  → {text.strip()[:60]}")


if __name__ == "__main__":
    main()

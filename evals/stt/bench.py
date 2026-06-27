"""large-v3-turbo (CTranslate2) を CPU で文字起こしし RTF を測る簡易ベンチ。

音声サンプルが無ければ gTTS で生成 (日本語読み上げ → 指定秒数にループ) してから測るので
一発で走る:

    uv run --with faster-whisper --with gtts evals/stt/bench.py

ffmpeg / ffprobe (system) が必要。RTF (実時間係数) = 処理秒 / 音声秒。1.0 未満で実時間より速い。
"""

import os
import time
import subprocess

from faster_whisper import WhisperModel

MODEL = "models/whisper/faster-whisper-large-v3-turbo-ct2"
SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "samples")
DURATIONS = [15, 60]  # 秒
TEXT = ("本日は晴天なり。患者は六十五歳男性、主訴は二日前からの発熱と倦怠感。"
        "既往歴に高血圧と二型糖尿病があり、内服加療中である。"
        "血圧は百四十の九十、脈拍は毎分八十八回、体温は三十七度八分であった。")


def ensure_samples() -> list[str]:
    """gTTS 読み上げを base にして DURATIONS 秒の wav を用意 (無ければ生成)。"""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    base = os.path.join(SAMPLE_DIR, "ja_base.mp3")
    if not os.path.exists(base):
        from gtts import gTTS
        print("generating sample audio (gTTS)...")
        gTTS(TEXT, lang="ja").save(base)

    paths = []
    for d in DURATIONS:
        wav = os.path.join(SAMPLE_DIR, f"ja_{d}s.wav")
        if not os.path.exists(wav):
            base_dur = audio_sec(base)
            loops = int(d / base_dur) + 1
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-stream_loop", str(loops),
                 "-i", base, "-t", str(d), wav],
                check=True,
            )
        paths.append(wav)
    return paths


def audio_sec(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def run(model, path):
    t = time.perf_counter()
    segments, _ = model.transcribe(path, language="ja", vad_filter=True)
    text = "".join(s.text for s in segments)  # generator なので消費して計測確定
    return time.perf_counter() - t, text


def main():
    paths = ensure_samples()

    t = time.perf_counter()
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    print(f"\nmodel load (CPU/int8): {time.perf_counter() - t:.1f}s\n")

    print(f"{'audio':<14}{'音声秒':>8}{'処理秒':>8}{'RTF':>8}  倍速")
    for p in paths:
        run(model, p)                 # warmup (1回目は確保等の overhead)
        sec, text = run(model, p)
        dur = audio_sec(p)
        rtf = sec / dur
        print(f"{os.path.basename(p):<14}{dur:>8.1f}{sec:>8.1f}{rtf:>8.3f}  {1 / rtf:.1f}x")
        print(f"  → {text.strip()[:60]}")


if __name__ == "__main__":
    main()

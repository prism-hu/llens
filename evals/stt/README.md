# STT ベンチ (CPU)

OWUI 内蔵 faster-whisper で使う `large-v3-turbo` (CTranslate2) を **CPU で文字起こしした時の速度** を測る簡易ベンチ。モデル選定の経緯・比較は [docs/stt.md](../../docs/stt.md)。

## 実行

一発。サンプル音声が無ければ gTTS で生成 (日本語読み上げ → 15s/60s ループ) してから測る。

```bash
uv run --with faster-whisper --with gtts evals/stt/bench.py
```

ffmpeg / ffprobe (system) が必要。`samples/` は git 管理外 (使い捨て音声、2回目以降は再利用)。

## 結果 (2026-06-28)

- ハード: AMD EPYC 9355 (32C/64T)、device=cpu、compute_type=int8、vad_filter=true
- モデルロード: ~1.2s (1回だけ)

| 音声長 | 処理秒 | RTF | 倍速 |
|---|---|---|---|
| 15s | 3.5s | 0.234 | 4.3x |
| 60s | 10.7s | 0.179 | 5.6x |

**RTF ≈ 0.18〜0.23（実時間の 4〜6 倍速）。** 口述ディクテーション (数秒〜1分) なら CPU で「話し終えてすぐ文字になる」レベルで、GPU は不要。

> 注: gTTS 合成音声のため医療用語に誤変換あり (例「主訴」→「主祖」)。これは速度ベンチ用の素材都合で、専門用語の弱点自体は docs/stt.md 参照。

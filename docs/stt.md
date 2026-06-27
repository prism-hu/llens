# 音声認識 (STT) モデル選定メモ

LLENS の音声入力 (OWUI のマイク → 文字起こし) に使う STT モデルの選定記録。
**結論: `large-v3-turbo` (CTranslate2 版) を OWUI 内蔵 faster-whisper・CPU で運用。**

セットアップ手順・DL コマンドは README「音声認識 (STT)」節。ここは *なぜそれを選んだか* の単一情報源。

## 前提・制約

- **閉域 + 患者音声**: ブラウザの Web Speech API (Chrome) は既定でクラウド方式＝音声を Google に送る。閉域で動かず、そもそも患者音声を外部送信できない → **サーバ側で完結する STT 一択**。Chrome 139 のオンデバイスモードも端末依存・日本語パック不確実で不採用。
- OWUI v0.9.5 は `STT_ENGINE=''` で内蔵 faster-whisper (CTranslate2) を使う。`WHISPER_MODEL` にローカルパスを渡せる (`routers/audio.py` `set_faster_whisper_model`)。`WHISPER_MODEL_AUTO_UPDATE=false` で `local_files_only=True` → オフライン読み込み。
- デバイスは `DEVICE_TYPE!='cuda'` で CPU。主推論 (H200x8) を汚さないため **STT は CPU 運用**。ディクテーション長なら CPU int8 で実時間の数十倍速、体感は即時。

## 指標の意味

| 指標 | 何を測るか | 良いのは |
|---|---|---|
| CER (文字誤り率) | 認識文字のうち誤った割合 (%) | **低いほど良い** |
| WER (単語誤り率) | 単語/文節単位の誤りの割合 | **低いほど良い** |
| RTF (実時間係数) | 処理時間 ÷ 音声長 (0.1 = 音声長の 1/10 で処理) | **低いほど速い** |

**注意: 下記の表は出典も録音条件も別物。表をまたいだ数値比較は不可** (同一モデルでも条件で CER が 9%→49% まで動く)。比較は同じ表の中だけで見る。

## 条件別 CER (低いほど良い)

### A. クリーン読み上げ・単一話者 (kotoba 公式 eval, 正規化後)
| モデル | CV8 ja | JSUT5000 | Reazon |
|---|---|---|---|
| kotoba-v2.0 | 9.2 | 8.4 | 11.6 |
| large-v3 | 8.5 | 7.1 | 14.9 |

### B. クリーン合成音声 (bhrtaym, TTS)
| モデル | CER | 速度 sec/件 |
|---|---|---|
| large-v3-turbo | 14.8 | 8.9 |
| large-v3 | 16.0 | 46.0 |

### C. ノイズ + 複数話者 + 自然発話 (neosophie, 同一テストで直接対決)
| モデル | CER | RTF | OWUI 内蔵経路 |
|---|---|---|---|
| qwen3-asr-1.7b | 14.0 | 0.036 | ✗ 非 whisper |
| **large-v3-turbo** | **18.4** | 0.013 | ✅ |
| **kotoba-v2.0** | **49.5** | 0.008 | ✅ |

## 最終二択: kotoba-v2.0-faster vs large-v3-turbo-ct2

| 軸 | kotoba-v2.0-faster | large-v3-turbo-ct2 | 勝ち |
|---|---|---|---|
| 静かな読み上げ精度 | CER 8〜11% | ~15% | kotoba (同一テスト直接比較値は無し) |
| 騒音/複数話者 | CER **49.5%** (崩壊) | CER **18.4%** | **turbo** |
| 専門用語 | △ (誤変換・脱落) | ◎相当 | **turbo** |
| 脱落・繰り返し(ハルシ) | 多い (decoder 2層の構造的弱点) | 少ない (4層) | **turbo** |
| CPU速度 | RTF 0.008 | RTF 0.013 | kotoba (ただし両者とも過剰に速く体感差ゼロ) |
| 対応言語 | 日本語のみ | 99言語 | **turbo** |

### 判断
- kotoba が勝つのは「静かな単一話者の読み上げ」1軸のみ。しかも専門用語ではそこでも負ける。
- 速度差は無価値 (両方とも実時間の数十倍速、口述用途では一瞬)。kotoba 唯一の優位が実用上効かない。
- 病院で効くのは **専門用語 × 崩れにくさ**。医療用語は kotoba の最弱点。無人運用で音声条件が読めない以上、**最低保証ライン (floor) が高い turbo が正解**。kotoba=高天井/低床、turbo=中天井/高床。
- → **large-v3-turbo-ct2 を既定採用。** kotoba を選べるのは「静かな個室・単一話者・一般語の口述」に運用を縛れる場合のみ。

## 出典

- [kotoba-whisper-v2.0 (公式 CER 表)](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0)
- [neosophie 日本語 ASR ベンチ (過酷条件・直接対決)](https://neosophie.com/ja/blog/20260226-japanese-asr-benchmark)
- [Qiita 日本語文字起こしモデル徹底比較 (専門用語・脱落)](https://qiita.com/Dinn/items/a800f031813746a5ec37)
- [bhrtaym Whisper 日本語 CER 実測](https://bhrtaym-blog.com/gemma4-e2b-vs-whisper-apple-silicon-benchmark-2026/)
- [deepdml/faster-whisper-large-v3-turbo-ct2](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2)

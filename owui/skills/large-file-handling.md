---
title: Large File Handling
description: "巨大な添付ファイルを、中身を主コンテキストに展開せずに処理するためのワークフロー。large-file-gate filter が『本文を context に入れていない (file_id=… で取得可)』というシステム指示を出した時、または巨大な CSV/Excel/PDF/ログ等を『全文を会話に出さずに』集計・要約・抽出したい時に起動する。tool と Pyodide (Code Interpreter) を併用する: Pyodide で file_id から raw / docling md を取り戻し、サイズを見て戦略的に削る or 分割し、harvest で file_id 化してから ask_subagent (subagent tool) に渡して結果だけ受け取る。中身そのものは print せず、メタ情報 (サイズ・shape・列名) と file_id だけを扱う。電子カルテ系 CSV は cp932 のことが多い。"
---

# 大容量ファイル処理 (中身を context に出さずに扱う)

## いつ使うか

- **large-file-gate** filter が「以下の添付は大きすぎるため本文を context に入れていない (file_id=… で取得できる)」というシステム指示を出した時。→ そのファイルの中身は**プロンプトに無い**。読めないので、ここの手順で file_id から取り戻して処理する。
- 巨大な CSV / Excel / PDF / ログ等を、**全文を会話に展開せずに**集計・要約・抽出したい時。

## 大原則

1. **中身を print しない。** stdout に出したものは会話 context に入る。出してよいのは「サイズ・shape・行数・列名などのメタ情報」と「file_id」だけ。個票・本文は出さない (院内 = 個人情報前提)。
2. **重い読解・要約は ask_subagent に投げる。** サブエージェントは別 context・別推論で動き、資料の中身は主 context に出ない。返るのは短い answer だけ。
3. **サブエージェントは tool を使えない / 一度に約 100k tokens まで。** だから「巨大を飲める形に削る・割る」前処理は**こちら (Pyodide) で**やる。割った後の各片を ask_subagent に渡す。

## 取得経路 (Pyodide からは同一オリジンで cookie 認証自動)

```python
from pyodide.http import pyfetch

# 生データ (CSV/Excel/バイナリ)。CSV は stdlib csv、xlsx は openpyxl read_only で読む元
raw = await (await pyfetch(f"/api/v1/files/{file_id}/content")).bytes()

# docling 抽出済み md (PDF/Office の本文)。チャンク分割して読ませる元
md = (await (await pyfetch(f"/api/v1/files/{file_id}/data/content")).json())["content"]
```

どちらを使うかはファイル種別で決める (両方取って使い分けてよい):
- **PDF / Word / PowerPoint** → `md` (docling 抽出テキスト) を分割して処理
- **CSV / TSV / ログ** → `raw` を **stdlib `csv`** でストリーム処理 (電子カルテ系 CSV は **cp932** が多い)
- **Excel (.xlsx)** → 下の「xlsx の扱い」を参照

> **重さの原則**: Pyodide の **pandas は import で numpy ごと数十 MB ロード + WASM が遅く、巨大データでタイムアウトしやすい**。CSV は stdlib `csv`、xlsx は `openpyxl` read_only で **stream + 早期 break**。「全部読む / 全部 DataFrame 化」を避ける。

## 戦略を立てる (メタだけ見る)

まず**中身を出さずに**サイズと構造だけ確認し、削るか割るかを決める。CSV は stdlib で軽い:

```python
import io, csv
print("step: inspect")
r = csv.reader(io.TextIOWrapper(io.BytesIO(raw), encoding="cp932", newline=""))
header = next(r)
print("columns:", header)                  # 列名だけ (値は出さない)
print("rows:", sum(1 for _ in r))          # 行数だけ
```

## xlsx の扱い (タイムアウト対策)

xlsx は ZIP+XML で必ずパースが要り、巨大だと Pyodide で**タイムアウトしがち**。順に:

1. **openpyxl read_only + 早期 break** で head/sample/構造だけ取る (stream。途中で止まれば残りはパースしない):
   ```python
   # install は単独セル: ("openpyxl", "et-xmlfile")
   import io, csv
   from openpyxl import load_workbook
   wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
   ws = wb.active
   print("sheets:", wb.sheetnames, "dim:", ws.calculate_dimension())  # メタだけ
   buf = io.StringIO(); w = csv.writer(buf)
   for i, row in enumerate(ws.iter_rows(values_only=True)):
       if i >= 2000: break        # 先頭だけ。巨大でも軽い
       w.writerow(row)
   wb.close()
   # buf を harvest → ask_subagent
   ```
2. **全集計が要る / それでもタイムアウトする**なら Pyodide で粘らず、**ユーザーに「xlsx を CSV (UTF-8 か cp932) に変換して再アップロード」を促す**。CSV なら stdlib で stream でき桁違いに軽い。無理に xlsx を WASM で捌かないのが正解。
3. **pandas.read_excel も使える**が、numpy ロード + 全 materialise で**巨大だとタイムアウトしやすい**。中規模までの保険として使う程度に留め、巨大ファイルは 1. (read_only) か 2. (CSV 変換) を優先する。

## harvest (削った/割った成果物を file_id 化)

中身を出さずに BE へ退避し file_id を得る。`POST /api/v1/files/` (添付ではないので**次ターンに再注入されない**)。

```python
from pyodide.http import pyfetch
from pyodide.ffi import to_js
import js

async def harvest(data: bytes, filename: str, content_type: str = "text/plain") -> str:
    u8 = js.Uint8Array.new(len(data)); u8.assign(data)
    blob = js.Blob.new(to_js([u8]),
                       to_js({"type": content_type}, dict_converter=js.Object.fromEntries))
    fd = js.FormData.new(); fd.append("file", blob, filename)
    resp = await pyfetch("/api/v1/files/", method="POST", body=fd)
    if resp.status != 200:
        raise RuntimeError(f"harvest failed: HTTP {resp.status}")
    return (await resp.json())["id"]
```

## パターン A: blind 抽出 (必要部分だけ取り出す)

全体は要らず「該当部分だけ」読ませたい時。Pyodide で絞り込み → 1 個の file_id → ask_subagent 1 回。

```python
print("step: extract")
import io, csv
out = io.StringIO(); w = csv.writer(out)
src = csv.reader(io.TextIOWrapper(io.BytesIO(raw), encoding="cp932", newline=""))
header = next(src); w.writerow(header)
ci = header.index("科")
for row in src:
    if row and row[ci] == "呼吸器内科":     # 必要行だけ (中身は print しない)
        w.writerow(row)
fid = await harvest(out.getvalue().encode("utf-8"), "subset.csv", "text/csv")
print("extracted file_id:", fid)            # 出すのはこの 1 行だけ
```

→ 続けて tool 呼び出し: `ask_subagent(file_id=fid, instruction="この抜粋を集計して…")`

## パターン B: 全網羅 (分割して map-reduce)

全体を要約/抽出する時。Pyodide で N 分割 → 各片を harvest → 各 file_id を ask_subagent → 最後にこちらで統合。

```python
print("step: split")
# md をトークン目安 (~8万 tokens=約16万字) ごとに分割。境界は段落優先で
CHUNK = 160000
ids = []
for i in range(0, len(md), CHUNK):
    part = md[i:i + CHUNK]
    ids.append(await harvest(part.encode("utf-8"),
                             f"chunk_{i//CHUNK:03d}.md", "text/markdown"))
print("chunk file_ids:", ids)               # id のリストだけ出す
```

→ 各 `ids[k]` を `ask_subagent(file_id=ids[k], instruction="この断片から…を抽出")` に渡し、返った短い answer を集めてこちらで統合する。断片数が多いと tool 呼び出しが増えるので、本当に全網羅が要るかは先に検討する (多くは パターン A で足りる)。

## ask_subagent への渡し方 (subagent tool)

- `ask_subagent(file_id=…, instruction=…)` … 新規。資料を読ませて結論だけ返す。`thread_id` も返る。
- `ask_subagent(thread_id=…, instruction=…)` … 継続。同じ資料・文脈のまま追い質問 (file_id 不要)。
- text 資料は本文注入、画像 (image/*) は VLM に隔離送信。**資料の中身も会話履歴もサブエージェント側に隔離され主 context には出ない。**

## セッション保護 (Pyodide)

`prompts/code-interpreter.md` の「実行単位とセッションの保護」に従う。要点:
- 取得・分割・harvest は**別々のセル**で、各セル先頭に `print("step …")` を置いて疎通を確認してから次へ。
- harvest は単独セルで `file_id` が返ることを確認する。
- セッションが壊れて NameError 等が出たら自力で復旧を繰り返さず、ユーザーにリロードを確認する。

## やってはいけないこと

- 中身 (本文・個票・full md・DataFrame 全体) を print / 応答本文に貼る。
- `mount_tool` で巨大ファイルを /mnt に出す → .md が**添付として再登録**され、次ターンに本文が再注入される。巨大ファイルは上記 pyfetch 直取得を使う。
- 巨大ファイルの file_id をそのまま ask_subagent に渡す → サブエージェント側で頭から truncate され尻尾が落ちる。必ず先に削る/割る。

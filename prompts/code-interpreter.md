## コード実行環境
OpenWebUIのCode Interpreter（Pyodide）でPythonを実行できます。

### 標準利用可能なライブラリ（importするだけで使える）
- 数値・統計: numpy, pandas, scipy, scikit-learn, sympy
- 可視化: matplotlib
- XML/HTML: beautifulsoup4
- テキスト: regex, tiktoken
- 日時: pytz
- HTTP（同一オリジン用）: pyodide.http
- および標準ライブラリ

### 追加導入可能なパッケージ（院内ホストから配信）
下表の名前をタプルに並べて下記の導入パターンを実行する。
**wheel ファイル名は書かなくて良い**（index.json と OWUI 同梱 Pyodide が裏で解決）。

依存欄に出てくる名前 (`lxml`, `pillow`, `typing-extensions`, `fonttools`, `markupsafe` 等) も
**必ずタプルに並記する**こと。micropip は `deps=False` で依存自動解決しないため、漏れると
内部 import 時に ModuleNotFoundError になる。

| 用途 | パッケージ名 | 一緒に入れる依存 |
|---|---|---|
| Excel(.xlsx) 読み書き | `openpyxl` | `et-xmlfile` |
| Excel(.xlsx) 高速書き出し・グラフ | `xlsxwriter` | — |
| Word(.docx) 読み書き | `python-docx` | `lxml`, `typing-extensions` |
| PowerPoint(.pptx) 読み書き | `python-pptx` | `lxml`, `xlsxwriter`, `pillow`, `typing-extensions` |
| PDF生成 | `fpdf2` | `defusedxml`, `pillow`, `fonttools` |
| DICOM読み取り | `pydicom` | — |
| 文字コード自動判定 | `chardet` | — |
| XML/HTML 高速処理 | `lxml` | — |
| テンプレート | `jinja2` | `markupsafe` |
| 暗号 | `pycryptodome` | — |
| 画像 | `pillow` | — |
| 型ヘルパ | `typing-extensions` | — |
| フォント処理 | `fonttools` | — |

#### 導入パターン (必要パッケージをタプルに並べる)

タプル内の名前は、`/static/pyodide-extra/index.json` にあれば同 wheel を、無ければ
plain 名のまま micropip に渡す (OWUI 同梱 Pyodide の `pyodide-lock.json` 経由で解決)。

```python
import micropip
from pyodide.http import pyfetch

_idx = (await (await pyfetch("/static/pyodide-extra/index.json")).json())
await micropip.install(
    [(f"/static/pyodide-extra/{_idx[n]}" if n in _idx else n)
     for n in ("python-docx", "lxml", "typing-extensions")],
    deps=False,
)
```

別パッケージを使うときは tuple の中身だけ書き換える。例:
- Word(.docx) 読み書き: `("python-docx", "lxml", "typing-extensions")`
- PowerPoint(.pptx) 読み書き: `("python-pptx", "lxml", "xlsxwriter", "pillow", "typing-extensions")`
- PDF 生成: `("fpdf2", "defusedxml", "pillow", "fonttools")`
- DICOM 読み取り: `("pydicom",)`
- テンプレート: `("jinja2", "markupsafe")`
- Excel 読み書き: `("openpyxl", "et-xmlfile")`

### 使用不可
- 重量級ML: torch, tensorflow, transformers, sentence-transformers, spacy
- 外部HTTP: requests（同一オリジン通信が必要なら `pyodide.http.pyfetch` を使う）
- OS機能: subprocess, multiprocessing
- ローカルファイル直接アクセス（仮想FSのみ。ユーザファイルは `/mnt/uploads/` 経由）
- 外部ネットワーク通信全般（院内閉域のため）

### matplotlibでプロットするとき
必ず以下の形式で出力すること：
```python
import matplotlib.pyplot as plt
import io, base64
plt.figure(figsize=(10, 6))
# 描画処理
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
buf.seek(0)
print(f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}")
plt.close()
```
- データURL文字列（data:image/png;base64,...）のみをprintする
- Markdown記法（![alt](...)）を付けない
- OpenWebUIが自動的にファイルURLに変換するため、応答本文では変換後のファイルURLをMarkdown形式で参照する
- 応答本文に生のbase64文字列を貼り付けない

### 生成したファイルの扱い
Pyodideで `/mnt/uploads/` 以下にファイルを保存した場合、OpenWebUIの右上スライダーアイコン（設定パネル）→「ファイル」タブに出力ファイルが表示され、ユーザーがダウンロードできる。
画像以外のファイル（CSV、Excel、Word、PowerPoint、PDF等）を出力する際はこの方法を用い、応答本文でファイル名と取得方法を案内する。

### 院内利用の指針
- 電子カルテ系CSVは Shift_JIS(CP932) のことが多い。`pd.read_csv(path, encoding="cp932")` または `chardet` で判定する。
- 個人情報を含むファイルを扱う前提のため、ファイル内容を不要に print で羅列しない。集計結果・統計値のみを出力する。
- ユーザがアップロードしたファイルは `/mnt/uploads/` に配置されているので、フルパスではなくファイル名で参照する。
- アップロード済みファイル一覧: `import os; os.listdir('/mnt/uploads')`
- ファイルシステムは同一セッション内では永続化される

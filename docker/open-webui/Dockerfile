# LLENS 用 Open WebUI イメージ
#
# - バックエンド (Python 3.11): pdf2image / pypdf を pip 追加 (pin)
#   用途: Functions/Tools から PDF → 画像 → VLM (Kimi K2.6 等) 経路
# - クライアント Pyodide (Python 3.12 WASM): Office 系 wheel を静的配信
#   /app/build/static/pyodide-extra/*.whl が同一オリジン HTTP で配信される
#   → 閉域でもブラウザの micropip でロード可能
#
# バージョン更新時は FROM タグと docker-compose.yml の image タグを同期して
#   docker compose build --pull open-webui

FROM ghcr.io/open-webui/open-webui:v0.9.5

# ─────────────────────────────────────────────
# システムパッケージ (PDF → 画像変換)
# ─────────────────────────────────────────────
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────
# バックエンド (Python 3.11)
# ─────────────────────────────────────────────
RUN pip install --no-cache-dir \
        pdf2image==1.17.0 \
        pypdf==6.7.5 \
        tiktoken

# ─────────────────────────────────────────────
# Pyodide (ブラウザ WASM) 向け wheel を静的配信ディレクトリへ
# ─────────────────────────────────────────────
# 取得対象: PyPI に pure Python wheel (py3-none-any) があるもののみ。
# Pyodide ネイティブ同梱で重複バンドルする必要が無いものは除外:
#   lxml / Pillow / numpy / pandas / scipy / matplotlib / regex /
#   beautifulsoup4 / sympy / tiktoken / pytz / Jinja2 / MarkupSafe /
#   pycryptodome / typing_extensions
# pure Python wheel が無い (= C 拡張のみ) ものはここでは取得できない:
#   MarkupSafe, pycryptodome 等。これらは上記の通り Pyodide 側に既存。

RUN mkdir -p /app/build/static/pyodide-extra \
 && pip download \
        --dest /app/build/static/pyodide-extra \
        --no-deps \
        --only-binary=:all: \
        --platform=any \
        --python-version=3.12 \
        openpyxl==3.1.5 \
        et_xmlfile==2.0.0 \
        python-docx==1.2.0 \
        python-pptx==1.0.2 \
        XlsxWriter==3.2.9 \
        fpdf2==2.8.7 \
        defusedxml==0.7.1 \
        pydicom==3.0.2 \
        chardet==7.4.3

# index.json を自動生成: {PEP 503 正規化名: wheel filename}。
# model にはパッケージ名だけ書かせれば、ブラウザ側で index を引いて
# 正確な wheel filename に解決できる (filename hallucination 防止)。
RUN python -c "import json, pathlib, re; \
d = pathlib.Path('/app/build/static/pyodide-extra'); \
idx = {re.sub(r'[-_.]+', '-', w.name.split('-')[0]).lower(): w.name \
       for w in sorted(d.glob('*.whl'))}; \
(d / 'index.json').write_text(json.dumps(idx, indent=2, sort_keys=True) + '\n'); \
print('index.json:', json.dumps(idx, indent=2, sort_keys=True))"

# ─────────────────────────────────────────────
# OWUI ハードコード prompt の差し替え
# ─────────────────────────────────────────────
# CODE_INTERPRETER_PYODIDE_PROMPT は env で上書きできない文字列定数で
# "Do not install packages ... micropip.install() are not available" を含む。
# LLENS は /static/pyodide-extra/ 経由の micropip を許可する設計のため、
# prompts/code-interpreter.md (= 単一情報源) の中身で定数ブロックを置換する。
# build context が repo root のため、COPY パスは repo 相対で指定。
COPY docker/open-webui/patch-pyodide-prompt.py /tmp/patch-pyodide-prompt.py
COPY prompts/code-interpreter.md /tmp/code-interpreter.md
RUN python /tmp/patch-pyodide-prompt.py \
 && rm /tmp/patch-pyodide-prompt.py /tmp/code-interpreter.md

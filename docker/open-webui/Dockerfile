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
# /app/build/static/pyodide-extra/ に置いた wheel は同一オリジン HTTP で配信され、
# pyfetch + micropip.install(deps=False) でブラウザ Pyodide にロードされる。
#
# OWUI 0.9.5 同梱 Pyodide = 0.28.0.dev0 / ABI cp313-pyodide_2025_0_wasm32。
# `/app/build/pyodide/` に下記の wheel だけが既に bundle されており、
# `loadPackagesFromImports` で import から auto-load される (再配布不要):
#   beautifulsoup4 / matplotlib / numpy / pandas / pillow / pytz / regex /
#   scikit-learn / scipy / sympy / tiktoken / typing_extensions
#   (openai / requests / pydantic / httpx 等 OWUI 内部用も含む)
#
# 注意: pyodide-lock.json には lxml / jinja2 / markupsafe / pycryptodome 等の
# entry も載っているが OWUI は wheel ファイルを bundle から落としているため、
# `await micropip.install("lxml")` 等は 404 で失敗する。下記の経路で別途配信する。
#
# 経路 A: pure-Python wheel (py3-none-any) を PyPI から取得。
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
        chardet==7.4.3 \
        Jinja2==3.1.6

# 経路 B: C 拡張ありで Pyodide 専用 emscripten ビルドが必要なもの (PyPI には無い)。
# Pyodide upstream (jsdelivr v0.28.0/full) から ABI 2025_0 wheel を直接取得する。
# OWUI 同梱 Pyodide (0.28.0.dev0) と v0.28.0 はリビジョン差があるが ABI が同一
# (cp313-pyodide_2025_0_wasm32) なので import 互換。
# pyfetch 経由で導入するため pyodide-lock.json の sha256 検証は通らない (関係なし)。
ARG PYODIDE_CDN=https://cdn.jsdelivr.net/pyodide/v0.28.0/full
RUN for whl in \
        lxml-5.4.0-cp313-cp313-pyodide_2025_0_wasm32.whl \
        markupsafe-3.0.2-cp313-cp313-pyodide_2025_0_wasm32.whl \
        pycryptodome-3.21.0-cp36-abi3-pyodide_2025_0_wasm32.whl ; do \
        curl -fSL -o "/app/build/static/pyodide-extra/$whl" "$PYODIDE_CDN/$whl" ; \
    done

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

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
        pypdf==6.7.5

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

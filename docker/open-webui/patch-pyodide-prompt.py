#!/usr/bin/env python3
"""
OWUI が hardcode している CODE_INTERPRETER_PYODIDE_PROMPT を
LLENS 仕様 (prompts/code-interpreter.md の内容) に差し替える (build 時に実行)。

オリジナルは「Do not install packages — pip install, subprocess, and
micropip.install() are not available」と一律禁止しており、これは LLENS が
/static/pyodide-extra/ 配下の wheel を micropip.install で導入する設計と矛盾する。

prompts/code-interpreter.md を単一情報源として、その中身をそのまま注入する。

- 既に LLENS 化済みなら no-op (idempotent)
- 上書き対象パターンが見つからない / 注入元 md が無いと build を失敗させる

────────────────────────────────────────────────────────────────────────
参考: 上書き対象の OWUI オリジナル prompt (v0.9.5 時点)
────────────────────────────────────────────────────────────────────────
OWUI を上げるときは下と upstream の現行版を diff して、
我々の LLENS 版 prompt (prompts/code-interpreter.md) に取り込むべき変更が
無いか確認すること。新版で構造が変わったら本ファイル末尾の正規表現も要見直し。

抽出コマンド:
  docker run --rm --entrypoint sh ghcr.io/open-webui/open-webui:<TAG> -c \\
    'python3 -c "import re; print(re.search(r\\"CODE_INTERPRETER_PYODIDE_PROMPT\\\\s*=\\\\s*(\\\\\\"\\\\\\"\\\\\\"[\\\\s\\\\S]*?\\\\\\"\\\\\\"\\\\\\")\\", open(\\"/app/backend/open_webui/config.py\\").read()).group(0))"'

──── ghcr.io/open-webui/open-webui:v0.9.5 ────
CODE_INTERPRETER_PYODIDE_PROMPT = '''

##### Pyodide Environment

- This Python environment runs via Pyodide in the browser. **Do not install packages** — `pip install`, `subprocess`, and `micropip.install()` are not available.
- If a required library is unavailable, use an alternative approach with available modules. Do not attempt to install anything.

##### Persistent File System

- User-uploaded files are available at `/mnt/uploads/`. When the user asks you to work with their files, read from this directory.
- You can also write output files to `/mnt/uploads/` so the user can access and download them from the file browser.
- The file system persists across code executions within the same session.
- Use `import os; os.listdir('/mnt/uploads')` to discover available files.
'''
────────────────────────────────────────────────────────────────────────
"""
import pathlib
import re
import sys

TARGET = pathlib.Path("/app/backend/open_webui/config.py")
SOURCE = pathlib.Path("/tmp/code-interpreter.md")  # Dockerfile が COPY する
# 置換後にだけ現れる日本語フレーズで idempotent 検出
MARKER = "## コード実行環境"


def main() -> int:
    if not SOURCE.exists():
        print(f"[patch-pyodide-prompt] ERROR: {SOURCE} not found", file=sys.stderr)
        return 1
    body = SOURCE.read_text().rstrip("\n")

    text = TARGET.read_text()

    if MARKER in text:
        print(f"[patch-pyodide-prompt] already patched, skipping")
        return 0

    pattern = re.compile(
        r'CODE_INTERPRETER_PYODIDE_PROMPT\s*=\s*"""[\s\S]*?"""',
    )
    if not pattern.search(text):
        print(
            f"[patch-pyodide-prompt] ERROR: pattern not found in {TARGET}.\n"
            "  OWUI のバージョン更新で定数構造が変わった可能性。\n"
            "  docker/open-webui/patch-pyodide-prompt.py の正規表現を要見直し。",
            file=sys.stderr,
        )
        return 1

    # md 本文に "\"\"\"" が含まれていたらエスケープ (現状は含まないが念のため)
    if '"""' in body:
        print(
            "[patch-pyodide-prompt] ERROR: source md contains triple-quote, "
            "would break Python string literal",
            file=sys.stderr,
        )
        return 1

    new_block = f'CODE_INTERPRETER_PYODIDE_PROMPT = """\n{body}\n"""'
    new_text = pattern.sub(lambda _: new_block, text, count=1)
    TARGET.write_text(new_text)
    print(f"[patch-pyodide-prompt] OK — injected {SOURCE} into {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

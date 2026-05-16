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

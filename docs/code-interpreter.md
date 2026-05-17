# Code Interpreter (Pyodide) 環境

OWUI の Code Interpreter は **ブラウザ上の Pyodide** で Python を実行する。
本ドキュメントは LLENS でこの環境をどう構成しているかの**エンジニアリング
リファレンス**。model 向けの利用案内は `prompts/code-interpreter.md`
(本番システムプロンプト) を参照。

## 環境バージョン (2026-05-18 時点)

| 項目 | 値 |
|---|---|
| OWUI | v0.9.5 (`ghcr.io/open-webui/open-webui:v0.9.5`) |
| Pyodide | 0.28.0.dev0 |
| Python | 3.13.2 |
| ABI | `cp313-cp313-pyodide_2025_0_wasm32` (emscripten_4_0_9) |

OWUI を上げるときは `docker/open-webui/Dockerfile` の `FROM` タグと
`docker-compose.yml` の `image` タグを同期して
`docker compose build --pull open-webui` でリビルド。

## 利用可能パッケージの 3 出所

1. **Python 標準ライブラリ** — Pyodide ランタイム同梱。`import` で直接使える。
2. **OWUI bundle** (`/pyodide/*.whl`) — OWUI が独自に取捨選択した wheel 群。
   `import` で auto-load されるか `await micropip.install("name")` で取得。
3. **LLENS pyodide-extra** (`/static/pyodide-extra/*.whl`) — LLENS が
   `docker/open-webui/Dockerfile` で追加同梱した wheel。`prompts/code-interpreter.md`
   記載の pyfetch + index.json パターンで取得。

実際の個別パッケージ名は `prompts/code-interpreter.md` の表に列挙されている
(model に渡す本番プロンプトと一致させるため重複は持たない)。

## pyodide-lock.json の落とし穴

OWUI 同梱の `/pyodide/pyodide-lock.json` には Pyodide upstream の
**340 entry が全部書かれている**が、実際に wheel ファイルが配置されているのは
そのうち **46 個だけ**。残り 294 entry は `await micropip.install("...")` しても
**404 で失敗**する。

`lxml` / `markupsafe` / `pycryptodome` を LLENS 側 (pyodide-extra) で経路 B
追加せざるを得なかったのはこのため。新規にパッケージを追加する前に、まず
OWUI bundle に実在するか `make list-pyodide-bundle` 等で確認すること。

## pyodide-extra への追加経路

`docker/open-webui/Dockerfile` に 2 つの経路がある:

- **経路 A** (`pip download --platform=any --python-version=3.12`)
  PyPI に `py3-none-any` の pure-Python wheel があるもの。ビルド時に PyPI から取得。
- **経路 B** (jsdelivr `v0.28.0/full` から `curl`)
  C 拡張ありで Pyodide 専用 emscripten ビルドが必要なもの (PyPI には存在しない)。
  ABI `cp313-cp313-pyodide_2025_0_wasm32` 一致のものを直接 DL。

`index.json` は build 時に自動生成 (PEP 503 正規化名 → wheel filename map)。
model はパッケージ名だけタプルに並べれば良く、wheel filename hallucination が起きない。

## 静的アセット

| パス | 内容 | 用途 |
|---|---|---|
| `/static/pyodide-extra/index.json` | pyodide-extra wheel の正規化名 → filename map | model が pyfetch で wheel URL 解決 |
| `/static/pyodide-extra/*.whl` | LLENS 追加 wheel | pyfetch + micropip.install |
| `/static/fonts/NotoSansJP-Regular.ttf` | Noto Sans JP Regular (OFL, ~2.3MB) | matplotlib / fpdf2 の日本語出力 |
| `/pyodide/*.whl` | OWUI bundle wheel | import 経由で auto-load |
| `/pyodide/pyodide-lock.json` | Pyodide 公式 lock (340 entry, **実体は 46 個のみ**) | 上記の落とし穴に注意 |

## prompt 上書き

OWUI v0.9.5 の `CODE_INTERPRETER_PYODIDE_PROMPT` 定数は env で上書きできない。
ビルド時に `docker/open-webui/patch-pyodide-prompt.py` が `config.py` を sed
パッチして、`prompts/code-interpreter.md` の内容を注入する (LLENS は
`/static/pyodide-extra/` 経由の micropip.install を許可する設計のため、
オリジナルの「Do not install packages」は無効化する必要がある)。

OWUI を上げる際は patch script 冒頭の docstring に**オリジナル prompt の
v0.9.5 時点 snapshot** が引用されているので、upstream の新版と diff を取って
取り込み漏れが無いか確認する。

## 追加・確認用コマンド

```sh
# OWUI bundle に何が同梱されているか
docker exec llens-open-webui ls /app/build/pyodide/ | grep '\.whl$' \
  | awk -F- '{n=$1; v=$2; gsub(/[.]whl$/,"",v); printf "%-25s %s\n", n, v}' | sort

# LLENS pyodide-extra (index.json)
docker exec llens-open-webui cat /app/build/static/pyodide-extra/index.json | python3 -m json.tool

# Pyodide ABI / version の確認
docker exec llens-open-webui python3 -c '
import json; d=json.load(open("/app/build/pyodide/pyodide-lock.json"))["info"]
for k in ("version","python","abi_version","platform"): print(k, d[k])'
```

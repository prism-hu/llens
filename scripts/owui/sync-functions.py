#!/usr/bin/env python3
"""
OWUI Functions 同期スクリプト

filters/*.py を OWUI の REST API 経由で登録/更新する。べき等。

挙動:
  1. GET /api/v1/functions/id/{id} で存在確認
  2a. あれば → POST /id/{id}/update (content / name / meta を更新)
                is_active / is_global は OWUI 側の現状を尊重 (保持)
  2b. 無ければ → POST /create + 初回のみ /toggle (active) + /toggle/global を打って
                  active=True, is_global=True にする (default は両方 False)

必要な .env (REPO_ROOT/.env):
  OWUI_API_KEY   - admin の API Key (OWUI Settings → Account → API Keys)
  OWUI_BASE_URL  - default http://localhost:8080

使い方:
  ./scripts/owui/sync-functions.py             # filters/*.py 全部
  ./scripts/owui/sync-functions.py token_meter # 個別指定 (拡張子なし、複数可)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FILTERS_DIR = REPO_ROOT / "filters"
ENV_PATH = REPO_ROOT / ".env"


def load_env(path: pathlib.Path) -> dict[str, str]:
    """.env を簡易 parse。KEY=VAL 行のみ、クォート除去、コメント無視。
    OS 環境変数が優先されるよう、呼び出し側で os.environ を上書きする。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def parse_frontmatter(content: str) -> dict[str, str]:
    """先頭の docstring から `key: value` 行だけ拾う。OWUI 自身は
    multi-line description (`description: |`) も解釈するが、ここで使うのは
    title (= name) のみで十分なため 1 行 KV だけ拾う最小実装。"""
    m = re.search(r'^"""(.*?)"""', content, re.S | re.M)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        m2 = re.match(r"^([a-zA-Z_]+):\s*(.+)$", line.strip())
        if m2:
            fm[m2.group(1)] = m2.group(2).strip()
    return fm


def http_request(
    method: str, url: str, api_key: str, body: dict | None = None
) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def sync_one(path: pathlib.Path, base_url: str, api_key: str) -> bool:
    fid = path.stem
    if not fid.replace("_", "").isalnum():
        print(f"[SKIP] {fid}: OWUI は id に alnum + _ のみ許可", file=sys.stderr)
        return False

    content = path.read_text()
    fm = parse_frontmatter(content)
    name = fm.get("title", fid)
    body = {
        "id": fid,
        "name": name,
        "content": content,
        "meta": {"description": fm.get("description")},
    }

    base = base_url.rstrip("/")
    get_url = f"{base}/api/v1/functions/id/{fid}"
    status, _ = http_request("GET", get_url, api_key)

    if status == 200:
        # 既存 → update。is_active / is_global は OWUI 側の現状を尊重 (touch しない)
        status, text = http_request(
            "POST", f"{base}/api/v1/functions/id/{fid}/update", api_key, body
        )
        if status == 200:
            print(f"[UPDATE] {fid}  ({name})")
            return True
        print(f"[FAIL]   {fid} update status={status} body={text[:200]}", file=sys.stderr)
        return False

    if status == 401:
        print(f"[FAIL]   {fid} 認証失敗 (OWUI_API_KEY を確認)", file=sys.stderr)
        return False

    # 不在 → create + active/global を立てる
    status, text = http_request(
        "POST", f"{base}/api/v1/functions/create", api_key, body
    )
    if status != 200:
        print(f"[FAIL]   {fid} create status={status} body={text[:200]}", file=sys.stderr)
        return False

    # create 直後は is_active=False, is_global=False。toggle で True 化。
    # toggle は OWUI 側の現状を反転するため、ここでは「初回 create 直後 (= False)」と
    # わかっているこの 1 回だけ叩く。失敗しても create 自体は成功扱いにする
    # (UI からトグルすれば復帰可能なので)。
    for ep in ("toggle", "toggle/global"):
        s, t = http_request(
            "POST", f"{base}/api/v1/functions/id/{fid}/{ep}", api_key
        )
        if s != 200:
            print(
                f"[WARN]   {fid} {ep} status={s} body={t[:200]} (UI で手動 toggle 必要)",
                file=sys.stderr,
            )
    print(f"[CREATE] {fid}  ({name})  → active=True, global=True")
    return True


def main() -> int:
    env = {**load_env(ENV_PATH), **os.environ}  # OS env が優先
    api_key = env.get("OWUI_API_KEY")
    base_url = env.get("OWUI_BASE_URL", "http://localhost:8080")
    if not api_key:
        print("OWUI_API_KEY が .env か環境変数に必要", file=sys.stderr)
        return 2

    only = set(sys.argv[1:])
    files = sorted(FILTERS_DIR.glob("*.py"))
    if not files:
        print(f"filter ファイルなし: {FILTERS_DIR}", file=sys.stderr)
        return 1

    targets = [f for f in files if not only or f.stem in only]
    if only and not targets:
        print(f"指定 id がどれも見つからない: {sorted(only)}", file=sys.stderr)
        return 1

    ok = sum(sync_one(f, base_url, api_key) for f in targets)
    print(f"\n{ok}/{len(targets)} synced")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())

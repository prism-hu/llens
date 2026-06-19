#!/usr/bin/env python3
"""
OWUI Functions / Tools 同期スクリプト

owui/filters/*.py → /api/v1/functions/  (Function: filter / pipe / action)
owui/tools/*.py   → /api/v1/tools/      (Tool: モデルが呼び出す function-calling)

それぞれ GET で存在確認 → update or create。べき等。
Function は create 後に /toggle と /toggle/global を叩いて active=True, global=True にする
(default は両方 False)。Tool には toggle endpoint が無く access は OWUI 側で個別管理。

必要な .env (REPO_ROOT/.env):
  OWUI_API_KEY   - admin の API Key (OWUI Settings → Account → API Keys、`sk-` で始まる)
  OWUI_BASE_URL  - default http://localhost:8080

使い方:
  ./scripts/owui/sync.py             # owui/filters/ owui/tools/ 両方
  ./scripts/owui/sync.py mount_tool  # 個別指定 (拡張子なし、複数可)
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
ENV_PATH = REPO_ROOT / ".env"

# kind 別の dir / endpoint / 初回トグル
KINDS: dict[str, dict] = {
    "filter": {
        "dir": REPO_ROOT / "owui" / "filters",
        "api_prefix": "/api/v1/functions",
        # create 直後は両 False。OWUI 設計上、ここを True にしないと load されない。
        "post_create_toggles": ["toggle", "toggle/global"],
    },
    "tool": {
        "dir": REPO_ROOT / "owui" / "tools",
        "api_prefix": "/api/v1/tools",
        # tool は toggle endpoint なし。
        "post_create_toggles": [],
        # create 時のみ public read を付与 (OWUI default は private)。
        # v0.9.5 の public = grant {user:* read} (access_control_to_grants の
        # "None → public read" がソース)。update では送らず OWUI 側の現状を尊重する
        # (UI で絞った access を上書きしないため)。
        "create_access_grants": [
            {"principal_type": "user", "principal_id": "*", "permission": "read"},
        ],
    },
}


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
    """先頭 docstring から `key: value` 行だけ拾う。OWUI は multi-line description
    (`description: |`) も解釈するが、ここで使うのは title (= name) のみで十分なため
    1 行 KV だけ拾う最小実装。"""
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


def sync_one(
    path: pathlib.Path, kind: str, base_url: str, api_key: str
) -> bool:
    cfg = KINDS[kind]
    fid = path.stem
    if not fid.replace("_", "").isalnum():
        print(f"[SKIP] {kind}:{fid}: OWUI は id に alnum + _ のみ許可", file=sys.stderr)
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
    prefix = cfg["api_prefix"]
    status, _ = http_request("GET", f"{base}{prefix}/id/{fid}", api_key)

    if status == 200:
        # 既存 → update。active / global / access は OWUI 側の現状を尊重 (touch しない)
        status, text = http_request(
            "POST", f"{base}{prefix}/id/{fid}/update", api_key, body
        )
        if status == 200:
            print(f"[UPDATE {kind}] {fid}  ({name})")
            return True
        print(
            f"[FAIL {kind}] {fid} update status={status} body={text[:200]}",
            file=sys.stderr,
        )
        return False

    # status != 200 は「不在」とみなして create に進む。
    # 注意: OWUI は存在しない function への GET /functions/id/{id} に 404 でなく 401 を
    # 返す (functions.py が NOT_FOUND を HTTP_401 で raise。tools は 404)。よって 401 を
    # 一律「認証失敗」とは扱えない (新規 filter が永遠に create されなくなる)。本物の
    # bad key なら下の create も 401 を返し、fid 付きで [FAIL ... create status=401] と表出する。

    # 不在 → create。tool は create 時のみ access_grants を付与 (default public read)。
    # body 本体には足さない = update 経路では送られず、既存 access を尊重する。
    create_body = body
    grants = cfg.get("create_access_grants")
    if grants:
        create_body = {**body, "access_grants": grants}
    status, text = http_request(
        "POST", f"{base}{prefix}/create", api_key, create_body
    )
    if status != 200:
        print(
            f"[FAIL {kind}] {fid} create status={status} body={text[:200]}",
            file=sys.stderr,
        )
        return False

    # create 直後の初期化トグル (filter のみ)。toggle は現状を反転するため、
    # 「create 直後 (= False)」とわかっているこの 1 回だけ叩く。
    toggle_msg = ""
    for ep in cfg["post_create_toggles"]:
        s, t = http_request(
            "POST", f"{base}{prefix}/id/{fid}/{ep}", api_key
        )
        if s != 200:
            print(
                f"[WARN] {fid} {ep} status={s} body={t[:200]} (UI で手動 toggle 必要)",
                file=sys.stderr,
            )
    if cfg["post_create_toggles"]:
        toggle_msg = "  → active=True, global=True"
    elif cfg.get("create_access_grants"):
        toggle_msg = "  → public (user:* read)"
    else:
        toggle_msg = "  ※ access は OWUI 側で要設定"
    print(f"[CREATE {kind}] {fid}  ({name}){toggle_msg}")
    return True


def discover_targets(only: set[str]) -> list[tuple[pathlib.Path, str]]:
    """owui/filters/*.py と owui/tools/*.py を kind 付きで列挙。only 指定があればその id だけに絞る。"""
    targets: list[tuple[pathlib.Path, str]] = []
    for kind, cfg in KINDS.items():
        for f in sorted(cfg["dir"].glob("*.py")):
            if only and f.stem not in only:
                continue
            targets.append((f, kind))
    return targets


def main() -> int:
    env = {**load_env(ENV_PATH), **os.environ}  # OS env が優先
    api_key = env.get("OWUI_API_KEY")
    base_url = env.get("OWUI_BASE_URL", "http://localhost:8080")
    if not api_key:
        print("OWUI_API_KEY が .env か環境変数に必要", file=sys.stderr)
        return 2
    if not api_key.startswith("sk-"):
        print(
            f"OWUI_API_KEY の形式が変 (sk- で始まる必要あり、現在の先頭: {api_key[:5]!r})",
            file=sys.stderr,
        )
        return 2

    only = set(sys.argv[1:])
    targets = discover_targets(only)

    if only:
        found = {p.stem for p, _ in targets}
        missing = only - found
        if missing:
            print(f"指定 id が見つからない: {sorted(missing)}", file=sys.stderr)
            return 1
    if not targets:
        print(
            f"対象なし (owui/filters/ owui/tools/ に *.py が無い、または only 指定にマッチせず)",
            file=sys.stderr,
        )
        return 1

    ok = sum(sync_one(p, kind, base_url, api_key) for p, kind in targets)
    print(f"\n{ok}/{len(targets)} synced")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())

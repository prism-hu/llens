#!/usr/bin/env python3
"""
OWUI Functions / Tools / Skills 同期スクリプト

owui/filters/*.py → /api/v1/functions/  (Function: filter / pipe / action)
owui/tools/*.py   → /api/v1/tools/      (Tool: モデルが呼び出す function-calling)
owui/skills/*.md  → /api/v1/skills/     (Skill: モデルに注入する md リファレンス)

それぞれ GET で存在確認 → update or create。べき等。
Function は create 後に /toggle と /toggle/global を叩いて active=True, global=True にする
(default は両方 False)。Tool には toggle endpoint が無く access は OWUI 側で個別管理。
Skill は create 時点で is_active=True (SkillForm default) + public read を付与。
update では is_active を OWUI 側の現状から echo して維持し、access_grants は送らない
(admin が None を渡すと filter_allowed_access_grants が None を返し access 不変)。

filter/tool と skill で差異:
  - id: filter/tool は filename stem。skill は frontmatter `name` (hyphen スラグ。OWUI の
        skill id は hyphen 規約)。表示 name は frontmatter `title` か、無ければスラグの title-case。
  - frontmatter: filter/tool は先頭 Python docstring、skill は YAML (---...---)。
  - payload: filter/tool は meta.description。skill は name/description/content/is_active が
             トップレベル (SkillForm)。content は両者ともファイル全文 (skill も frontmatter 込み)。

必要な .env (REPO_ROOT/.env):
  OWUI_API_KEY   - admin の API Key (OWUI Settings → Account → API Keys、`sk-` で始まる)
  OWUI_BASE_URL  - default http://localhost:8080

使い方:
  ./scripts/owui/sync.py             # owui/filters/ owui/tools/ owui/skills/ 全部
  ./scripts/owui/sync.py mount_tool  # 個別指定 (filename stem、複数可)
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

# kind 別の dir / glob / endpoint / 初回トグル
KINDS: dict[str, dict] = {
    "filter": {
        "dir": REPO_ROOT / "owui" / "filters",
        "glob": "*.py",
        "api_prefix": "/api/v1/functions",
        # create 直後は両 False。OWUI 設計上、ここを True にしないと load されない。
        "post_create_toggles": ["toggle", "toggle/global"],
    },
    "tool": {
        "dir": REPO_ROOT / "owui" / "tools",
        "glob": "*.py",
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
    "skill": {
        "dir": REPO_ROOT / "owui" / "skills",
        "glob": "*.md",
        "api_prefix": "/api/v1/skills",
        # skill は create 時 is_active=True (SkillForm default) なので toggle 不要。
        "post_create_toggles": [],
        # tool と同じく create 時のみ public read。update では送らない。
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


def parse_md_frontmatter(content: str) -> dict[str, str]:
    """skill の YAML frontmatter (---...---) から 1 行 KV を拾う。
    クォート除去。multi-line (`description: |`) は未対応だが、現状の skill は
    description を 1 行クォートで書いているため十分。"""
    m = re.search(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.S)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        m2 = re.match(r"^([a-zA-Z_]+):\s*(.+)$", line.strip())
        if m2:
            v = m2.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            fm[m2.group(1)] = v
    return fm


def build_skill_payload(path: pathlib.Path, content: str) -> tuple[str, dict]:
    """skill md → (id, SkillForm 互換 body)。
    id = frontmatter name (hyphen スラグ)。表示 name = frontmatter title か
    スラグの title-case。description = frontmatter description。content は全文。
    is_active はここでは True (create 用)。update 時は呼び出し側で現状を echo する。"""
    fm = parse_md_frontmatter(content)
    skill_id = (fm.get("name") or path.stem.replace("_", "-")).strip()
    name = fm.get("title") or skill_id.replace("-", " ").title()
    body = {
        "id": skill_id,
        "name": name,
        "description": fm.get("description"),
        "content": content,
        "is_active": True,
    }
    return skill_id, body


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
    content = path.read_text()

    if kind == "skill":
        # id は frontmatter name (hyphen スラグ)。hyphen を許可する。
        fid, body = build_skill_payload(path, content)
        if not fid.replace("_", "").replace("-", "").isalnum():
            print(f"[SKIP] {kind}:{fid}: OWUI は id に alnum + _ - のみ許可", file=sys.stderr)
            return False
        name = body["name"]
    else:
        fid = path.stem
        if not fid.replace("_", "").isalnum():
            print(f"[SKIP] {kind}:{fid}: OWUI は id に alnum + _ のみ許可", file=sys.stderr)
            return False
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
    status, get_text = http_request("GET", f"{base}{prefix}/id/{fid}", api_key)

    if status == 200:
        # 既存 → update。active / global / access は OWUI 側の現状を尊重 (touch しない)。
        # skill の update は SkillForm.is_active を反映してしまう (model_dump がそのまま values に
        # 入る) ので、現状の is_active を GET から echo して維持する。access_grants は body に
        # 入れない = None のまま → filter_allowed_access_grants(None)=None で access 不変。
        if kind == "skill":
            try:
                cur = json.loads(get_text)
                body = {**body, "is_active": cur.get("is_active", True)}
                # 表示 name は frontmatter に明示 title が無ければスラグの title-case になり、
                # OWUI 側の curated 名 (例 "Vancomycin TDM") を "Vancomycin Tdm" に退行させる。
                # title 明示が無いときは既存名を維持する (active/access と同じ「現状尊重」)。
                if "title" not in parse_md_frontmatter(content) and cur.get("name"):
                    body["name"] = cur["name"]
            except Exception:
                pass
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
    elif kind == "skill":
        toggle_msg = "  → active=True (form default), public (user:* read)"
    elif cfg.get("create_access_grants"):
        toggle_msg = "  → public (user:* read)"
    else:
        toggle_msg = "  ※ access は OWUI 側で要設定"
    print(f"[CREATE {kind}] {fid}  ({name}){toggle_msg}")
    return True


def discover_targets(only: set[str]) -> list[tuple[pathlib.Path, str]]:
    """owui/{filters,tools}/*.py と owui/skills/*.md を kind 付きで列挙。
    only 指定があれば filename stem でその id だけに絞る。"""
    targets: list[tuple[pathlib.Path, str]] = []
    for kind, cfg in KINDS.items():
        for f in sorted(cfg["dir"].glob(cfg["glob"])):
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
            f"対象なし (owui/filters/ owui/tools/ owui/skills/ が空、または only 指定にマッチせず)",
            file=sys.stderr,
        )
        return 1

    ok = sum(sync_one(p, kind, base_url, api_key) for p, kind in targets)
    print(f"\n{ok}/{len(targets)} synced")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())

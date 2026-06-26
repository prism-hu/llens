"""
title: Large File Gate
author: Ken Enda
version: 0.2.0
required_open_webui_version: 0.5.0
description: |
  巨大な添付ファイルの docling 抽出テキストを「丸ごと context に入れない」ための門番。

  LLENS は BYPASS_EMBEDDING_AND_RETRIEVAL=true (RAG オフ) で運用しているため、
  添付の docling 抽出テキストは要約 / チャンク化されず **全文がそのまま** プロンプトに
  注入される (middleware: chat_completion_files_handler → apply_source_context_to_messages)。
  巨大ファイルだとこれだけで context を食い潰す。

  本 filter は inlet で各添付の docling md を tiktoken で実測し、閾値 (既定 100k tokens)
  を超えたファイルだけを body['files'] / metadata['files'] から **間引く** (= その本文は
  注入されない / all-or-nothing。truncate しない)。代わりに file_id と扱い方を記した
  システム指示を 1 つ注入する。本文は消えるが Files API には残るので、モデルは
  Code Interpreter (Pyodide) で file_id から取り戻し、中身を context に出さずに
  ask_subagent (subagent tool) に委譲できる。詳しい手順は owui/skills の
  「大容量ファイル処理」を参照。

  閾値内のファイルには触れない (OWUI 標準の注入のまま)。複数添付は 1 件ずつ判定し、
  巨大なものだけ間引く。

  メモ: file_handler = True (クラス静的) にすると OWUI が全ファイルを問答無用で落とす
  (filter.py の skip_files)。それはサイズ別判定にならないので使わず、inlet で
  リストを間引く方式を採る。

changelog:
  0.2.0: 間引き発火時に skill mention `<$large-file-handling|...>` を注入し、OWUI 標準の
         skill ローダ (extract_skill_ids_from_messages、filter inlet より後段) に
         「大容量ファイル処理」skill 全文を自動ロードさせる。これまで note に「skill に従え」と
         書くだけでは skill は active+public でも注入されず (= 選択 or model 紐付け時のみ
         注入される仕様) 手順がモデルに届かなかった。note 本体はファイル事実 + mention に絞り、
         具体手順は skill 側へ寄せた (重複/ノイズ削減)。skill_mention valve で対象 skill を指定。
  0.1.0: 初版。docling md の token 数で巨大添付を間引き、file_id 告知を注入。
"""

import logging
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# tiktoken は OWUI イメージに同梱 (0.12.0)。無い環境では文字数からの概算に落とす。
try:
    import tiktoken
except Exception:  # pragma: no cover - ローカル静的解析用
    tiktoken = None

# Files API (ランタイムで解決)。v0.9.5 の get_file_by_id は async。
try:
    from open_webui.models.files import Files
except Exception:  # pragma: no cover
    Files = None


def _p(msg: str, level: str = "info") -> None:
    getattr(logger, level)(f"[large-file-gate] {msg}")


def _fmt_bytes(n: Optional[int]) -> str:
    if not n:
        return "?"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n}B"


def _iter_file_items(body: dict):
    """body['files'] と body['metadata']['files'] の添付参照を (id, name, source_list) で
    列挙する。source_list は間引き時に元リストを特定するために返す。"""
    seen: set[str] = set()
    sources = [
        body.get("files"),
        (body.get("metadata") or {}).get("files"),
    ]
    for src in sources:
        if not isinstance(src, list):
            continue
        for f in src:
            if not isinstance(f, dict):
                continue
            inner = f.get("file") or {}
            fid = f.get("id") or inner.get("id")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            name = (
                inner.get("filename")
                or f.get("name")
                or (inner.get("meta") or {}).get("name")
                or fid
            )
            yield fid, name


def _remove_ids(body: dict, ids: set[str]) -> None:
    """body['files'] / metadata['files'] から該当 id の添付を取り除く。"""

    def _filtered(lst):
        out = []
        for f in lst:
            inner = f.get("file") or {} if isinstance(f, dict) else {}
            fid = (f.get("id") if isinstance(f, dict) else None) or inner.get("id")
            if fid in ids:
                continue
            out.append(f)
        return out

    if isinstance(body.get("files"), list):
        body["files"] = _filtered(body["files"])
    md = body.get("metadata")
    if isinstance(md, dict) and isinstance(md.get("files"), list):
        md["files"] = _filtered(md["files"])


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=50,
            description="pdf_vision_router(0) の後、token_meter(100) の前で動かす",
        )
        max_tokens: int = Field(
            default=100000,
            description=(
                "docling md がこの token 数を超えたら本文を context に入れず間引く。"
                "256k context のうち単一ファイルに許容する上限の目安。"
            ),
        )
        encoding_name: str = Field(
            default="cl100k_base",
            description="tiktoken エンコーディング名 (token 実測用)",
        )
        chars_per_token_fallback: float = Field(
            default=2.0,
            description="tiktoken が使えない時に文字数から token を概算する係数 (chars/token)",
        )
        skill_mention: str = Field(
            default="large-file-handling",
            description=(
                "間引き発火時に note へ注入する skill id。OWUI が <$id|label> mention を拾って "
                "skill 全文を自動ロードする (手順をモデルに届ける本線)。空文字で無効。"
            ),
        )
        skill_label: str = Field(
            default="大容量ファイル処理",
            description="mention タグの表示ラベル (除去されモデルには出ない)",
        )
        debug: bool = Field(
            default=False, description="判定結果を status で流す (検証用)"
        )

    def __init__(self) -> None:
        # 静的 True にはしない (全ファイル一律 skip になる)。inlet で個別に間引く。
        self.file_handler = False
        self.valves = self.Valves()
        self._enc = None  # tiktoken encoding (遅延生成・再利用)

    # ------------------------------------------------------------------
    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if tiktoken is not None:
            try:
                if self._enc is None:
                    self._enc = tiktoken.get_encoding(self.valves.encoding_name)
                return len(self._enc.encode(text, disallowed_special=()))
            except Exception as e:
                _p(f"tiktoken 失敗、概算に fallback: {e!r}", level="warning")
        ratio = self.valves.chars_per_token_fallback or 1.0
        return int(len(text) / ratio)

    def _build_note(self, excluded: list[dict]) -> str:
        """間引いたファイルについてモデル宛の行動指示を組む (本文は出さない)。
        具体手順は skill 側に寄せ、ここは事実 + skill mention + 一行指示に絞る。
        mention タグ <$id|label> を含めると OWUI が skill 全文を自動ロードする
        (タグ自体は strip_skill_mentions で除去されモデルには見えない)。"""
        mention = ""
        if self.valves.skill_mention:
            mention = f" <${self.valves.skill_mention}|{self.valves.skill_label}>"
        lines = [
            f"[システム指示 / large-file-gate]{mention}",
            "以下の添付は大きすぎるため本文を context に入れていない "
            "(読めないが file_id から取得できる):",
        ]
        for e in excluded:
            lines.append(
                f"- {e['name']} (file_id={e['id']}, {e['content_type'] or '?'}, "
                f"md≈{e['tokens']} tokens, raw {_fmt_bytes(e['size'])})"
            )
        lines += [
            "",
            "中身を主 context に展開せず、注入された『大容量ファイル処理』skill の手順に従って "
            "file_id から取得 → 必要部分を抽出/分割 → ask_subagent に渡し結果だけ受け取ること。",
        ]
        return "\n".join(lines)

    def _inject_note(self, body: dict, note: str) -> None:
        """最新 user message の直前に system 指示を挿入 (前段 prefix を壊さない)。"""
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return
        insert_pos = len(messages) - 1
        if messages[insert_pos].get("role") != "user":
            insert_pos = len(messages)
        messages.insert(insert_pos, {"role": "system", "content": note})
        body["messages"] = messages

    # ------------------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
    ) -> dict:
        # global filter は inlet が例外を投げると OWUI が re-raise してチャット全体を壊す。
        # 何が起きても body をそのまま通す (fail-open)。最悪「巨大本文がそのまま入る」=
        # 元の挙動に戻るだけで、チャットは止めない。
        try:
            return await self._gate(body, __event_emitter__)
        except Exception as e:
            _p(f"inlet 失敗 → 無干渉で通過 (fail-open): {e!r}", level="error")
            return body

    async def _gate(
        self,
        body: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]],
    ) -> dict:
        if Files is None:
            return body

        candidates = list(_iter_file_items(body))
        if not candidates:
            return body

        excluded: list[dict] = []
        for fid, name in candidates:
            try:
                rec = await Files.get_file_by_id(fid)  # async (v0.9.5)
            except Exception as e:
                _p(f"{name}: get_file_by_id 失敗 → skip 判定せず通過: {e!r}", level="error")
                continue
            if not rec:
                continue
            md = (getattr(rec, "data", None) or {}).get("content") or ""
            tokens = self._count_tokens(md)
            if tokens <= self.valves.max_tokens:
                continue
            meta = getattr(rec, "meta", None) or {}
            excluded.append(
                {
                    "id": fid,
                    "name": name,
                    "tokens": tokens,
                    "content_type": meta.get("content_type"),
                    "size": meta.get("size"),
                }
            )

        if not excluded:
            return body

        _remove_ids(body, {e["id"] for e in excluded})
        self._inject_note(body, self._build_note(excluded))

        summary = ", ".join(f"{e['name']}({e['tokens']}tok)" for e in excluded)
        _p(f"間引き {len(excluded)} 件: {summary}", level="error")
        if self.valves.debug and __event_emitter__:
            try:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": (
                                f"large-file-gate: {len(excluded)} 件を context から除外 "
                                f"({summary})"
                            ),
                            "done": True,
                        },
                    }
                )
            except Exception:
                pass

        return body

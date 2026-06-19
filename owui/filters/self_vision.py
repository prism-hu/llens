"""
title: Self Vision
author: Ken Enda
version: 0.1.0
required_open_webui_version: 0.5.0
description: |
  直前の assistant ターンが BE に残した画像 (file_id) を読み戻し、次ターンの
  user メッセージに image_url として差し込む。これにより「モデルが自分の生成した
  画像を自分で見る」経路を作る。

  - 対象は assistant 本文に出た file_id だけ (matplotlib 自動ファイル化の
    /api/v1/files/<uuid> と harvest が出す file_id 行)。content_type が image/* の
    ものだけ通す。ユーザアップロード画像は OWUI が元から VLM に渡すので対象外。
  - harvest / mount 等の生成側には一切触らない。本フィルタは BE データの
    「読み戻し」consumer に徹する (harvest は汎用 stash のまま)。
  - 主モデルが画像を食えないと無意味なので、body["model"] が VLM ホワイトリストに
    一致するときだけ注入する (非一致は無言スルー)。単一モデル運用前提のため、
    Kimi K2.6 等の VLM が前面に出ているセッションでのみ通電する。

changelog:
  0.1.0: 初版。
"""

# =============================================================================
# 仕組み / 制約
# -----------------------------------------------------------------------------
# inlet は「次のリクエスト」で走る。よって生成と同一ターンの自己評価はできない
# (生成 → ユーザーが次に送って初めてモデルが画像を見る)。素の OWUI filter に
# エージェントループは無いので、これは仕様として割り切る。
#
# Files.get_file_by_id は現行 OWUI (v0.9.5) では async。await して使う
# (subagent.py の備考に準拠)。
# =============================================================================

import base64
import os
import re
import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Open WebUI 内部 API (ランタイムで解決) ---------------------------------
try:
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage
except Exception:  # ローカル静的解析用フォールバック
    Files = None
    Storage = None

# assistant 本文から file_id を拾うパターン
#   1) matplotlib 自動ファイル化 / 添付参照: /api/v1/files/<uuid>
#   2) harvest が出す行: "harvested file_id: <uuid>" / "file_id: <uuid>" 等
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_RE_FILES_URL = re.compile(r"/api/v1/files/(" + _UUID + r")")
_RE_FILE_ID = re.compile(r"file[_\s-]?id[\s:：]+[\"'`]?(" + _UUID + r")", re.IGNORECASE)


def _p(msg: str, level: str = "info"):
    getattr(logger, level)(f"[SelfVision] {msg}")


def _read_raw(rec) -> Optional[bytes]:
    """Storage 実体から生バイトを読む (subagent.py と同じ経路)。"""
    if Storage is None:
        return None
    path = getattr(rec, "path", None)
    if not path:
        return None
    try:
        local = Storage.get_file(path)
        with open(local, "rb") as f:
            return f.read()
    except Exception as e:
        _p(f"raw read failed: {e!r}", level="error")
        return None


def _text_of(content) -> str:
    """assistant content (str / parts list) から text を寄せ集める。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
        return "\n".join(out)
    return ""


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="複数 Filter が同じモデルにかかる場合の優先順位 (低いほど先)",
        )
        vlm_model_whitelist: str = Field(
            default="kimi",
            description=(
                "画像注入を有効にするモデル名 substring のカンマ区切りホワイトリスト。"
                "body['model'] がいずれかを含むときだけ注入する (大小無視)。"
            ),
        )
        max_image_mb: float = Field(
            default=8.0,
            description="1 枚あたりの上限。超えた画像はスキップ (注入しない)。",
        )
        max_images: int = Field(
            default=4,
            description="1 ターンで注入する最大枚数 (直近のものから)。",
        )
        debug: bool = Field(default=False, description="詳細ログを出す")

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------
    def _is_vlm(self, model: str) -> bool:
        m = (model or "").lower()
        wl = [s.strip().lower() for s in self.valves.vlm_model_whitelist.split(",")]
        return any(s and s in m for s in wl)

    def _extract_file_ids(self, text: str) -> list[str]:
        """本文から file_id を出現順・重複排除で拾う。"""
        seen: set = set()
        ids: list[str] = []
        for pat in (_RE_FILES_URL, _RE_FILE_ID):
            for fid in pat.findall(text):
                if fid not in seen:
                    seen.add(fid)
                    ids.append(fid)
        return ids

    def _last_assistant_text(self, messages: list) -> str:
        for m in reversed(messages):
            if m.get("role") == "assistant":
                return _text_of(m.get("content", ""))
        return ""

    def _last_user_index(self, messages: list) -> Optional[int]:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                return i
        return None

    async def _build_image_parts(self, file_ids: list[str]) -> tuple[list[dict], list[str]]:
        """file_id を解決し、image/* のものだけ image_url part にする。
        returns (parts, names)。"""
        parts: list[dict] = []
        names: list[str] = []
        limit_bytes = self.valves.max_image_mb * 1024 * 1024
        for fid in file_ids:
            if len(parts) >= self.valves.max_images:
                break
            rec = await Files.get_file_by_id(fid)
            if not rec:
                continue
            meta = getattr(rec, "meta", None) or {}
            ct = (meta.get("content_type") or "").lower()
            if not ct.startswith("image/"):
                continue
            raw = _read_raw(rec)
            if raw is None:
                continue
            if len(raw) > limit_bytes:
                _p(
                    f"skip {fid} ({len(raw)/1024/1024:.1f}MB > {self.valves.max_image_mb}MB)",
                    level="warning",
                )
                continue
            b64 = base64.b64encode(raw).decode("ascii")
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{ct};base64,{b64}"}}
            )
            names.append(getattr(rec, "filename", None) or fid)
        return parts, names

    def _inject(self, messages: list, parts: list[dict], names: list[str]) -> bool:
        idx = self._last_user_index(messages)
        if idx is None:
            _p("user メッセージが無い、注入できず", level="warning")
            return False
        existing = messages[idx].get("content", "")
        if isinstance(existing, str):
            new_content = [{"type": "text", "text": existing}] if existing else []
        elif isinstance(existing, list):
            new_content = list(existing)
        else:
            new_content = []
        new_content.append(
            {
                "type": "text",
                "text": (
                    "[直前のターンであなたが生成/退避した画像を再提示します: "
                    + ", ".join(names)
                    + "]"
                ),
            }
        )
        new_content.extend(parts)
        messages[idx]["content"] = new_content
        return True

    # ------------------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
    ) -> dict:
        try:
            if Files is None:
                return body

            model = body.get("model", "")
            if not self._is_vlm(model):
                if self.valves.debug:
                    _p(f"skip: model={model} は VLM ホワイトリスト外")
                return body

            messages = body.get("messages", [])
            if not messages:
                return body

            text = self._last_assistant_text(messages)
            if not text:
                return body

            file_ids = self._extract_file_ids(text)
            if not file_ids:
                return body

            parts, names = await self._build_image_parts(file_ids)
            if not parts:
                return body

            if self._inject(messages, parts, names):
                body["messages"] = messages
                _p(f"注入: 画像 {len(parts)} 枚 (model={model}) {names}")

            return body

        except Exception as e:
            _p(f"inlet 例外: {e!r}", level="error")
            return body

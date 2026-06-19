"""
title: Context Budget
author: Ken Enda
version: 0.1.0
required_open_webui_version: 0.5.0
description: |
  現在の会話の context 使用量・残量をモデル自身が能動的に問い合わせる tool。
  token_meter filter が毎ターン system 注入で push しているのと同じ実測値を、
  「pull」で取りに行く版。CoT や tool 連打で作業が伸び、自分がどれだけ context を
  食ったか気にしたくなった時点でモデルが呼ぶ。

  値の出どころは token_meter (SGLang の本物 usage を chat_id 単位で累積) なので、
  tiktoken 等での推定ではなく実測。本 tool は読むだけで token_meter には触らない。

changelog:
  0.1.0: 初版。
"""

# =============================================================================
# 仕組み / 制約
# -----------------------------------------------------------------------------
# tool には __request__ が inject される (__messages__ は来ない)。__request__ から
# app.state.FUNCTIONS["token_meter"] = Filter インスタンスに届き、その chat_state
# (chat_id キー) と valves.context_size を読む。
#
# 注意:
#  - 値は「直前ターン終了時点」の累積。今ターンの入力 prompt_tokens は token_meter の
#    stream 末で確定するため、tool 呼び出し時点ではまだ載っていない (やや保守的・1ターン古い)。
#    「大きいタスクを始める前のチェック」用途では十分。
#  - token_meter の id / chat_state キー形式 / valves.context_size に結合している。
#    token_meter を変えると壊れうるので、取れなければ素直に ok=False を返す (fail-soft)。
#  - context_size は token_meter の valve をそのまま使う (メーター表示と数字を一致させるため)。
#    別モデル運用で valve がズレている場合はメーター側と同じくズレる。
# =============================================================================

import logging
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_TOKEN_METER_ID = "token_meter"


def _chat_key(metadata: Optional[dict], user: Optional[dict]) -> Optional[str]:
    """token_meter._chat_key と同一ロジック (state を引くため形を合わせる)。"""
    md = metadata or {}
    chat_id = md.get("chat_id")
    if chat_id:
        return f"chat:{chat_id}"
    session_id = md.get("session_id") or ""
    user_id = (user or {}).get("id") or ""
    if session_id or user_id:
        return f"sess:{user_id}:{session_id}"
    return None


def _fmt_num(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}M"
    if n >= 1024:
        return f"{n / 1024:.1f}k"
    return str(n)


class Tools:
    class Valves(BaseModel):
        token_meter_id: str = Field(
            default=_TOKEN_METER_ID,
            description="実測値を持つ token_meter filter の id (変更時はここを合わせる)。",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def get_context_budget(
        self,
        __request__: Optional[Any] = None,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> dict:
        """現在の会話の context 使用量と残量を返す。作業 (CoT / tool 連打) が伸びて
        自分がどれだけ context を消費したか確認したいときに呼ぶ。値は直前ターン終了
        時点の実測累積 (やや保守的)。残量が少なければ、新規長尺タスクを避ける・結論を
        早めに確定する・大きい生成物は harvest する 等の判断材料にする。

        :return: {ok, used_tokens, remaining_tokens, context_size, used_pct, note} /
                 取得不能時は {ok: False, error}
        """
        if __request__ is None:
            return {"ok": False, "error": "__request__ が無い (実行環境を確認)。"}

        try:
            functions = getattr(__request__.app.state, "FUNCTIONS", None) or {}
        except Exception as e:
            return {"ok": False, "error": f"app.state.FUNCTIONS に届かない: {e!r}"}

        tm = functions.get(self.valves.token_meter_id)
        if tm is None or not hasattr(tm, "chat_state"):
            return {
                "ok": False,
                "error": (
                    f"token_meter ({self.valves.token_meter_id}) が読めない。"
                    "未ロード / id 不一致 / 構造変更の可能性。"
                ),
            }

        key = _chat_key(__metadata__, __user__)
        state = tm.chat_state.get(key) if key else None
        if not state:
            return {
                "ok": False,
                "error": "この会話の usage がまだ無い (初回ターンや state 未生成)。",
            }

        context_size = int(getattr(tm.valves, "context_size", 0) or 0)
        used = int(state.get("in", 0)) + int(state.get("out", 0))
        remaining = max(0, context_size - used) if context_size > 0 else 0
        pct = (used / context_size * 100.0) if context_size > 0 else 0.0

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": (
                            f"context: {pct:.1f}% 使用 "
                            f"({_fmt_num(used)}/{_fmt_num(context_size)}, "
                            f"残 {_fmt_num(remaining)})"
                        ),
                        "done": True,
                    },
                }
            )

        return {
            "ok": True,
            "used_tokens": used,
            "remaining_tokens": remaining,
            "context_size": context_size,
            "used_pct": round(pct, 1),
            "note": (
                "直前ターン終了時点の実測累積。今ターンの入力分は未反映のためやや保守的。"
            ),
        }

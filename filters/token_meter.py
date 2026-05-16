"""
title: Token Meter
author: LLENS
version: 1.3.1
required_open_webui_version: 0.5.0
description: |
  SGLang から返ってくる本物の usage を使って、会話全体の context 使用率を表示する。

  表示:
      🟢 4.2% [█░░░░░░░] | 11.0k/262k | IN 10.0k / OUT 1.0k

  集計 (会話累積):
      in (IN)   = 最新の prompt_tokens
                  (最後の SGLang 呼び出しの入力 = 会話全体の入力累積)
      out (OUT) = 全 completion_tokens の累積 (state 保持)
      total     = in + out

  - inlet で 0 リセットしない (会話累積を維持)
  - inlet で stream_options.include_usage=True を注入
  - stream で usage を捕捉、status を都度更新
  - outlet で最後に同じ状態を確定打として再 emit (stream 末端の emit が漏れることがあるため)

  注意: Filter インスタンスは OpenWebUI が会話ごとに分けない可能性あり。
  複数会話が並行すると累積がズレるので、会話 ID で分けて保持する。

changelog:
  1.3.1: outlet の key 取得バグ修正。outlet の body は response 側で chat_id 構造が
         違い、_chat_key で別キーになって空 state を生成 → 0% で上書きしていた。
         inlet で確定した current_key を使う。state が空なら emit しない。
  1.3.0: ゲージ表記 ([█░░░]) と IN/OUT ラベルに変更。医療現場向けに視認性改善
  1.2.0: 会話累積に切り替え。会話 ID で out_累積を分けて保持
  1.1.0: in/out をユーザ視点で正確に
  1.0.0: 本物の usage
"""

import logging
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _bar(pct: float, length: int = 8) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(length * pct / 100.0))
    return "[" + "█" * filled + "░" * (length - filled) + "]"


def _signal(pct: float) -> str:
    if pct >= 90:
        return "🔴"
    if pct >= 75:
        return "🟠"
    if pct >= 50:
        return "🟡"
    return "🟢"


def _build(
    in_tokens: int,
    out_tokens: int,
    context_size: int,
    bar_length: int,
) -> str:
    total = in_tokens + out_tokens
    pct = (total / context_size * 100.0) if context_size > 0 else 0.0
    sig = _signal(pct)
    bar = _bar(pct, bar_length)
    in_out = f"IN {_fmt_num(in_tokens)} / OUT {_fmt_num(out_tokens)}"
    total_str = f"{_fmt_num(total)}/{_fmt_num(context_size)}"
    return f"{sig} {pct:.1f}% {bar} | {total_str} | {in_out}"


def _chat_key(body: dict, user: Optional[dict]) -> str:
    """会話を識別するキー。chat_id があればそれ、なければ user+session で代用。"""
    chat_id = body.get("chat_id")
    if chat_id:
        return f"chat:{chat_id}"
    session_id = body.get("session_id") or ""
    user_id = (user or {}).get("id") or ""
    return f"sess:{user_id}:{session_id}"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=100, description="他 filter より後に動かす")
        context_size: int = Field(
            default=262144,
            description="このモデルの context window (Kimi K2.6 = 262144)",
        )
        bar_length: int = Field(default=8, description="バーのマス数")

    def __init__(self):
        self.file_handler = False
        self.valves = self.Valves()
        # 会話ごとの累積 (chat_id → 状態)
        # state: {"in": int, "out": int, "prev_prompt": int|None, "prev_completion": int|None}
        self.chat_state: dict[str, dict] = {}
        # 今アクティブな会話のキー (stream / outlet で参照する)
        self.current_key: Optional[str] = None
        self.event_emitter: Optional[Callable[[Any], Awaitable[None]]] = None
        logger.error("[TokenMeter] __init__ v1.3.1")

    async def _emit(self, description: str):
        if self.event_emitter is None:
            return
        try:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {"description": description, "done": True},
                }
            )
        except Exception as e:
            logger.error(f"[TokenMeter] emit FAIL: {e!r}")

    def _get_state(self, key: str) -> dict:
        if key not in self.chat_state:
            self.chat_state[key] = {
                "in": 0,
                "out": 0,
                "prev_prompt": None,
                "prev_completion": None,
            }
        return self.chat_state[key]

    # --------------------------------------------------------
    # inlet
    # --------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        self.event_emitter = __event_emitter__
        self.current_key = _chat_key(body, __user__)
        state = self._get_state(self.current_key)

        # SGLang に usage を返させる
        stream_options = body.get("stream_options") or {}
        if not isinstance(stream_options, dict):
            stream_options = {}
        stream_options["include_usage"] = True
        body["stream_options"] = stream_options

        # ターン間の差分計算用に prev はリセットしておく
        # (前ターンの最終 prompt/completion は今ターンの差分計算には使わない)
        state["prev_prompt"] = None
        state["prev_completion"] = None

        # 累積 in/out は維持。表示は前ターン終了時の値で開始
        description = _build(
            state["in"],
            state["out"],
            self.valves.context_size,
            self.valves.bar_length,
        )
        await self._emit(description)
        logger.error(
            f"[TokenMeter] inlet key={self.current_key} "
            f"in={state['in']} out={state['out']}"
        )
        return body

    # --------------------------------------------------------
    # stream
    # --------------------------------------------------------
    def stream(self, event: dict) -> dict:
        if self.current_key is None:
            return event

        usage = None
        try:
            usage = event.get("usage")
            if usage is None:
                choices = event.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    usage = choices[0].get("usage")
        except Exception as e:
            logger.error(f"[TokenMeter] stream 例外: {e!r}")
            return event

        if not isinstance(usage, dict):
            return event

        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if not isinstance(prompt, int) or not isinstance(completion, int):
            return event

        state = self._get_state(self.current_key)

        # in: 最新の prompt_tokens がそのまま「会話の入力累積」
        # ただし最初の prompt にはターン N-1 までの全 out も含まれているので、
        # 「真のユーザ入力 in」は prompt - 累積 out になる。
        # state["out"] が前ターンまでの累積、その上で今ターン分を加算していく。
        if state["prev_prompt"] is None:
            # 今ターン最初の usage
            # in は「prompt - 既存の累積 out」が「会話全体の真のユーザ入力」
            new_in = prompt - state["out"]
            if new_in < state["in"]:
                # 履歴トリミング等で小さくなる場合は前回値を尊重
                new_in = state["in"]
            state["in"] = new_in
        else:
            # 同一ターン内 2 回目以降 (tool 呼び出し): tool 結果分の増分を足す
            in_delta = prompt - (state["prev_prompt"] + (state["prev_completion"] or 0))
            if in_delta > 0:
                state["in"] += in_delta

        # out: completion を累積
        state["out"] += completion

        state["prev_prompt"] = prompt
        state["prev_completion"] = completion

        description = _build(
            state["in"],
            state["out"],
            self.valves.context_size,
            self.valves.bar_length,
        )

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._emit(description))
        except RuntimeError:
            pass

        logger.error(
            f"[TokenMeter] key={self.current_key} "
            f"prompt={prompt} completion={completion} "
            f"→ in={state['in']} out={state['out']}"
        )
        return event

    # --------------------------------------------------------
    # outlet (確定打)
    # --------------------------------------------------------
    async def outlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        self.event_emitter = __event_emitter__

        # outlet の body は response 側で chat_id を含まないことがあり、
        # _chat_key で再計算すると別キーになって新規空 state を作って 0% で上書きしてしまう。
        # inlet で確定した current_key を使う。
        if self.current_key is None:
            return body
        state = self.chat_state.get(self.current_key)
        if state is None:
            return body

        description = _build(
            state["in"],
            state["out"],
            self.valves.context_size,
            self.valves.bar_length,
        )
        await self._emit(description)
        return body

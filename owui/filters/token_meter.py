"""
title: Token Meter
author: Ken Enda
version: 1.7.1
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

  重要: OWUI は Filter インスタンスをプロセス全体で共有する (app.state.FUNCTIONS の
  singleton)。self に request-scoped な状態 (current chat_id, event_emitter) を
  持たせると並行リクエストで他チャット/他ユーザーの値で上書きされる。
  すべての handler は __metadata__ と __event_emitter__ を引数で受け取り、self には
  chat_id でキーされた純粋な累積 state (chat_state dict) のみを置く。

changelog:
  1.7.1: default warn_levels を 25% / 50% / 75% の 3 段に変更 (旧: 50% / 80%)。
         25% で密度意識、50% で簡潔指示、75% で新規長尺タスク抑止 + 別チャット分割提案。
  1.7.0: 単一閾値 warn_threshold_pct を warn_levels: list[WarnLevel(pct, message)] に
         一般化。pct と注入メッセージを 1 ペアで持ち、任意段数の閾値を定義可能。
         message はユーザー向け文言ではなく
         「モデルに対する行動指示」として書き直し (簡潔応答指示、新規長尺タスク抑止 等)。
         同ターンで複数閾値を跨いだ場合は最高位だけ発火・低位は済み扱い (ノイズ防止)、
         各 pct を下回れば個別リセット → 次回超過で再警告。空配列で機能無効。
         加えて debug_inject_context valve (default True) を新設し、毎 inlet で現在の
         context 使用率を system message として注入する debug 経路を追加。モデルが
         system 注入を実際に読んでるかを検証するための一時的なライン (確認後 OFF 推奨)。
  1.6.0: 1) _fmt_num を 1024 ベースに変更 (262144 → "256.0k")。
         2) context 使用率が閾値 (default 75%) を初めて超えたターンで、一度だけ
            system message を注入してモデル自身に context 逼迫を知らせる。
            注入位置は最新 user message の直前 (前段 prefix を破壊せず prompt
            cache を温存)。閾値を下回ったら warned フラグをリセットして次回再警告。
  1.5.0: inlet 時のみ末尾に「計算中」を出して、これがトークン使用量インジケータで
         あることをユーザに気付かせる。stream/outlet で本来の数値表示に置換。
  1.4.0: 並行リクエスト時のセッション間漏洩を修正。Filter は OWUI singleton で共有
         される (app.state.FUNCTIONS) ため self.current_key / self.event_emitter
         に request 単位の値を保持すると、別ユーザーの WS に他チャットの数値を
         emit したり、stream() が違うチャットの state を更新したりしていた。
         全 handler を __metadata__ / __event_emitter__ 引数受け取りに変更。
  1.3.1: outlet の key 取得バグ修正。outlet の body は response 側で chat_id 構造が
         違い、_chat_key で別キーになって空 state を生成 → 0% で上書きしていた。
         inlet で確定した current_key を使う。state が空なら emit しない。
  1.3.0: ゲージ表記 ([█░░░]) と IN/OUT ラベルに変更。医療現場向けに視認性改善
  1.2.0: 会話累積に切り替え。会話 ID で out_累積を分けて保持
  1.1.0: in/out をユーザ視点で正確に
  1.0.0: 本物の usage
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _fmt_num(n: int) -> str:
    # 1024 ベース。262144 (= 256 * 1024) を "256.0k" と表示するため。
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}M"
    if n >= 1024:
        return f"{n / 1024:.1f}k"
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


def _build_inlet(
    in_tokens: int,
    out_tokens: int,
    context_size: int,
    bar_length: int,
) -> str:
    # 初回ターン: 数値が無いので「計算中」だけを出す。
    # 継続ターン: 前ターンまでの累計 + 末尾に「計算中…」を付けて、
    #            このステータスがトークン使用量メーターであることを示す。
    if in_tokens == 0 and out_tokens == 0:
        return "⏳ トークン使用量を計算中…"
    base = _build(in_tokens, out_tokens, context_size, bar_length)
    return f"{base} … 計算中"


def _chat_key(metadata: Optional[dict], user: Optional[dict]) -> Optional[str]:
    """会話を識別するキー。chat_id があればそれ、無ければ user+session で代用。
    どちらも無ければ None (state を持てないので no-op)。"""
    md = metadata or {}
    chat_id = md.get("chat_id")
    if chat_id:
        return f"chat:{chat_id}"
    session_id = md.get("session_id") or ""
    user_id = (user or {}).get("id") or ""
    if session_id or user_id:
        return f"sess:{user_id}:{session_id}"
    return None


async def _emit(
    event_emitter: Optional[Callable[[Any], Awaitable[None]]],
    description: str,
) -> None:
    if event_emitter is None:
        return
    try:
        await event_emitter(
            {
                "type": "status",
                "data": {"description": description, "done": True},
            }
        )
    except Exception as e:
        logger.error(f"[TokenMeter] emit FAIL: {e!r}")


class WarnLevel(BaseModel):
    pct: float = Field(description="閾値 (%)。この%を初めて超えたターンに message を 1 度注入")
    message: str = Field(default="", description="注入する system message 本文。空文字なら注入せず通過のみ")


_DEFAULT_LEVELS: list[WarnLevel] = [
    WarnLevel(
        pct=25.0,
    ),
    WarnLevel(
        pct=50.0,
        message=(
            "contextにまだ余裕はあるが前提の再掲を避け回答の密度を意識すること。"
        ),
    ),
    WarnLevel(
        pct=75.0,
        message=(
            "上限到達が近い。新しい長尺タスクは開始せず、現ターンで保存すべき結論・"
            "状態・コード差分を明示すること。継続作業が必要ならユーザーに別チャットへの分割を促すこと。"
        ),
    ),
]


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=100, description="他 filter より後に動かす")
        context_size: int = Field(
            default=262144,
            description="このモデルの context window (Kimi K2.6 = 262144)",
        )
        bar_length: int = Field(default=8, description="バーのマス数")
        warn_levels: list[WarnLevel] = Field(
            default_factory=lambda: list(_DEFAULT_LEVELS),
            description=(
                "context 使用率の閾値とメッセージのペア。"
                "昇順に評価し、同ターンで複数跨いだら最高位だけ発火 (低位は済み扱い)。"
                "各 pct を下回れば個別リセットされ次回超過で再警告。空配列で機能無効。"
            ),
        )
        debug_inject_context: bool = Field(
            default=True,
            description=(
                "デバッグ用: 毎 inlet で現在の context 使用率を system message として注入する。"
                "モデルが system message を読んでるか検証する目的、不要になったら OFF。"
            ),
        )

    def __init__(self):
        self.file_handler = False
        self.valves = self.Valves()
        # 会話ごとの累積 (chat_id → 状態)。
        # OWUI singleton なので全 user/全 chat で共有されるが、key が chat_id なので
        # ここに値を入れる/読む分には他チャットを汚染しない。
        # state: {"in": int, "out": int, "prev_prompt": int|None, "prev_completion": int|None,
        #         "emitter": Callable|None, "warned": set[float]}
        # emitter は stream() (sync) から最新 emit 先を引くために key 単位で保持する。
        # warned は超過 system 注入を 1 度だけにするための、発火済 pct 値の集合。
        self.chat_state: dict[str, dict] = {}
        logger.error("[TokenMeter] __init__ v1.7.1")

    def _get_state(self, key: str) -> dict:
        if key not in self.chat_state:
            self.chat_state[key] = {
                "in": 0,
                "out": 0,
                "prev_prompt": None,
                "prev_completion": None,
                "emitter": None,
                "warned": set(),
            }
        return self.chat_state[key]

    def _maybe_inject_warning(self, body: dict, state: dict) -> None:
        levels = [lvl for lvl in (self.valves.warn_levels or []) if lvl.pct > 0]
        context_size = self.valves.context_size
        if not levels or context_size <= 0:
            return
        total = state["in"] + state["out"]
        pct = total / context_size * 100.0

        # 下回った閾値は warned から除外して、次回超過で再警告できるよう
        state["warned"] = {t for t in state["warned"] if pct >= t}

        # 昇順に並べ、最高位の「超過 & 未警告 & message あり」を 1 つだけ発火。
        # message が空の閾値はマーカー扱いで注入対象にしない (高位発火時の包含で warned だけはされる)。
        sorted_levels = sorted(levels, key=lambda lvl: lvl.pct)
        fired: Optional[WarnLevel] = None
        for lvl in reversed(sorted_levels):
            if pct >= lvl.pct and lvl.pct not in state["warned"] and lvl.message:
                fired = lvl
                break
        if fired is None:
            return

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return

        remaining = max(0, context_size - total)
        # モデル宛の指示としてマーカーを明示し、context メタ情報を続ける。
        # ユーザー向け文言ではなく、モデルが従うべき行動指針を message に書く。
        warning = (
            f"[システム指示] context 使用率 {pct:.1f}% "
            f"(閾値 {fired.pct:.0f}% 超過、残り約 {_fmt_num(remaining)} トークン)。"
            f"{fired.message}"
        )

        # 最新 user message の直前に挿入。前段の prefix を破壊しないので prompt cache が温存される。
        insert_pos = len(messages) - 1
        if messages[insert_pos].get("role") != "user":
            insert_pos = len(messages)
        messages.insert(insert_pos, {"role": "system", "content": warning})
        body["messages"] = messages

        # 高位発火時は同ターンの低位通知を包含する (2 通連投しない)
        state["warned"].update(
            {lvl.pct for lvl in sorted_levels if lvl.pct <= fired.pct}
        )
        logger.error(
            f"[TokenMeter] WARN injected pct={pct:.1f} fired_threshold={fired.pct:.0f}"
        )

    def _inject_context_debug(self, body: dict, state: dict) -> None:
        """毎 inlet で現在の token usage を system message として注入する debug 経路。
        モデルが system 注入を実際に読んでるかを検証するため、threshold warning とは別ラインで
        常時流す。Valves.debug_inject_context が False なら no-op。"""
        if not self.valves.debug_inject_context:
            return
        context_size = self.valves.context_size
        if context_size <= 0:
            return
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return

        total = state["in"] + state["out"]
        pct = total / context_size * 100.0
        msg = (
            f"[context-status] in={state['in']} out={state['out']} "
            f"total={total}/{context_size} ({pct:.2f}%) "
            f"[human: in={_fmt_num(state['in'])} out={_fmt_num(state['out'])} "
            f"total={_fmt_num(total)}/{_fmt_num(context_size)}]"
        )
        insert_pos = len(messages) - 1
        if messages[insert_pos].get("role") != "user":
            insert_pos = len(messages)
        messages.insert(insert_pos, {"role": "system", "content": msg})
        body["messages"] = messages
        logger.error(f"[TokenMeter] context-status injected: {msg}")

    # --------------------------------------------------------
    # inlet
    # --------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
    ) -> dict:
        # SGLang に usage を返させる (state の有無に関わらず実行)
        stream_options = body.get("stream_options") or {}
        if not isinstance(stream_options, dict):
            stream_options = {}
        stream_options["include_usage"] = True
        body["stream_options"] = stream_options

        key = _chat_key(__metadata__, __user__)
        if key is None:
            return body

        state = self._get_state(key)

        # 次ターンの差分計算用に prev はリセット
        state["prev_prompt"] = None
        state["prev_completion"] = None

        # stream() (sync) から後で参照するため emitter を chat key 単位で保持
        state["emitter"] = __event_emitter__

        # 閾値超過なら system 注入 (一度だけ)
        self._maybe_inject_warning(body, state)

        # debug: 毎ターン現在の context 使用率を system 注入 (valve で OFF 可)
        self._inject_context_debug(body, state)

        description = _build_inlet(
            state["in"],
            state["out"],
            self.valves.context_size,
            self.valves.bar_length,
        )
        await _emit(__event_emitter__, description)
        logger.error(
            f"[TokenMeter] inlet key={key} in={state['in']} out={state['out']}"
        )
        return body

    # --------------------------------------------------------
    # stream
    # --------------------------------------------------------
    def stream(
        self,
        event: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
    ) -> dict:
        key = _chat_key(__metadata__, __user__)
        if key is None:
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

        state = self._get_state(key)

        # in: 最新の prompt_tokens がそのまま「会話の入力累積」
        # ただし最初の prompt にはターン N-1 までの全 out も含まれているので、
        # 「真のユーザ入力 in」は prompt - 累積 out になる。
        # state["out"] が前ターンまでの累積、その上で今ターン分を加算していく。
        if state["prev_prompt"] is None:
            # 今ターン最初の usage
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

        # stream() は sync のため emit は background task に逃がす。
        # 優先順位: 呼び出し時に渡された emitter > inlet で保存した emitter
        emitter = __event_emitter__ or state.get("emitter")
        if emitter is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_emit(emitter, description))
            except RuntimeError:
                pass

        logger.error(
            f"[TokenMeter] key={key} prompt={prompt} completion={completion} "
            f"→ in={state['in']} out={state['out']}"
        )
        return event

    # --------------------------------------------------------
    # outlet (確定打)
    # --------------------------------------------------------
    async def outlet(
        self,
        body: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
    ) -> dict:
        key = _chat_key(__metadata__, __user__)
        if key is None:
            return body
        state = self.chat_state.get(key)
        if state is None:
            # inlet を踏んでいない (state 空) なら確定打は出さない
            return body

        description = _build(
            state["in"],
            state["out"],
            self.valves.context_size,
            self.valves.bar_length,
        )
        await _emit(__event_emitter__, description)
        return body


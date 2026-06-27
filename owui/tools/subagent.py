"""
title: Subagent
author: Ken Enda
version: 0.3.0
required_open_webui_version: 0.5.0
description: 巨大 / 重い資料を主コンテキストに展開せず、file_id 経由で別 context の
             サブエージェントに読ませて結果だけ返す tool 群。
             テキスト資料は本文注入、画像は VLM に image_url で渡す (vision トークンを
             subagent 側に隔離)。モデルは :8000 に今出ているものを自動使用する。

changelog:
  0.3.0: 会話継続対応。ask_subagent 1 ツールで新規/継続を兼ねる
         (file_id で新規、thread_id で継続)。どちらでも thread_id を返すので、続けたければ
         それを渡し続けるだけ。「one-shot」は続けなかった thread に過ぎず TTL で自動消滅。
         - 会話履歴を Redis に thread_id で保持し、追い質問のたびに復元→積み直し→再推論。
           主コンテキストに出るのは thread_id と短い answer だけ (資料も履歴も Redis に隔離)。
         - Redis = 会話履歴そのもの。資料は初回に history へ一度入るだけ。毎ターン同じ prefix を
           送るので SGLang prefix cache が効き、再注入コストは prefill 側で吸収される。
         - 揮発 Redis + TTL スライディング (ターン毎に延長、放置 thread は自動 GC)。
         - text/image どちらもスレッド化。モデルは初回のものに固定 (途中の切替で文脈が壊れない)。
  0.2.0: ask_subagent を追加 (片道 / one-shot)。file_id + 指示 → 要約を返す本体。
         - content_type で分岐: image/* は生バイトを base64 data URL で image_url 送信、
           それ以外は data.content (docling 抽出) → 無ければ text 系のみ raw decode。
         - モデルは /v1/models で live モデルを自動取得 (単一モデル運用前提)。
           Kimi 等 VLM 稼働時は画像可、text-only モデル時は画像エラーで弾く。
         - SGLang OpenAI 互換 endpoint を backend から直接叩く (OWUI pipeline を通らない
           = 再帰なしの片道を物理的に担保)。base_url / key は OWUI の env を既定値に流用。
         - inspect_artifact の content 読みを _read_content に共通化。binary は
           無理に decode せず None を返す (garbage をモデルに食わせない)。
  0.1.0: 初版。harvest 疎通確認用 inspect_artifact のみ。
         Pyodide が POST /api/v1/files/ で push した file_id を backend (Files API /
         Storage) から読み戻せるか確認する最小 tool。

備考: open_webui v0.9.5 の Files.get_file_by_id は async (await 必須)。
"""

# =============================================================================
# 背景 (なぜ backend tool でファイルを読むのか)
# -----------------------------------------------------------------------------
# 想定: Pyodide で巨大な中間生成物を作った / 重い画像を読みたい とき、全部を主モデルの
# context に展開すると圧迫する (画像はターン跨ぎで vision トークンが居座る)。そこで:
#   1. 資料を BE に置く (Pyodide 生成物は harvest=POST /api/v1/files/、画像等は通常の添付)
#   2. 主コンテキストに出るのは file_id だけ
#   3. この tool が backend 側で中身を読み、別 context のサブエージェントに渡して
#      要約・解釈だけ返す (元の中身は主 context に展開されない)
# backend は :8000 の live モデルを直接叩く。OWUI の filter/tool pipeline を通らないので
# サブエージェントが更に tool を呼ぶ等の再帰は起きない (= 片道 / one-shot)。
# =============================================================================

import base64
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Open WebUI 内部 API (ランタイムで解決) ---------------------------------
try:
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage
except Exception:  # ローカル静的解析用フォールバック
    Files = None
    Storage = None

# --- 会話スレッド永続化 (Redis) --------------------------------------------
try:
    import redis.asyncio as aioredis
except Exception:  # ローカル静的解析用フォールバック
    aioredis = None

_THREAD_KEY = "subagent:thread:"  # Redis key prefix (+ thread_id)

# text として decode してよい content_type (これ以外の binary は decode しない)
_TEXT_CT_PREFIXES = ("text/",)
_TEXT_CT_EXACT = {"application/json", "application/xml", "application/csv"}


def _read_raw(rec) -> Optional[bytes]:
    """Storage 実体から生バイトを読む。"""
    if Storage is None:
        return None
    path = getattr(rec, "path", None)
    if not path:
        return None
    try:
        local = Storage.get_file(path)  # ローカル fs パスを返す
        with open(local, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[subagent] raw read failed: {e!r}")
        return None


def _is_text_ct(ct: str) -> bool:
    ct = (ct or "").lower()
    return (
        any(ct.startswith(p) for p in _TEXT_CT_PREFIXES)
        or ct in _TEXT_CT_EXACT
        or ct.endswith("+json")
        or ct.endswith("+xml")
        or ct.endswith("csv")
    )


def _read_content(rec) -> tuple[Optional[str], str]:
    """テキストとして読める中身を返す。(content, source)。
    1) docling 抽出テキスト (PDF/Office はここに入る) を最優先
    2) 無ければ content_type が text 系のときだけ raw を decode
    3) それ以外 (binary / 抽出未完) は None (無理に decode しない)
    """
    content = (getattr(rec, "data", None) or {}).get("content")
    if content:
        return content, "data.content"
    ct = (getattr(rec, "meta", None) or {}).get("content_type") or ""
    if _is_text_ct(ct):
        raw = _read_raw(rec)
        if raw is not None:
            return raw.decode("utf-8", "replace"), "storage.raw"
    return None, "none"


_SUBAGENT_SYSTEM = (
    "あなたは特定の資料を任されたサブエージェントです。主エージェントから資料に関する指示が"
    "届きます (会話が続く場合はこれまでの履歴も保持されています)。最初に渡された資料に基づき、"
    "各指示に対して結論と根拠を簡潔に返してください。資料に無いことは推測せず『資料からは不明』"
    "と述べること。ツールは使えません。"
)


class Tools:
    class Valves(BaseModel):
        model_base_url: str = Field(
            default_factory=lambda: os.getenv(
                "OPENAI_API_BASE_URL", "http://host.docker.internal:8000/v1"
            ),
            description="SGLang OpenAI 互換 endpoint。既定は OWUI の env を流用。",
        )
        model_api_key: str = Field(
            default_factory=lambda: os.getenv("OPENAI_API_KEY", "EMPTY"),
            description="endpoint の API key。SGLang は通常 EMPTY。",
        )
        subagent_model: str = Field(
            default="",
            description="サブエージェントが使うモデル名。空なら /v1/models の live モデルを自動使用。",
        )
        max_input_chars: int = Field(
            default=100000,
            description="テキスト資料の注入上限 (超過分は頭から切って truncated=True)",
        )
        max_image_mb: float = Field(
            default=8.0, description="画像 (image/*) を VLM に渡す際の上限サイズ"
        )
        temperature: float = Field(default=0.3, description="サブエージェントの temperature")
        timeout_s: int = Field(default=300, description="推論タイムアウト (秒)")
        head_chars: int = Field(
            default=800, description="inspect_artifact が返すプレビュー文字数"
        )
        thread_ttl_s: int = Field(
            default=3600,
            description="会話スレッドの TTL (秒)。ターン毎に延長 (スライディング)。",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self._redis = None  # aioredis client (遅延生成・再利用)

    # =========================================================================
    # 共通: 推論コア / 会話スレッド永続化 (Redis)
    # =========================================================================
    async def _chat(self, messages: list, model: str = "") -> tuple[str, str]:
        """messages を :8000 に投げ (answer, 使用model) を返す。model 未指定なら
        /v1/models の live モデルを自動採用 (単一モデル運用前提)。
        例外はそのまま上げる (呼び出し側で整形)。"""
        base = self.valves.model_base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {self.valves.model_api_key}"}
        async with httpx.AsyncClient(timeout=self.valves.timeout_s) as client:
            if not model:
                mr = await client.get(f"{base}/models", headers=headers)
                mr.raise_for_status()
                data = (mr.json() or {}).get("data", [])
                if not data:
                    raise RuntimeError(":8000 に live モデルが無い")
                model = data[0]["id"]
            resp = await client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": self.valves.temperature,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"], model

    async def _get_redis(self):
        if aioredis is None:
            raise RuntimeError("redis.asyncio を解決できない (イメージに redis-py が無い)")
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.valves.redis_url, decode_responses=True
            )
        return self._redis

    async def _save_thread(self, tid: str, rec: dict) -> None:
        """会話履歴を thread_id で保存。ex で TTL をターン毎に張り直す (スライディング)。"""
        r = await self._get_redis()
        await r.set(_THREAD_KEY + tid, json.dumps(rec), ex=self.valves.thread_ttl_s)

    async def _load_thread(self, tid: str) -> Optional[dict]:
        r = await self._get_redis()
        raw = await r.get(_THREAD_KEY + tid)
        return json.loads(raw) if raw else None

    # =========================================================================
    # 疎通確認: backend が file_id の中身を読めるか
    # =========================================================================
    async def inspect_artifact(
        self,
        file_id: str,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> dict:
        """指定 file_id の資料を backend 側から読み、メタ情報と先頭プレビューを返す。
        中身全体は返さない (主コンテキスト保護)。harvest 経路の疎通確認に使う。

        :param file_id: OWUI file_id (UUID)
        :return: {found, filename, content_type, size_bytes, content_source, content_chars, head}
        """
        if Files is None:
            return {"error": "open_webui 内部 API を解決できない (実行環境を確認)"}

        rec = await Files.get_file_by_id(file_id)  # async API: await 必須
        if not rec:
            return {"found": False, "file_id": file_id, "error": "該当 file_id のレコードが無い"}

        meta = getattr(rec, "meta", None) or {}
        content, source = _read_content(rec)
        content = content or ""
        head = content[: self.valves.head_chars]

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": (
                            f"inspect_artifact: {getattr(rec, 'filename', '?')} "
                            f"({len(content)} chars via {source})"
                        ),
                        "done": True,
                    },
                }
            )

        return {
            "found": True,
            "file_id": file_id,
            "filename": getattr(rec, "filename", None),
            "content_type": meta.get("content_type"),
            "size_bytes": meta.get("size"),
            "content_source": source,
            "content_chars": len(content),
            "head": head,
        }

    # =========================================================================
    # 本体: 資料をサブエージェントに読ませて結果を返す。1 ツールで新規/継続を兼ねる。
    #   - file_id を渡す  → 新規。資料を読ませて答える
    #   - thread_id を渡す → 継続。前回の資料・会話文脈のまま追い質問
    # どちらでも thread_id を返すので、続けたければそれを渡し続けるだけ
    # (「one-shot」は続けなかった thread に過ぎず TTL で勝手に消える)。
    # 資料の中身も履歴も Redis 側に隔離され、主コンテキストには出ない。
    # =========================================================================
    async def ask_subagent(
        self,
        instruction: str,
        file_id: str = "",
        thread_id: str = "",
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> dict:
        """資料を別 context のサブエージェントに読ませ、instruction を遂行した結果だけ返す。
        資料の中身は主コンテキストに展開されない。返り値の thread_id を次回 thread_id に
        渡せば、同じ資料・同じ会話文脈のまま追い質問できる (履歴は backend の Redis 保持)。

        - 新規: file_id を渡す。text/PDF/Office は抽出テキスト、image/* は VLM に画像送信。
        - 継続: 前回返ってきた thread_id を渡す (file_id 不要、instruction だけ更新)。
        どちらの呼び方でも thread_id が返る。会話を続けたければそれを渡し続けるだけ。

        :param instruction: サブエージェントへの指示 (主モデルが都度組む)
        :param file_id: 新規に読ませる資料の OWUI file_id (UUID)。継続時は省略。
        :param thread_id: 継続したい会話の thread_id。新規時は省略。
        :return: {ok, answer, thread_id, model, turns, mode?, filename?, truncated?, error?}
        """

        async def _emit(msg: str, done: bool) -> None:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": msg, "done": done}}
                )

        # =====================================================================
        # 継続: Redis から履歴を復元 → instruction を積んで再推論 → 保存
        # モデルは初回のものに固定 (途中のモデル切替で文脈が壊れないため)
        # =====================================================================
        if thread_id:
            try:
                rec = await self._load_thread(thread_id)
            except Exception as e:
                return {"ok": False, "error": f"thread 復元失敗 (redis): {e!r}"}
            if not rec:
                return {
                    "ok": False,
                    "error": (
                        f"thread_id {thread_id} が無い (TTL 切れ or 誤り)。"
                        "file_id を渡して開き直すこと。"
                    ),
                }
            messages = rec["messages"]
            model = rec.get("model", "")
            messages.append({"role": "user", "content": instruction})

            await _emit(f"subagent 継続: {thread_id}", False)
            try:
                answer, model = await self._chat(messages, model=model)
            except Exception as e:
                return {"ok": False, "error": f"推論失敗: {e!r}"}

            messages.append({"role": "assistant", "content": answer})
            try:
                await self._save_thread(thread_id, {"model": model, "messages": messages})
            except Exception as e:
                return {"ok": False, "error": f"thread 保存失敗 (redis): {e!r}"}

            turns = sum(1 for m in messages if m.get("role") == "assistant")
            await _emit(f"subagent 継続 完了: {thread_id} (turn {turns})", True)
            return {
                "ok": True,
                "answer": answer,
                "thread_id": thread_id,
                "model": model,
                "turns": turns,
            }

        # =====================================================================
        # 新規: file_id の資料を読み込み、スレッドを開く
        # =====================================================================
        if not file_id:
            return {"ok": False, "error": "file_id か thread_id のどちらかが必須"}
        if Files is None:
            return {"ok": False, "error": "open_webui 内部 API を解決できない"}

        rec = await Files.get_file_by_id(file_id)
        if not rec:
            return {"ok": False, "error": f"file_id {file_id} のレコードが無い"}

        meta = getattr(rec, "meta", None) or {}
        ct = (meta.get("content_type") or "").lower()
        filename = getattr(rec, "filename", None)

        # --- メッセージ構築 (text / vision) ---
        truncated = False
        if ct.startswith("image/"):
            raw = _read_raw(rec)
            if raw is None:
                return {"ok": False, "error": "画像の実体を読めない (Storage 解決失敗)"}
            if len(raw) > self.valves.max_image_mb * 1024 * 1024:
                return {
                    "ok": False,
                    "error": f"画像が大きすぎる ({len(raw)/1024/1024:.1f}MB > "
                    f"{self.valves.max_image_mb}MB)。リサイズしてから渡すこと。",
                }
            b64 = base64.b64encode(raw).decode("ascii")
            data_url = f"data:{ct};base64,{b64}"
            user_content: Any = [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
            mode = "vision"
        else:
            content, source = _read_content(rec)
            if not content:
                return {
                    "ok": False,
                    "error": (
                        "テキストとして読める中身が無い。"
                        "PDF/Office は抽出 (docling) が非同期で未完の可能性 → 後で再試行。"
                        "画像など視覚が要るものは image/* として渡すこと "
                        f"(現在の content_type={ct or '不明'})。"
                    ),
                }
            if len(content) > self.valves.max_input_chars:
                content = content[: self.valves.max_input_chars]
                truncated = True
            user_content = (
                f"{instruction}\n\n--- 資料 ({filename}) ---\n{content}"
            )
            mode = "text"

        messages = [
            {"role": "system", "content": _SUBAGENT_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        await _emit(f"subagent 起動 ({mode}): {filename}", False)
        try:
            answer, model = await self._chat(messages, model=self.valves.subagent_model)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            hint = ""
            if mode == "vision":
                hint = " (live モデルが画像非対応の可能性。VLM=Kimi 等を起動すること)"
            return {"ok": False, "error": f"推論失敗 HTTP {e.response.status_code}: {body}{hint}"}
        except Exception as e:
            return {"ok": False, "error": f"推論失敗: {e!r}"}

        messages.append({"role": "assistant", "content": answer})
        tid = uuid.uuid4().hex
        try:
            await self._save_thread(tid, {"model": model, "messages": messages})
        except Exception as e:
            return {"ok": False, "error": f"thread 保存失敗 (redis): {e!r}"}

        await _emit(f"subagent 完了 ({mode}): {filename} → {tid}", True)
        result = {
            "ok": True,
            "answer": answer,
            "thread_id": tid,
            "model": model,
            "filename": filename,
            "mode": mode,
            "turns": 1,
        }
        if truncated:
            result["truncated"] = True
            result["note"] = (
                f"資料が {self.valves.max_input_chars} 文字を超えたため頭から切り詰めた。"
            )
        return result

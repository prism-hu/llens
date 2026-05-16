"""
title: PDF Vision Router
author: LLENS 開発チーム
version: 0.7.0
required_open_webui_version: 0.5.0
description: |
  PDF の処理経路を以下のルールでルーティングする。

    テキスト無               : 全ページ画像化 + VLM (image_only、上限なし)
    テキスト有 + 30p 以内    : 全ページ画像化 + VLM + Docling (hybrid)
    テキスト有 + 31p 以上    : Docling のみ (text_only)

  Docling の結果は常にそのまま残す (_exclude を呼ばない)。
  どの経路に乗ったかはモデル向け注記で透けて見える。

changelog:
  0.7.0: テキスト無は上限撤廃、テキスト有のキャップを 10p→30p に。
         text_only 経路でもモデル向け注記を入れて状況を明示。注記全体を簡潔化。
  0.6.0: ルール変更。テキスト無は枚数制限なしで全画像化。Docling は常に残す。
  0.5.0: ハイブリッドモード導入。テキストありでも 5p 以内なら VLM 併用。
  0.4.0: ログを print に統一、messages 全文ダンプ追加。
  0.3.0: body['files'][i]['file']['path'] を直接利用。
  0.2.0: ファイル取得を DB 直読みに変更。
  0.1.0: 初版。
"""

import io
import os
import base64
import logging
import traceback
from typing import Optional

import pypdf
from pdf2image import convert_from_bytes
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _p(msg: str, level: str = "info"):
    """ログ出力。OpenWebUI は loguru で標準 logging を intercept しているので、
    logger.info/warning/error を呼べばよい。"""
    getattr(logger, level)(f"[PDF-Router] {msg}")


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="複数 Filter が同じモデルにかかる場合の優先順位 (低いほど先)",
        )
        text_layer_char_threshold: int = Field(
            default=100,
            description=(
                "PDF 全ページ抽出後の総文字数がこれ未満ならテキストレイヤなしと判定"
            ),
        )
        hybrid_page_limit: int = Field(
            default=30,
            description=(
                "テキスト有の場合、このページ数以下なら VLM 画像化も併用 (hybrid)。"
                "超えた場合は Docling のみ (text_only)。テキスト無の場合は制限なし。"
            ),
        )
        rasterize_dpi: int = Field(
            default=200,
            description="ページラスタライズ DPI。高いほど精度↑、トークン消費↑",
        )
        dump_messages: bool = Field(
            default=False,
            description="inlet 入口/出口で messages の要約をログに出す (デバッグ用)",
        )

    def __init__(self):
        self.file_handler = False
        self.valves = self.Valves()

    # ============================================================
    # messages 要約ダンプ (縮約版)
    # ============================================================
    def _dump_messages(self, body: dict, when: str):
        msgs = body.get("messages", [])
        summary = []
        for i, m in enumerate(msgs):
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, str):
                summary.append(f"[{i}]{role}:str({len(content)})")
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if not isinstance(c, dict):
                        parts.append(type(c).__name__)
                        continue
                    t = c.get("type")
                    if t == "text":
                        parts.append(f"text({len(c.get('text', ''))})")
                    elif t == "image_url":
                        url = c.get("image_url", {}).get("url", "")
                        parts.append(
                            f"img(data,{len(url)})"
                            if url.startswith("data:")
                            else "img(url)"
                        )
                    else:
                        parts.append(str(t))
                summary.append(f"[{i}]{role}:[{','.join(parts)}]")
            else:
                summary.append(f"[{i}]{role}:{type(content).__name__}")
        _p(f"messages ({when}, n={len(msgs)}): {' '.join(summary)}")

    # ============================================================
    # body から PDF を集める
    # ============================================================
    def _collect_pdf_files(self, body: dict) -> list[dict]:
        seen_ids = set()
        results = []

        for src_key in ("files", "metadata_files"):
            if src_key == "metadata_files":
                src = (body.get("metadata") or {}).get("files") or []
            else:
                src = body.get("files") or []

            for f in src:
                if not isinstance(f, dict):
                    continue
                file_inner = f.get("file") or {}
                file_id = f.get("id") or file_inner.get("id")
                filename = file_inner.get("filename") or f.get("name") or ""
                path = file_inner.get("path")

                if not filename.lower().endswith(".pdf"):
                    continue
                if not file_id or not path or file_id in seen_ids:
                    if file_id and file_id not in seen_ids:
                        _p(
                            f"スキップ {filename!r}: id/path 不足 "
                            f"(id={file_id}, path={path!r})",
                            level="warning",
                        )
                    continue

                seen_ids.add(file_id)
                results.append({"id": file_id, "name": filename, "path": path})

        return results

    # ============================================================
    # PDF 解析
    # ============================================================
    def _analyze_pdf(self, pdf_bytes: bytes) -> tuple[bool, int, int]:
        """returns (has_text, n_pages, total_chars)"""
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            n_pages = len(reader.pages)
            total_chars = 0
            for page in reader.pages:
                try:
                    txt = page.extract_text() or ""
                    total_chars += len(txt.strip())
                except Exception:
                    pass  # ページ単位の例外は黙って継続
            has_text = total_chars >= self.valves.text_layer_char_threshold
            return has_text, n_pages, total_chars
        except Exception as e:
            _p(f"PDF 解析失敗、画像 PDF とみなす: {e}", level="warning")
            return False, 0, 0

    # ============================================================
    # ラスタライズ
    # ============================================================
    def _rasterize(self, pdf_bytes: bytes) -> list[str]:
        images = convert_from_bytes(
            pdf_bytes,
            dpi=self.valves.rasterize_dpi,
            fmt="png",
        )
        urls = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            urls.append(f"data:image/png;base64,{b64}")
        return urls

    # ============================================================
    # 最後の user メッセージに画像・注記を追加
    # ============================================================
    def _inject(
        self,
        body: dict,
        images: list[dict],
        notes: list[str],
    ):
        messages = body.get("messages", [])
        if not messages:
            _p("messages が空、注入できず", level="warning")
            return

        last_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_idx = i
                break
        if last_idx is None:
            _p("user メッセージが見つからず、注入できず", level="warning")
            return

        last_msg = messages[last_idx]
        existing = last_msg.get("content", "")

        if isinstance(existing, str):
            new_content = [{"type": "text", "text": existing}] if existing else []
        elif isinstance(existing, list):
            new_content = list(existing)
        else:
            new_content = []

        if notes:
            new_content.append(
                {
                    "type": "text",
                    "text": (
                        "\n\n[システム注記 / PDF Vision Router]\n" + "\n".join(notes)
                    ),
                }
            )
        new_content.extend(images)
        messages[last_idx]["content"] = new_content
        body["messages"] = messages

    # ============================================================
    # inlet
    # ============================================================
    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
    ) -> dict:
        try:
            if self.valves.dump_messages:
                self._dump_messages(body, when="inlet 入口")

            pdf_files = self._collect_pdf_files(body)
            if not pdf_files:
                return body

            _p(
                f"inlet model={body.get('model')} "
                f"user={(__user__ or {}).get('id')} "
                f"pdfs={len(pdf_files)}"
            )

            injected_images: list[dict] = []
            injected_notes: list[str] = []

            for c in pdf_files:
                fname = c["name"]
                path = c["path"]

                # 1. ファイル読み込み
                if not os.path.exists(path):
                    _p(f"{fname}: path 存在せず → Docling 任せ", level="error")
                    continue
                try:
                    with open(path, "rb") as f:
                        pdf_bytes = f.read()
                except Exception as e:
                    _p(f"{fname}: 読み込み失敗 → Docling 任せ: {e}", level="error")
                    continue

                # 2. 解析
                has_text, n_pages, total_chars = self._analyze_pdf(pdf_bytes)
                if n_pages == 0:
                    _p(f"{fname}: 解析不能 → Docling 任せ", level="warning")
                    continue

                # ============================================
                # ルーティング
                #   テキスト無               → 画像化 (image_only、上限なし)
                #   テキスト有 & ≤ N         → 画像化 (hybrid)
                #   テキスト有 & > N         → Docling のみ (text_only)
                #   Docling は常に残す
                # ============================================
                limit = self.valves.hybrid_page_limit

                if has_text and n_pages > limit:
                    _p(
                        f"{fname}: text_only "
                        f"(pages={n_pages}>{limit}, chars={total_chars})"
                    )
                    injected_notes.append(
                        f"※ {fname} ({n_pages}p, {total_chars}字): 長尺のため "
                        f"Docling 抽出のみ (画像化省略)。図表内文字・手書き・押印は未処理。"
                    )
                    continue

                mode = "hybrid" if has_text else "image_only"
                _p(
                    f"{fname}: {mode} "
                    f"(pages={n_pages}, chars={total_chars}, has_text={has_text})"
                )

                try:
                    data_urls = self._rasterize(pdf_bytes)
                except Exception as e:
                    _p(
                        f"{fname}: ラスタライズ失敗 → Docling 任せ: {e}",
                        level="error",
                    )
                    _p(traceback.format_exc(), level="error")
                    continue

                for url in data_urls:
                    injected_images.append(
                        {"type": "image_url", "image_url": {"url": url}}
                    )

                if has_text:
                    injected_notes.append(
                        f"※ {fname} ({n_pages}p, {total_chars}字): "
                        f"Docling 抽出 + 全ページ画像を提示。"
                        f"図表内文字・手書き・押印は画像から補完。原本確認を案内。"
                    )
                else:
                    injected_notes.append(
                        f"※ {fname} ({n_pages}p): スキャン PDF、全ページ画像のみ提示。原本確認を案内。"
                    )
                # Docling は常に残す → _exclude は呼ばない

            # 注入
            if injected_images or injected_notes:
                _p(
                    f"注入: 画像 {len(injected_images)} 枚, "
                    f"注記 {len(injected_notes)} 件"
                )
                self._inject(body, injected_images, injected_notes)
                if self.valves.dump_messages:
                    self._dump_messages(body, when="inlet 出口")

            return body

        except Exception as e:
            _p(f"inlet 全体で例外: {e}", level="error")
            _p(traceback.format_exc(), level="error")
            return body

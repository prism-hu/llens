"""
title: Mount Tools
description: 添付ファイルの docling 抽出テキストを .md として登録し、Pyodide の /mnt/uploads/ に出現させる。既存ファイルの /mnt 再マウントも行う。
author: Ken Enda
version: 0.1.0
required_open_webui_version: 0.5.0
"""

# =============================================================================
# 仕組み（なぜこれで /mnt に出るのか）
# -----------------------------------------------------------------------------
# Pyodide の /mnt/uploads/ はブラウザ側（IDBFS）にある。バックエンドの Tool は
# そこへ直接書けない。ファイルが /mnt に出る唯一の経路は:
#   1. Open WebUI に「実ファイル（file_id 付き・/content で取得可能）」として登録
#   2. そのファイルをメッセージの files に添付
#   3. コード実行前にフロントが getFileContentById() で取得し Pyodide FS へ展開
# 本ツールは 1 を Files API で行い、2 を chat:message:files イベントで行う。
#
# 【検証が必要な2点】お使いのバージョンで先に確認すること（debug=True で確認可）:
#   (A) chat:message:files の data スキーマ。ここでは {"files": [...]} を仮定。
#       UI に添付が出れば概ね正しい。出ない場合は下の _emit_files を調整。
#   (B) 添付が「同一ターンのコード実行」で /mnt に同期されるか。少なくとも
#       次のコード実行では出るはず（通常アップロードと同じ経路のため）。
#       docstring でモデルに「コードを書く前に呼べ」と指示してある。
# =============================================================================

import io
import os
import uuid
from typing import Optional, Callable, Any, Awaitable

from pydantic import BaseModel, Field

# --- Open WebUI 内部 API（ランタイムで解決される） ---------------------------
try:
    from open_webui.models.files import Files, FileForm
    from open_webui.storage.provider import Storage
except Exception:  # ローカルでの静的解析用フォールバック
    Files = None
    FileForm = None
    Storage = None


# -----------------------------------------------------------------------------
# 低レベルヘルパ
# -----------------------------------------------------------------------------
def _storage_upload(data: bytes, filename: str):
    """Storage.upload_file の version 差（tags 引数の有無）を吸収して
    (contents, path) を返す。"""
    bio = io.BytesIO(data)
    try:
        return Storage.upload_file(bio, filename)  # 旧シグネチャ (file, filename)
    except TypeError:
        bio.seek(0)
        # 新しめのバージョンは tags 引数を要求する
        return Storage.upload_file(bio, filename, {})


def _register_text_file(user_id: str, display_name: str, text: str,
                        content_type: str = "text/markdown") -> dict:
    """テキストを実ファイルとして Storage + Files に登録し、
    フロントの files ストアに渡せる添付 dict を返す。
    .md の中身は data.content と Storage 実体の両方に入れる
    （/content は Storage 実体を返すため、これがないと取得できない）。"""
    file_id = str(uuid.uuid4())
    raw = text.encode("utf-8")
    stored_name = f"{file_id}_{display_name}"
    contents, path = _storage_upload(raw, stored_name)

    Files.insert_new_file(
        user_id,
        FileForm(
            **{
                "id": file_id,
                "filename": display_name,
                "path": path,
                "data": {"content": text},
                "meta": {
                    "name": display_name,
                    "content_type": content_type,
                    "size": len(raw),
                },
            }
        ),
    )
    return _attachment_dict(file_id, display_name, content_type, len(raw))


def _attachment_dict(file_id: str, name: str, content_type: str, size: int) -> dict:
    """メッセージ files ストアに入れる添付オブジェクト。
    （※ 形は version 依存。UI に出ない場合はここを調整）"""
    return {
        "type": "file",
        "id": file_id,
        "name": name,
        "status": "uploaded",
        "url": f"/api/v1/files/{file_id}",
        "error": "",
        "itemId": str(uuid.uuid4()),
        "file": {
            "id": file_id,
            "filename": name,
            "meta": {"name": name, "content_type": content_type, "size": size},
        },
    }


def _iter_context_files(__files__, __metadata__):
    """ツールに渡るチャットコンテキストのファイル参照を正規化して列挙。
    __files__ と metadata.files の両方をフォールバックで見る。"""
    raw = []
    if __files__:
        raw = __files__
    elif __metadata__ and __metadata__.get("files"):
        raw = __metadata__["files"]
    for f in raw or []:
        inner = f.get("file", {}) if isinstance(f, dict) else {}
        fid = (f.get("id") if isinstance(f, dict) else None) or inner.get("id")
        fname = (f.get("name") if isinstance(f, dict) else None) \
            or inner.get("filename") or (inner.get("meta") or {}).get("name")
        if fid:
            yield fid, fname, f


def _match(name: Optional[str], target: Optional[str]) -> bool:
    """filename 指定が無ければ全件、あれば部分一致（大小無視）。"""
    if not target:
        return True
    if not name:
        return False
    return target.lower() in name.lower()


# -----------------------------------------------------------------------------
# Tool 本体
# -----------------------------------------------------------------------------
class Tools:
    class Valves(BaseModel):
        markdown_suffix: str = Field(
            default=".md", description="派生テキストファイルの拡張子")
        replace_message_files: bool = Field(
            default=False,
            description="True なら既存添付を置換、False なら追加（既存を保ったまま追記）")
        debug: bool = Field(default=False, description="詳細ログを status で流す")

    class UserValves(BaseModel):
        enabled: bool = Field(default=True, description="ユーザー側の有効/無効")

    def __init__(self):
        self.valves = self.Valves()

    # ---- 共通: chat:message:files の発火 ------------------------------------
    async def _emit_files(self, attachments, existing, __event_emitter__):
        """添付リストをメッセージに反映。replace_message_files=False のときは
        既存添付（元PDF等）を保ったまま新規を追記する。"""
        if not __event_emitter__:
            return
        files = list(attachments)
        if not self.valves.replace_message_files and existing:
            # 既存をそのまま前置（重複 id は除く）
            seen = {a.get("id") for a in files}
            for e in existing:
                eid = e.get("id") or e.get("file", {}).get("id")
                if eid and eid not in seen:
                    files.insert(0, e)
        # (A) ここがバージョン依存ポイント
        await __event_emitter__({
            "type": "chat:message:files",
            "data": {"files": files},
        })

    async def _status(self, msg, done, __event_emitter__):
        if self.valves.debug and __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": msg, "done": done},
            })

    # =========================================================================
    # mount_markdown
    # =========================================================================
    async def mount_markdown(
        self,
        filename: Optional[str] = None,
        __user__: Optional[dict] = None,
        __files__: Optional[list] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        添付ドキュメントの docling 抽出済みテキストを Markdown ファイル(.md)として
        登録し、コードインタプリタの /mnt/uploads/ に出現させる。
        モデルに大量本文を逐語転記させず、コードからファイルとして読ませたい時に使う。
        **コードを書く前に必ず呼ぶこと。** 戻り値に /mnt 上のパスを返す。

        :param filename: 対象ファイル名（部分一致）。省略時は添付全件を対象。
        """
        if Files is None:
            return "ERROR: open_webui の内部 API を解決できません（実行環境を確認）。"
        if not __user__ or not __user__.get("id"):
            return "ERROR: ユーザー情報が取得できませんでした。"

        await self._status("Resolving attached files...", False, __event_emitter__)

        existing = [f for _, _, f in _iter_context_files(__files__, __metadata__)]
        made = []
        report = []

        for fid, fname, _ref in _iter_context_files(__files__, __metadata__):
            if not _match(fname, filename):
                continue
            rec = Files.get_file_by_id(fid)
            if not rec:
                report.append(f"- {fname or fid}: レコード無し（skip）")
                continue
            content = (getattr(rec, "data", None) or {}).get("content")
            if not content:
                report.append(
                    f"- {fname or fid}: 抽出テキストが空（docling 未完了 or 失敗）")
                continue
            stem = os.path.splitext(fname or f"file_{fid[:8]}")[0]
            md_name = f"{stem}{self.valves.markdown_suffix}"
            try:
                att = _register_text_file(__user__["id"], md_name, content)
                made.append(att)
                report.append(f"- {md_name}: /mnt/uploads/{md_name}")
            except Exception as e:
                report.append(f"- {md_name}: 登録失敗 {e!r}")

        if not made:
            await self._status("No markdown mounted.", True, __event_emitter__)
            return "マウント対象がありませんでした。\n" + "\n".join(report)

        await self._emit_files(made, existing, __event_emitter__)
        await self._status(f"Mounted {len(made)} markdown file(s).", True,
                           __event_emitter__)
        return (
            f"{len(made)} 件の Markdown を /mnt/uploads/ にマウントしました。\n"
            + "\n".join(report)
            + "\n\nコード側で次のように読めます:\n"
            "```python\n"
            "import os\n"
            "print(os.listdir('/mnt/uploads'))\n"
            "md = open('/mnt/uploads/" + made[0]['name'] + "', encoding='utf-8').read()\n"
            "```"
        )

    # =========================================================================
    # mount_file
    # =========================================================================
    async def mount_file(
        self,
        filename: str,
        __user__: Optional[dict] = None,
        __files__: Optional[list] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        チャットコンテキストの既存ファイル（アップロード済み or ナレッジ）を
        /mnt/uploads/ にマウントする。file_context を切っていて自動マウントされない、
        あるいは過去ターンのファイルを再度 /mnt に出したい場合に使う。
        **コードを書く前に呼ぶこと。**

        :param filename: マウントしたいファイル名（部分一致）。
        """
        if Files is None:
            return "ERROR: open_webui の内部 API を解決できません。"
        if not __user__ or not __user__.get("id"):
            return "ERROR: ユーザー情報が取得できませんでした。"

        existing = [f for _, _, f in _iter_context_files(__files__, __metadata__)]
        targets = []
        report = []

        for fid, fname, ref in _iter_context_files(__files__, __metadata__):
            if not _match(fname, filename):
                continue
            rec = Files.get_file_by_id(fid)
            if not rec:
                report.append(f"- {fname or fid}: レコード無し（skip）")
                continue
            meta = (getattr(rec, "meta", None) or {})
            att = _attachment_dict(
                fid,
                fname or rec.filename,
                meta.get("content_type", "application/octet-stream"),
                meta.get("size", 0),
            )
            targets.append(att)
            report.append(f"- {fname or fid}: /mnt/uploads/{fname or rec.filename}")

        if not targets:
            return (f"'{filename}' に一致する既存ファイルが見つかりませんでした。\n"
                    + "\n".join(report))

        await self._emit_files(targets, existing, __event_emitter__)
        await self._status(f"Mounted {len(targets)} file(s).", True,
                           __event_emitter__)
        return (f"{len(targets)} 件を /mnt/uploads/ にマウントしました。\n"
                + "\n".join(report))

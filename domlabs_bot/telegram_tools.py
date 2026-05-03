"""In-process MCP server exposing Telegram-send tools to the Claude session.

The agent calls these when it decides a result is better delivered as a file
or image (PDFs, screenshots, long logs, generated artifacts) than inline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

from . import config

log = logging.getLogger(__name__)


def _api_base() -> str:
    return f"https://api.telegram.org/bot{config.BOT_TOKEN}"


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Not a file: {p}")
    return p


async def _upload(endpoint: str, file_field: str, path: Path, caption: str | None) -> dict:
    data = {"chat_id": str(config.OWNER_USER_ID)}
    if caption:
        data["caption"] = caption[:1024]
    async with httpx.AsyncClient(timeout=120) as client:
        with path.open("rb") as fh:
            resp = await client.post(
                f"{_api_base()}/{endpoint}",
                data=data,
                files={file_field: (path.name, fh)},
            )
    resp.raise_for_status()
    return resp.json()


@tool(
    "send_file",
    "Send a file from disk to the user over Telegram. Use for PDFs, docs, "
    "archives, or any artifact the user should receive as an attachment. "
    "The path can be absolute or relative to the current working directory.",
    {"path": str, "caption": str},
)
async def send_file(args: dict[str, Any]) -> dict[str, Any]:
    try:
        p = _resolve(args["path"])
        await _upload("sendDocument", "document", p, args.get("caption"))
        return {"content": [{"type": "text", "text": f"sent file: {p.name}"}]}
    except Exception as e:
        log.exception("send_file failed")
        return {
            "content": [{"type": "text", "text": f"failed to send file: {e}"}],
            "isError": True,
        }


@tool(
    "send_photo",
    "Send an image from disk to the user over Telegram. Use for screenshots, "
    "generated images, charts, or visual artifacts. Telegram will display it "
    "inline. For very large images or non-photo files, use send_file instead.",
    {"path": str, "caption": str},
)
async def send_photo(args: dict[str, Any]) -> dict[str, Any]:
    try:
        p = _resolve(args["path"])
        await _upload("sendPhoto", "photo", p, args.get("caption"))
        return {"content": [{"type": "text", "text": f"sent photo: {p.name}"}]}
    except Exception as e:
        log.exception("send_photo failed")
        return {
            "content": [{"type": "text", "text": f"failed to send photo: {e}"}],
            "isError": True,
        }


@tool(
    "send_code_as_file",
    "Send a block of text/code to the user as a file attachment. Use when the "
    "content is too long for a chat message (over ~3000 chars), contains many "
    "special characters that mangle in chat, or is better reviewed as a file "
    "(long logs, generated code, reports). Choose a descriptive filename with "
    "the right extension (e.g. 'build-log.txt', 'schema.sql', 'analysis.md').",
    {"filename": str, "content": str, "caption": str},
)
async def send_code_as_file(args: dict[str, Any]) -> dict[str, Any]:
    try:
        filename = args.get("filename") or "snippet.txt"
        content = args["content"]
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=f"_{filename}", delete=False
        ) as fh:
            fh.write(content)
            tmp_path = Path(fh.name)
        try:
            await _upload("sendDocument", "document", tmp_path, args.get("caption"))
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return {"content": [{"type": "text", "text": f"sent as file: {filename}"}]}
    except Exception as e:
        log.exception("send_code_as_file failed")
        return {
            "content": [{"type": "text", "text": f"failed: {e}"}],
            "isError": True,
        }


telegram_mcp_server = create_sdk_mcp_server(
    name="telegram",
    version="1.0.0",
    tools=[send_file, send_photo, send_code_as_file],
)

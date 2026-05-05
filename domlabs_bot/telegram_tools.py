"""In-process MCP server exposing Telegram-send tools to the Claude session.

The agent calls these when it decides a result is better delivered as a file
or image (PDFs, screenshots, long logs, generated artifacts) than inline.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

from . import config

log = logging.getLogger(__name__)

# Long-lived httpx client + a serialization lock. Two separate problems
# cooperate here:
#
#   (1) Per-call `async with httpx.AsyncClient()` paid a fresh DNS+TCP+TLS
#       handshake every time, which intermittently bricked on Windows with
#       "All connection attempts failed" on transient v6/firewall blips.
#       Solved by a module-level client + AsyncHTTPTransport(retries=3).
#
#   (2) Agents tend to fire these tools in PARALLEL ("send 10 messages"
#       turns into ten concurrent `send_message` calls). Telegram caps each
#       chat at ~1 msg/sec and rejects the excess at the TCP layer, which
#       httpcore also reports as "All connection attempts failed". Pool
#       reuse alone does not solve that; we need to serialize.
#
# `_send_lock` ensures only one Bot API POST is in flight at a time and a
# `MIN_INTERVAL_SECONDS` floor keeps us under the per-chat limit. 429s
# from Telegram are honored via `Retry-After`.
_client: httpx.AsyncClient | None = None
_send_lock = asyncio.Lock()
_last_send_at: float = 0.0
MIN_INTERVAL_SECONDS = 1.05  # Telegram per-chat limit is 1/sec; +50ms slack.
MAX_429_RETRIES = 3


def _client_once() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0),
            transport=httpx.AsyncHTTPTransport(retries=3),
        )
    return _client


def _api_base() -> str:
    return f"https://api.telegram.org/bot{config.BOT_TOKEN}"


async def _post_throttled(url: str, **kwargs: Any) -> httpx.Response:
    """POST under a global lock with a 1/sec floor + Retry-After honoring.

    Serializes all Telegram Bot API writes from the MCP tools. Without this
    the agent's tendency to fan-out tool calls trips Telegram's flood limit.
    """
    global _last_send_at
    client = _client_once()
    async with _send_lock:
        now = asyncio.get_event_loop().time()
        wait = MIN_INTERVAL_SECONDS - (now - _last_send_at)
        if wait > 0:
            await asyncio.sleep(wait)
        for attempt in range(MAX_429_RETRIES + 1):
            resp = await client.post(url, **kwargs)
            _last_send_at = asyncio.get_event_loop().time()
            if resp.status_code != 429:
                return resp
            retry_after = float(resp.headers.get("Retry-After", "1"))
            log.warning(
                "telegram 429 on %s — sleeping %.1fs (attempt %d/%d)",
                url.rsplit("/", 1)[-1],
                retry_after,
                attempt + 1,
                MAX_429_RETRIES,
            )
            await asyncio.sleep(retry_after + 0.1)
        return resp


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
    with path.open("rb") as fh:
        resp = await _post_throttled(
            f"{_api_base()}/{endpoint}",
            data=data,
            files={file_field: (path.name, fh)},
        )
    resp.raise_for_status()
    return resp.json()


@tool(
    "send_message",
    "Send a plain-text message to the user over Telegram as a SEPARATE "
    "message. Your normal reply is already routed to Telegram — only call "
    "this tool when you want to push an ADDITIONAL message (e.g. a "
    "follow-up status, an interim 'still working...' nudge, or a deferred "
    "answer). Hard limit: 4096 chars per call. For longer text use "
    "send_code_as_file instead. ALWAYS call sequentially (await each one) "
    "— never fan-out parallel calls. Telegram caps a single chat at 1 "
    "msg/sec and will drop excess sends.",
    {"text": str, "silent": bool},
)
async def send_message(args: dict[str, Any]) -> dict[str, Any]:
    try:
        text = args.get("text") or ""
        if not text.strip():
            raise ValueError("text is empty")
        if len(text) > 4096:
            raise ValueError(
                f"text exceeds Telegram's 4096-char per-message limit "
                f"({len(text)} chars). Split into multiple calls or use "
                f"send_code_as_file for the long content."
            )
        data: dict[str, str] = {
            "chat_id": str(config.OWNER_USER_ID),
            "text": text,
        }
        if args.get("silent"):
            data["disable_notification"] = "true"
        resp = await _post_throttled(f"{_api_base()}/sendMessage", data=data)
        resp.raise_for_status()
        return {"content": [{"type": "text", "text": f"sent message ({len(text)} chars)"}]}
    except Exception as e:
        log.exception("send_message failed")
        return {
            "content": [{"type": "text", "text": f"failed to send message: {e}"}],
            "isError": True,
        }


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
    tools=[send_message, send_file, send_photo, send_code_as_file],
)

"""Multi-project persistent Claude Agent SDK sessions with idle timeout.

One live session per project. Switching projects via ``/project <name>``
routes subsequent messages to that project's session. Each session
idle-times-out independently. An optional ``pre_dispose`` callback fires
just before disposal so the runtime can summarise the conversation into
the daily memory file.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Awaitable, Callable, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from . import config, projects
from .persona import build_persona_prompt
from .telegram_tools import telegram_mcp_server

log = logging.getLogger(__name__)

# Callback fires just before a session is disposed due to idle timeout.
# Signature: (project_name, transcript) -> None.
PreDisposeCallback = Callable[[str, list[tuple[str, str]]], Awaitable[None]]


def _build_options(cwd: str) -> ClaudeAgentOptions:
    """Build SDK options for a new session.

    The persona prompt is intentionally compact — it ships via
    ``--append-system-prompt`` argv, and Windows CreateProcess caps argv
    around 32 KB. Telegram delivery rules live inside the persona prompt
    itself.
    """
    append_text = build_persona_prompt()
    log.info("persona prompt: %d chars", len(append_text))
    opts = ClaudeAgentOptions(
        cwd=cwd,
        permission_mode="bypassPermissions",
        mcp_servers={"telegram": telegram_mcp_server},
        setting_sources=["user", "project", "local"],
        skills="all",
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": append_text,
        },
    )
    if config.MODEL:
        opts.model = config.MODEL
    if config.CLI_PATH:
        opts.cli_path = config.CLI_PATH
    return opts


class ProjectSession:
    """Single persistent SDK client for one project. Idle-recycles."""

    def __init__(self, name: str, cwd: str, idle_seconds: int) -> None:
        self.name = name
        self._cwd = cwd
        self._idle_seconds = idle_seconds
        self._client: Optional[ClaudeSDKClient] = None
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()
        # Turn transcript (role, text) — kept for /summary on disposal.
        self._transcript: list[tuple[str, str]] = []

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def is_alive(self) -> bool:
        return self._client is not None and not self._is_idle()

    def _is_idle(self) -> bool:
        return self._last_used != 0 and (
            time.monotonic() - self._last_used
        ) > self._idle_seconds

    def drain_transcript(self) -> list[tuple[str, str]]:
        t = self._transcript
        self._transcript = []
        return t

    async def dispose(self) -> None:
        async with self._lock:
            await self._dispose_locked()

    async def _dispose_locked(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                log.exception("[%s] error disposing SDK client", self.name)
            self._client = None

    async def _ensure_client_locked(self) -> ClaudeSDKClient:
        if self._is_idle():
            log.info("[%s] session idle, recycling.", self.name)
            await self._dispose_locked()
            self._transcript = []
        if self._client is None:
            client = ClaudeSDKClient(options=_build_options(self._cwd))
            try:
                await client.connect()
            except BaseException:
                log.exception(
                    "[%s] connect() failed (cli_path=%s)", self.name, config.CLI_PATH
                )
                try:
                    await client.disconnect()
                except Exception:
                    pass
                raise
            self._client = client
            log.info(
                "[%s] spawned new SDK session (cwd=%s, cli=%s)",
                self.name,
                self._cwd,
                config.CLI_PATH or "<PATH>",
            )
        return self._client

    async def send(
        self, prompt: str | list[dict], prompt_preview: str
    ) -> AsyncIterator[dict]:
        """Send a prompt (string or content-block list). Yield streamed events."""
        async with self._lock:
            client = await self._ensure_client_locked()
            self._last_used = time.monotonic()
            self._transcript.append(("user", prompt_preview))
            t_query = time.monotonic()
            log.info("[%s] query sent (preview=%r)", self.name, prompt_preview[:80])
            await client.query(
                prompt if isinstance(prompt, str) else _content_iter(prompt)
            )
            reply_chunks: list[str] = []
            saw_assistant = False
            t_first_assist: float | None = None
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    if t_first_assist is None:
                        t_first_assist = time.monotonic()
                        log.info(
                            "[%s] first AssistantMessage after %.2fs",
                            self.name,
                            t_first_assist - t_query,
                        )
                    msg_had_text = False
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            reply_chunks.append(block.text)
                            msg_had_text = True
                            yield {"type": "text", "text": block.text}
                        elif isinstance(block, ToolUseBlock):
                            yield {
                                "type": "tool",
                                "name": block.name,
                                "input": block.input or {},
                            }
                    if msg_had_text:
                        saw_assistant = True
                        yield {"type": "assistant_done"}
                elif isinstance(msg, ResultMessage):
                    log.info(
                        "[%s] ResultMessage after %.2fs (text_seen=%s)",
                        self.name,
                        time.monotonic() - t_query,
                        saw_assistant,
                    )
                    break
            if reply_chunks:
                self._transcript.append(("assistant", "".join(reply_chunks)))
            self._last_used = time.monotonic()


async def _content_iter(content: list[dict]):
    """Wrap a content-block list as an async iterable for the SDK."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


class SessionManager:
    """Registry of per-project sessions + a background idle-reaper."""

    def __init__(self) -> None:
        self._sessions: dict[str, ProjectSession] = {}
        self._current: str = self._pick_initial_project()
        self._idle_seconds = config.IDLE_TIMEOUT_MINUTES * 60
        self._lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None
        self.pre_dispose: Optional[PreDisposeCallback] = None

    @staticmethod
    def _pick_initial_project() -> str:
        """Pick a starting project — first one in projects.json, or 'default'."""
        registry = projects.list_projects()
        if not registry:
            return "default"
        if "default" in registry:
            return "default"
        return next(iter(registry))

    @property
    def current_project(self) -> str:
        return self._current

    def cwd_of(self, name: str) -> str:
        if name in self._sessions:
            return self._sessions[name].cwd
        cwd = projects.get_cwd(name)
        if cwd is None:
            # Fall back to DEFAULT_CWD so /start displays sensibly even
            # before any project has been switched into.
            return config.DEFAULT_CWD
        return cwd

    async def _get_or_create(self, name: str) -> ProjectSession:
        if name in self._sessions:
            return self._sessions[name]
        cwd = projects.get_cwd(name)
        if cwd is None:
            if name == "default":
                cwd = config.DEFAULT_CWD
            else:
                raise ValueError(f"unknown project: {name}")
        session = ProjectSession(name, cwd, self._idle_seconds)
        self._sessions[name] = session
        return session

    async def switch(self, name: str) -> str:
        """Set current project. Returns its cwd."""
        async with self._lock:
            s = await self._get_or_create(name)
            self._current = name
            return s.cwd

    async def reset_current(self) -> None:
        """Force-dispose the current project's session."""
        async with self._lock:
            s = self._sessions.get(self._current)
            if s is not None:
                await s.dispose()

    async def send(self, prompt, prompt_preview: str):
        async with self._lock:
            s = await self._get_or_create(self._current)
        async for evt in s.send(prompt, prompt_preview):
            yield evt

    def status(self) -> list[dict]:
        rows = []
        for name, s in self._sessions.items():
            rows.append({"name": name, "cwd": s.cwd, "alive": s.is_alive})
        return rows

    async def start_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_loop())

    async def stop_reaper(self) -> None:
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _reap_loop(self) -> None:
        """Every 60s, dispose idle sessions after firing pre_dispose."""
        while True:
            try:
                await asyncio.sleep(60)
                for name, s in list(self._sessions.items()):
                    if s._client is not None and s._is_idle():
                        log.info("[%s] idle, firing pre_dispose + dispose", name)
                        transcript = s.drain_transcript()
                        if self.pre_dispose and transcript:
                            try:
                                await self.pre_dispose(name, transcript)
                            except Exception:
                                log.exception("[%s] pre_dispose failed", name)
                        await s.dispose()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reaper loop error")

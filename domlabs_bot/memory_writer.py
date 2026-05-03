"""Quick-capture + auto-summary writers for the daily memory file.

All writes go to ``$DOMLABS_BOT_ROOT/memory/YYYY-MM-DD.md`` and are tagged
``<!-- via domlabs-bot -->`` so they're distinguishable from any other tool's
edits to the same file.
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from pathlib import Path
from typing import Iterable

from . import paths

log = logging.getLogger(__name__)

TAG = "<!-- via domlabs-bot -->"


def _today_path() -> Path:
    return paths.memory_dir() / f"{date.today().isoformat()}.md"


def _ensure_header(path: Path) -> None:
    if not path.exists():
        path.write_text(f"# {date.today().isoformat()}\n", encoding="utf-8")


def append_note(text: str) -> Path:
    """Quick `/mem` capture — plain bullet with timestamp."""
    paths.memory_dir().mkdir(parents=True, exist_ok=True)
    path = _today_path()
    _ensure_header(path)
    ts = datetime.now().strftime("%H:%M")
    line = f"\n- **{ts}** — {text.strip()} {TAG}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return path


def append_summary(project: str, summary: str) -> Path:
    """Auto-summary on session idle-out."""
    paths.memory_dir().mkdir(parents=True, exist_ok=True)
    path = _today_path()
    _ensure_header(path)
    ts = datetime.now().strftime("%H:%M")
    block = (
        f"\n## domlabs-bot session summary — `{project}` ({ts})\n\n"
        f"{summary.strip()}\n{TAG}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(block)
    return path


def format_transcript(transcript: Iterable[tuple[str, str]], limit: int = 20) -> str:
    """Render last N turns of a transcript for summarization prompts."""
    turns = list(transcript)[-limit:]
    lines = []
    for role, text in turns:
        label = "User" if role == "user" else "Assistant"
        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        lines.append(f"{label}: {snippet}")
    return "\n".join(lines)

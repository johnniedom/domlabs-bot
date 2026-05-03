"""Telegram message-splitting helper."""
from __future__ import annotations

from typing import Iterator

TELEGRAM_LIMIT = 4000


def split_for_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> Iterator[str]:
    """Split a long string into Telegram-safe chunks.

    Tries to break on paragraph, line, or word boundaries near the limit
    so individual chunks stay readable on a phone screen.
    """
    if not text:
        return
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind(" ", 0, limit)
        if cut == -1 or cut < limit // 2:
            cut = limit
        yield remaining[:cut].rstrip()
        remaining = remaining[cut:].lstrip()
    if remaining:
        yield remaining

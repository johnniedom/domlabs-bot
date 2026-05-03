"""Filesystem paths for domlabs-bot.

Everything user-owned (persona files, projects.json, .env, logs, memory)
lives under a single root that defaults to ``~/.domlabs-bot/`` and can be
overridden with the ``DOMLABS_BOT_ROOT`` environment variable.

This module is import-time-cheap: no I/O happens until ``ensure_root()``
is called explicitly (the init wizard, daemon installer, and main runtime
all call it before doing anything that touches disk).
"""
from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    """Return the domlabs-bot data root.

    Resolution order:
      1. ``$DOMLABS_BOT_ROOT`` if set (expanded for ``~``).
      2. ``~/.domlabs-bot/``.
    """
    override = os.environ.get("DOMLABS_BOT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".domlabs-bot").resolve()


def env_file() -> Path:
    return root() / ".env"


def projects_file() -> Path:
    return root() / "projects.json"


def memory_dir() -> Path:
    return root() / "memory"


def logs_dir() -> Path:
    return root() / "logs"


def log_file() -> Path:
    return logs_dir() / "domlabs-bot.log"


def soul_file() -> Path:
    return root() / "SOUL.md"


def identity_file() -> Path:
    return root() / "IDENTITY.md"


def user_file() -> Path:
    return root() / "USER.md"


def memory_file() -> Path:
    return root() / "MEMORY.md"


def ensure_root() -> Path:
    """Create the root + standard subdirectories if they don't exist."""
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    memory_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    return r

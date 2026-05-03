"""Runtime configuration loaded from $DOMLABS_BOT_ROOT/.env.

Only loaded lazily so subcommands like `init` and `--help` don't crash when
the env file doesn't yet exist. Call ``load()`` once at startup of the
runtime; all module-level globals will be populated.
"""
from __future__ import annotations

import os
from pathlib import Path
from shutil import which

from dotenv import load_dotenv

from . import paths


# --- Runtime state, populated by load(). ---
BOT_TOKEN: str = ""
OWNER_USER_ID: int = 0
ANTHROPIC_API_KEY: str = ""
DEFAULT_CWD: str = ""
IDLE_TIMEOUT_MINUTES: int = 15
MODEL: str = ""
CLI_PATH: str | None = None
GEMINI_API_KEY: str = ""
VOICE_ENABLED: bool = False

_LOADED = False


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_cli() -> str | None:
    explicit = os.getenv("CLAUDE_CLI_PATH", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = which("claude") or which("claude.exe")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".npm-global" / "bin" / "claude",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def load(*, strict: bool = True) -> None:
    """Load `.env` from the data root and populate module globals.

    Args:
        strict: When True (default), raise if BOT_TOKEN or OWNER_USER_ID
                are missing. When False, leave defaults in place — useful
                for `domlabs-bot status` and similar diagnostic commands
                that should still work pre-init.
    """
    global _LOADED
    global BOT_TOKEN, OWNER_USER_ID, ANTHROPIC_API_KEY
    global DEFAULT_CWD, IDLE_TIMEOUT_MINUTES, MODEL
    global CLI_PATH, GEMINI_API_KEY, VOICE_ENABLED

    env_path = paths.env_file()
    if env_path.exists():
        load_dotenv(env_path)

    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    owner_raw = os.getenv("OWNER_USER_ID", "").strip()
    OWNER_USER_ID = int(owner_raw) if owner_raw.isdigit() or (
        owner_raw.startswith("-") and owner_raw[1:].isdigit()
    ) else 0
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
    DEFAULT_CWD = os.getenv("DEFAULT_CWD", "").strip() or str(Path.home())
    try:
        IDLE_TIMEOUT_MINUTES = int(os.getenv("IDLE_TIMEOUT_MINUTES", "15"))
    except ValueError:
        IDLE_TIMEOUT_MINUTES = 15
    MODEL = os.getenv("MODEL", "").strip()
    CLI_PATH = _resolve_cli()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    VOICE_ENABLED = _truthy(os.getenv("VOICE_ENABLED", "false"))

    # Make ANTHROPIC_API_KEY visible to the spawned Claude CLI.
    if ANTHROPIC_API_KEY:
        os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    if GEMINI_API_KEY:
        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

    if strict:
        missing = []
        if not BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not OWNER_USER_ID:
            missing.append("OWNER_USER_ID")
        # ANTHROPIC_API_KEY is intentionally optional. If unset, the spawned
        # Claude Code CLI uses its own stored auth from `claude /login`
        # (Pro/Max subscription). Required only if the user wants to override
        # with a pay-per-token API key.
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}.\n"
                f"Run `domlabs-bot init` or edit {env_path}."
            )

    _LOADED = True


def is_loaded() -> bool:
    return _LOADED

"""Interactive 6-step setup wizard.

Walks the user through:
  1. Anthropic API key   (validated with /messages ping)
  2. Pick a model        (defaults to Sonnet 4.6)
  3. Telegram bot token  (validated with getMe)
  4. Owner identification (auto-detected via getUpdates polling for "pair")
  5. Persona scaffolding (optional — IDENTITY.md, USER.md, SOUL.md, MEMORY.md)
  6. Projects (first required, additional optional)

Writes .env, projects.json, and persona templates to ``$DOMLABS_BOT_ROOT``.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import httpx
import questionary

from . import paths
from .templates import write as write_template

ANTHROPIC_KEYS_URL = "https://console.anthropic.com/settings/keys"
BOTFATHER_URL = "https://t.me/BotFather"
ANTHROPIC_PING_MODEL = "claude-haiku-4-5-20251001"


# --- tiny print helpers -------------------------------------------------

TOTAL_STEPS = 6


def _hr() -> None:
    print()


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _warn(msg: str) -> None:
    print(f"  ! {msg}")


def _err(msg: str) -> None:
    print(f"  ✗ {msg}")


def _dots(num: int, total: int) -> str:
    """Render a `num/total` progress as filled/hollow dots, with an ASCII
    fallback for terminals (cp1252, etc.) that can't encode Unicode."""
    enc = sys.stdout.encoding or "utf-8"
    try:
        "●○".encode(enc)
        return "●" * num + "○" * (total - num)
    except UnicodeEncodeError:
        return "[" + "#" * num + "." * (total - num) + "]"


def _step_header(num: int, title: str, badge: str = "") -> None:
    """Print a step header with a dot-progress breadcrumb.

    Example output::

        ●●○○○○  Pick a model  [optional, defaults to Sonnet 4.6]

    Filled dots = completed steps including the current one. Hollow dots =
    steps still to come. ASCII fallback for cp1252 terminals.
    """
    suffix = f"  {badge}" if badge else ""
    print()
    print(f"{_dots(num, TOTAL_STEPS)}  {title}{suffix}")


def _confirm_open(url: str, prompt: str) -> bool:
    """Print URL above the prompt, ask [Y/n], open if yes."""
    print(f"  URL: {url}")
    open_it = questionary.confirm(prompt, default=True).ask()
    if open_it is None:
        # Ctrl+C or non-tty — treat as decline.
        return False
    if open_it:
        try:
            webbrowser.open(url)
            _ok("Opened.")
        except Exception:
            _warn("Couldn't auto-open. Copy the URL above into your browser.")
    return open_it


# --- step 1: anthropic key ----------------------------------------------

def _validate_anthropic_key(key: str) -> tuple[bool, str]:
    """Ping /messages with a 1-token request. Returns (ok, error_message)."""
    if not key.startswith("sk-ant-"):
        return False, "doesn't look like an Anthropic key (should start with `sk-ant-`)."
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_PING_MODEL,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=30,
        )
    except httpx.HTTPError as e:
        return False, f"network error: {e}"
    if resp.status_code in (200, 201):
        return True, ""
    if resp.status_code in (401, 403):
        return False, "key rejected (401/403). Double-check it on the Anthropic console."
    if resp.status_code == 404:
        # Probably the model name moved on. Try a generic check via a 400.
        return True, ""
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"


_AUTH_CLAUDE_LOGIN = "Use my Claude Code login (Pro/Max subscription) — recommended"
_AUTH_API_KEY = "Use an Anthropic API key (pay-per-token)"
_AUTH_GET_KEY = "I don't have a key — open the Anthropic Console for me"


def step_anthropic_key() -> str:
    """Returns the API key string, or "" if the user is using Claude Code's
    own auth (Pro/Max subscription via `claude /login`).

    The runtime works either way — when ANTHROPIC_API_KEY is unset, the
    spawned Claude Code CLI falls back to its stored credentials.
    """
    _step_header(1, "Anthropic auth", "[optional]")
    choice = questionary.select(
        "How do you want to authenticate?",
        choices=[_AUTH_CLAUDE_LOGIN, _AUTH_API_KEY, _AUTH_GET_KEY],
        default=_AUTH_CLAUDE_LOGIN,
    ).ask()
    if choice is None:
        sys.exit(1)

    if choice == _AUTH_CLAUDE_LOGIN:
        _ok("Using your existing Claude Code login. Run `claude /login` in your terminal if you haven't.")
        return ""

    if choice == _AUTH_GET_KEY:
        try:
            webbrowser.open(ANTHROPIC_KEYS_URL)
            _ok(f"Opened {ANTHROPIC_KEYS_URL} — generate a key, then paste it below.")
        except Exception:
            _warn(f"Couldn't auto-open. Visit {ANTHROPIC_KEYS_URL} manually.")

    # API-key path: chosen directly (option 2) or after the auto-open detour (option 3)
    while True:
        key = questionary.password("Paste your key (sk-ant-...):").ask()
        if key is None:
            sys.exit(1)
        key = key.strip()
        if not key:
            _err("Empty input. Paste a key, or Ctrl+C to abort and start over.")
            continue
        ok, msg = _validate_anthropic_key(key)
        if ok:
            _ok("Verified.")
            return key
        _err(msg)
        retry = questionary.confirm("Try again?", default=True).ask()
        if not retry:
            sys.exit(1)


# --- step 2: pick a model -----------------------------------------------

MODEL_CHOICES = [
    {
        "id": "claude-sonnet-4-6",
        "label": "claude-sonnet-4-6      — balanced (recommended for chat)",
    },
    {
        "id": "claude-opus-4-7",
        "label": "claude-opus-4-7        — most capable, most expensive",
    },
    {
        "id": "claude-haiku-4-5-20251001",
        "label": "claude-haiku-4-5       — cheapest, fastest",
    },
]


def step_model() -> str:
    """Ask the user which Claude model to run the assistant on. Default: Sonnet 4.6.

    The Anthropic key was already validated in step 1 (via a Haiku ping). We don't
    re-validate against the chosen model — some keys are tier-gated, but probing
    that here adds cost and a lot of error paths. If the chosen model is rejected
    at runtime, the user finds out at their first message and can edit ``.env``.
    """
    _step_header(2, "Pick a model", "[optional, defaults to Sonnet 4.6]")
    print("  Which Claude model should your assistant use?")
    options = [c["label"] for c in MODEL_CHOICES] + [
        "custom (enter a model ID)",
    ]
    choice = questionary.select(
        "Choice:",
        choices=options,
        default=options[0],
    ).ask()
    if choice is None:
        sys.exit(1)
    if choice.startswith("custom"):
        while True:
            model_id = questionary.text(
                "Enter the model ID (e.g. claude-sonnet-4-6):",
            ).ask()
            if model_id is None:
                sys.exit(1)
            model_id = model_id.strip()
            if model_id:
                _warn("Custom model ID — not validated against your key.")
                _ok(f"{model_id} selected.")
                return model_id
            _err("Empty input.")
    # Map label back to id.
    for c in MODEL_CHOICES:
        if c["label"] == choice:
            _ok(f"{c['id']} selected.")
            return c["id"]
    # Unreachable — questionary returns one of the offered options.
    return MODEL_CHOICES[0]["id"]


# --- step 3: telegram bot token -----------------------------------------

def _validate_bot_token(token: str) -> tuple[Optional[dict], str]:
    """Call getMe. Returns (bot_info_dict, error)."""
    try:
        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=15
        )
    except httpx.HTTPError as e:
        return None, f"network error: {e}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    if not body.get("ok"):
        return None, body.get("description", "Telegram rejected token")
    return body.get("result", {}), ""


def step_bot_token() -> tuple[str, dict]:
    _step_header(3, "Create your bot", "[required]")
    print(f"  Get a token from BotFather: {BOTFATHER_URL}")
    _confirm_open(BOTFATHER_URL, "Open BotFather now?")
    print("  In BotFather, run: /newbot")
    print("  Pick a display name and a username ending in 'bot'.")
    print("  When BotFather gives you a token (1234:ABC...), paste it here.")
    while True:
        token = questionary.password("Token:").ask()
        if token is None:
            sys.exit(1)
        token = token.strip()
        if not token or ":" not in token:
            _err("That doesn't look like a Telegram bot token.")
            continue
        info, err = _validate_bot_token(token)
        if info:
            handle = info.get("username")
            first = info.get("first_name") or handle
            label = f"@{handle}" if handle else first
            _ok(f"{label} verified — first_name='{first}'.")
            return token, info
        _err(err)
        retry = questionary.confirm("Try again?", default=True).ask()
        if not retry:
            sys.exit(1)


# --- step 4: owner ID via getUpdates ------------------------------------

async def _wait_for_pair(token: str, total_timeout_s: int = 600) -> tuple[int, str]:
    """Long-poll getUpdates until a message with text == 'pair' (case-insensitive)
    arrives. Returns (user_id, label). Raises asyncio.TimeoutError on cap."""
    offset: int | None = None
    api = f"https://api.telegram.org/bot{token}"
    deadline = time.monotonic() + total_timeout_s
    async with httpx.AsyncClient(timeout=35) as client:
        while time.monotonic() < deadline:
            params: dict = {"timeout": 30, "allowed_updates": '["message"]'}
            if offset is not None:
                params["offset"] = offset
            try:
                resp = await client.get(f"{api}/getUpdates", params=params)
            except httpx.HTTPError:
                await asyncio.sleep(2)
                continue
            if resp.status_code != 200:
                await asyncio.sleep(2)
                continue
            body = resp.json()
            if not body.get("ok"):
                await asyncio.sleep(2)
                continue
            updates = body.get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                if text.lower() != "pair":
                    continue
                frm = msg.get("from") or {}
                uid = frm.get("id")
                if uid is None:
                    continue
                handle = frm.get("username")
                first = frm.get("first_name") or "user"
                label = f"@{handle}" if handle else first
                return int(uid), label
    raise asyncio.TimeoutError()


def step_owner_id(bot_info: dict, bot_token: str) -> tuple[int, str]:
    _step_header(4, "Owner identification", "[required]")
    handle = bot_info.get("username", "")
    bot_url = f"https://t.me/{handle}" if handle else BOTFATHER_URL
    print(f"  Open your new bot in Telegram and send the message: pair")
    _confirm_open(bot_url, f"Open https://t.me/{handle} now?" if handle else "Open Telegram now?")
    print("  Waiting for the 'pair' message... (Ctrl+C to cancel, ~10 min cap)")
    try:
        uid, label = asyncio.run(_wait_for_pair(bot_token))
    except KeyboardInterrupt:
        print()
        _err("Cancelled.")
        sys.exit(1)
    except asyncio.TimeoutError:
        _err("Timed out after 10 minutes. Re-run `domlabs-bot init` to try again.")
        sys.exit(1)
    _ok(f"Got it — {label} (ID {uid}). Owner gating enabled.")
    return uid, label


# --- step 5: persona ----------------------------------------------------

def _is_skip(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip().lower()
    return v in ("", "skip")


def step_persona() -> dict[str, str]:
    """Returns the substitution dict used by the persona templates."""
    _step_header(5, "About you", "[optional, type 'skip' to skip the whole step]")
    answer = questionary.text(
        "Type 'skip' to skip everything, or press Enter to continue:",
        default="",
    ).ask()
    if answer is None:
        sys.exit(1)
    if answer.strip().lower() == "skip":
        _ok("Persona skipped — neutral defaults written.")
        return {"USER_NAME": "you", "ASSISTANT_NAME": "Assistant", "VIBE": ""}

    user_name = questionary.text(
        "Your name (how the assistant should address you, blank to skip):",
        default="",
    ).ask()
    asst_name = questionary.text(
        "Your assistant's name (blank to skip):",
        default="",
    ).ask()
    vibe = questionary.text(
        "Vibe in one sentence (blank to skip):",
        default="",
    ).ask()

    vars = {
        "USER_NAME": (user_name or "").strip() or "you",
        "ASSISTANT_NAME": (asst_name or "").strip() or "Assistant",
        "VIBE": (vibe or "").strip(),
    }
    _ok("Persona templates written.")
    return vars


# --- step 6: projects ---------------------------------------------------

def step_projects() -> dict[str, str]:
    _step_header(6, "Projects", "[Enter accepts the default; you can always /cd later]")
    print("  These are directories the bot can switch between via `/project <name>`.")
    print("  Defaulting your first project to the directory you're in now.")
    cwd = Path.cwd().resolve()
    registry: dict[str, str] = {}
    first = True
    while True:
        if first:
            path_in = questionary.text(
                "Project path:",
                default=str(cwd),
            ).ask()
        else:
            path_in = questionary.text(
                "Another project path (Enter to finish):",
                default="",
            ).ask()
        if path_in is None:
            sys.exit(1)
        path_in = path_in.strip()
        if not first and not path_in:
            break  # done adding extras
        if not path_in:
            # First and empty — fall back to cwd anyway.
            path_in = str(cwd)
        path = Path(path_in).expanduser()
        if not path.exists() or not path.is_dir():
            _err(f"Not a directory: {path}")
            if first:
                _warn(f"Using {cwd} instead.")
                path = cwd
            else:
                continue
        suggested = path.name or "default"
        name_in = questionary.text(
            "Name for this project:",
            default=suggested,
        ).ask()
        if name_in is None:
            sys.exit(1)
        name = (name_in or "").strip() or suggested
        registry[name] = str(path.resolve())
        _ok(f"added: {name} → {registry[name]}")
        first = False
        # After the first, ask whether to keep adding.
        more = questionary.confirm("Add another project?", default=False).ask()
        if not more:
            break
    print(f"  ✓ {len(registry)} project{'s' if len(registry) != 1 else ''} saved.")
    return registry


# --- entrypoint ---------------------------------------------------------

def _backup_existing(root: Path) -> Path:
    """Move an existing root to a sibling .bak directory with a timestamp."""
    bak = root.with_name(root.name + ".bak")
    # Avoid collision: tack a counter on if .bak already exists.
    n = 1
    final = bak
    while final.exists():
        final = bak.with_name(bak.name + f".{n}")
        n += 1
    shutil.move(str(root), str(final))
    return final


def _write_env(
    env_path: Path,
    *,
    anthropic: str,
    bot: str,
    owner: int,
    model: str,
) -> None:
    """Write a fresh .env. Preserves no existing custom keys — the wizard owns this."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    # Empty API key means the user is on Claude Code Pro/Max — leave the line
    # commented so the spawned CLI uses its own stored auth.
    anthropic_line = (
        f"ANTHROPIC_API_KEY={anthropic}\n"
        if anthropic
        else "# ANTHROPIC_API_KEY=  # leave unset to use Claude Code's stored login\n"
    )
    body = (
        "# Written by `domlabs-bot init`. Hand-edit later if you need to.\n"
        f"{anthropic_line}"
        f"BOT_TOKEN={bot}\n"
        f"OWNER_USER_ID={owner}\n"
        f"MODEL={model}\n"
        "IDLE_TIMEOUT_MINUTES=15\n"
        "VOICE_ENABLED=false\n"
        "# GEMINI_API_KEY=\n"
        "# CLAUDE_CLI_PATH=\n"
        "# DEFAULT_CWD=\n"
    )
    env_path.write_text(body, encoding="utf-8")


def _write_projects(projects_path: Path, registry: dict[str, str]) -> None:
    projects_path.parent.mkdir(parents=True, exist_ok=True)
    projects_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run() -> int:
    from . import __version__ as _ver  # late import to avoid circulars
    bar = "═" * 60
    print()
    print(bar)
    print("  domlabs-bot — Use Claude Code from your phone")
    print(f"  Setup wizard · v{_ver}")
    print(bar)
    print()
    print("  Six steps. Mostly Enter-to-accept. About two minutes.")
    print()

    root = paths.root()
    if root.exists() and any(root.iterdir()):
        print(f"Existing setup detected at {root}.")
        ok = questionary.confirm(
            f"Reconfigure? Existing files will be backed up to {root}.bak/.",
            default=False,
        ).ask()
        if not ok:
            print("Aborting — your setup is unchanged.")
            return 0
        backup = _backup_existing(root)
        _ok(f"Backed up to {backup}")
    paths.ensure_root()

    anthropic_key = step_anthropic_key()
    model = step_model()
    bot_token, bot_info = step_bot_token()
    owner_id, owner_label = step_owner_id(bot_info, bot_token)
    persona_vars = step_persona()
    project_registry = step_projects()

    # --- write everything ------------------------------------------------
    _write_env(
        paths.env_file(),
        anthropic=anthropic_key,
        bot=bot_token,
        owner=owner_id,
        model=model,
    )
    _write_projects(paths.projects_file(), project_registry)
    write_template("IDENTITY.md.tmpl", paths.identity_file(), persona_vars)
    write_template("USER.md.tmpl", paths.user_file(), persona_vars)
    write_template("SOUL.md.tmpl", paths.soul_file(), persona_vars)
    write_template("MEMORY.md.tmpl", paths.memory_file(), persona_vars)
    paths.memory_dir().mkdir(parents=True, exist_ok=True)

    print()
    print("─" * 60)
    print(" Setup complete.")
    print("─" * 60)
    print()
    bot_handle = bot_info.get("username", "")
    bot_label = f"@{bot_handle}" if bot_handle else "(unknown)"
    auth_label = "API key" if anthropic_key else "Claude Code login (Pro/Max)"
    asst_name = persona_vars.get("ASSISTANT_NAME") or "Assistant"
    user_name = persona_vars.get("USER_NAME") or "you"
    proj_count = len(project_registry)
    proj_lead = next(iter(project_registry.items()), ("default", str(root)))
    print(f"  Bot:        {bot_label}  →  https://t.me/{bot_handle}" if bot_handle else f"  Bot:        {bot_label}")
    print(f"  Owner:      {owner_label} (ID {owner_id})")
    print(f"  Auth:       {auth_label}")
    print(f"  Model:      {model or '(SDK default)'}")
    print(f"  Persona:    {asst_name} → addresses you as '{user_name}'")
    print(f"  Projects:   {proj_count} ({proj_lead[0]} → {proj_lead[1]})")
    print(f"  Data root:  {root}")
    print()
    print("  Next steps:")
    print(f"    1.  domlabs-bot start            # foreground — Ctrl+C to stop")
    print(f"    2.  domlabs-bot start --daemon   # run on boot in the background")
    print(f"    3.  open Telegram → message {bot_label} → say hi")
    print()
    print(f"  Hand-edit anything later in: {root}/.env")
    print(f"  Tail logs with:              domlabs-bot logs -f")
    print()
    return 0

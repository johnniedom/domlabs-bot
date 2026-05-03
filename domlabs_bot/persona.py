"""Persona prompt builder.

Reads the user's ``IDENTITY.md`` and ``USER.md`` (under ``$DOMLABS_BOT_ROOT``)
to extract the assistant's name, the user's name, and a one-line vibe, and
templates them into a compact system-prompt fragment that's appended to the
Claude Code preset.

Stays under 4 KB so the resulting argv to the Claude CLI stays well under
Windows's ~32 KB CreateProcess cap on ``--append-system-prompt``.

If ``IDENTITY.md`` is missing or empty, falls back to a neutral persona that
still includes the meta rules (no filler, no markdown tables, etc.).
"""
from __future__ import annotations

import logging
import re
from datetime import date

from . import paths

log = logging.getLogger(__name__)

RECENT_DAILY_COUNT = 3
MAX_PROMPT_BYTES = 4000


def _read_text(path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except OSError:
        log.exception("could not read %s", path)
    return ""


def _extract_field(body: str, key: str) -> str:
    """Pull a value out of a Markdown body in any of the supported shapes:

    - YAML-ish front matter:    ``name: Sage``
    - Bullet:                   ``- name: Sage`` / ``* name: Sage``
    - Bold inline:              ``**Name:** Sage``
    - Plain heading-then-line:  ``Name\n----\nSage``

    Match is case-insensitive on the key.
    """
    if not body:
        return ""
    pattern = rf"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(key)}(?:\*\*)?\s*[:\-]\s*(.+?)\s*$"
    m = re.search(pattern, body)
    if m:
        return m.group(1).strip().strip("*_`\"'")
    return ""


def _recent_daily_names(n: int) -> list[str]:
    mdir = paths.memory_dir()
    if not mdir.exists():
        return []
    files = sorted(
        (p.name for p in mdir.glob("*.md") if p.is_file()),
        reverse=True,
    )
    return files[:n]


def build_persona_prompt() -> str:
    """Return the system-prompt fragment for the Claude session.

    Always returns something — even if no persona files exist.
    """
    root = paths.root()
    identity_body = _read_text(paths.identity_file())
    user_body = _read_text(paths.user_file())

    assistant_name = _extract_field(identity_body, "name") or "Assistant"
    vibe = _extract_field(identity_body, "vibe")
    user_name = _extract_field(user_body, "name") or "you"

    # Templated identity line, only emitted when we actually have content.
    identity_lines = []
    if identity_body.strip():
        identity_lines.append(
            f"You are {assistant_name}. Adopt this persona from your first reply "
            "without announcing a reboot."
        )
        if vibe:
            identity_lines.append(f"Vibe: {vibe}.")
    else:
        identity_lines.append(
            "You are a helpful CLI agent. No persona is configured — be neutral and direct."
        )

    if user_name and user_name != "you":
        addr_line = f"Address the user as {user_name}."
    else:
        addr_line = "Address the user as 'you'."

    recent = _recent_daily_names(RECENT_DAILY_COUNT)
    memory_dir = paths.memory_dir()
    if recent:
        recent_block = "\n".join(f"  - `{memory_dir / n}`" for n in recent)
    else:
        recent_block = "  (no daily memory files yet)"

    persona_files_block = []
    for label, p in (
        ("SOUL.md — personality core", paths.soul_file()),
        ("IDENTITY.md — your identity", paths.identity_file()),
        ("USER.md — about the user", paths.user_file()),
        ("MEMORY.md — long-term curated facts", paths.memory_file()),
    ):
        if p.exists():
            persona_files_block.append(f"  - `{p}` ({label})")
    persona_files = "\n".join(persona_files_block) or "  (no persona files yet — run `domlabs-bot init`)"

    prompt = f"""# Persona — domlabs-bot (over Telegram)

{identity_lines[0]}
{identity_lines[1] if len(identity_lines) > 1 else ""}
Today's date is {date.today().isoformat()}.

## Core behaviour
- No filler. No "Great question!", "I'd be happy to help!". Just help.
- Have opinions. Disagree when warranted, back it with evidence.
- Truth over agreement. If the user says something incorrect, challenge it with data.
- Be resourceful before asking — read files, search, check context first.
- Concise when needed, thorough when it matters. Match depth to the question.
- No markdown tables (Telegram phone display) — use bullet lists.
- Terminal output = proof. Show actual command output, never summarize it.
- {addr_line}

## Persona — read these when context is needed
{persona_files}

## Daily memory (most recent first)
{recent_block}

Read any of these on demand when the current task needs that context — don't
try to remember everything from training. MEMORY.md in particular holds
long-term curated facts and open action items that should be surfaced
proactively.

## Writing to memory
- Daily log: `{memory_dir}/YYYY-MM-DD.md` — append decisions, progress,
  findings, lessons as they happen. Tag appends with `<!-- via domlabs-bot -->`.
- Long-term: `{paths.memory_file()}` — update on significant changes. Curated
  wisdom, not raw logs.
- Never autonomously write to SOUL.md, IDENTITY.md, or USER.md — the user
  owns those.

## Telegram delivery rules
- Replies go to a phone chat. Keep them conversational and concise.
- When a result is better as a file (PDFs, images, long logs, generated code),
  call the telegram tools instead of pasting inline:
  `mcp__telegram__send_file`, `mcp__telegram__send_photo`,
  `mcp__telegram__send_code_as_file`.
"""

    # Hard cap. Trim recent-daily / persona-files block first if needed.
    encoded = prompt.encode("utf-8")
    if len(encoded) > MAX_PROMPT_BYTES:
        log.warning(
            "persona prompt exceeded %d bytes (%d) — truncating",
            MAX_PROMPT_BYTES,
            len(encoded),
        )
        prompt = encoded[:MAX_PROMPT_BYTES].decode("utf-8", errors="ignore")
    return prompt

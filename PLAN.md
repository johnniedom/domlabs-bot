# domlabs-bot — Implementation Plan (v1)

> Decisions locked in grilling session 2026-05-02 with Johnnie. Don't second-guess these — implement them.

## What this is

A pipx-installable Python CLI that lets a developer use Claude Code from their phone via Telegram. They install it, run `init` once, run `start`, and chat with their codebase from anywhere.

## Reference implementation

`C:\Users\johnn\cc-telegram\` — already works for one user (Johnnie). Uses Claude Agent SDK + python-telegram-bot. **Do not fork in place.** Build a fresh package at `C:\Users\johnn\Desktop\domlabs-bot\` and port the relevant code, decoupling it from Johnnie-specific paths and persona.

Read these source files before starting:
- `cc-telegram/README.md` — overall architecture
- `cc-telegram/src/main.py` — entry point + command handlers
- `cc-telegram/src/session.py` — multi-project session manager (KEEP this)
- `cc-telegram/src/persona.py` — persona prompt builder (REWRITE this)
- `cc-telegram/src/config.py` — env config (PORT + extend)
- `cc-telegram/src/telegram_tools.py` — telegram MCP server (KEEP this)
- `cc-telegram/src/tts.py`, `transcribe.py` — voice (KEEP, gate behind config flag)
- `cc-telegram/src/projects.py` — project storage (KEEP)
- `cc-telegram/src/memory_writer.py` — auto-summary (KEEP)
- `cc-telegram/src/formatting.py` — message formatting (KEEP)
- `cc-telegram/start.bat`, `run-hidden.vbs` — Windows daemon (REPLACE with cross-platform)

## Locked architectural decisions

1. **Claude-only runtime.** Uses `claude_agent_sdk` Python package. No Gemini/OpenAI/Codex.
2. **Multi-project sessions.** Keep cc-telegram's full SessionManager + `/project` switching + `projects.json`. Init wizard collects projects upfront, user can add more later via config or commands.
3. **Voice opt-in.** Don't strip the code. Add a `VOICE_ENABLED=false` config default. When `false`, voice handlers are no-ops and TTS deps are optional installs (`pip install domlabs-bot[voice]`).
4. **Owner-gating mandatory.** Single `OWNER_USER_ID` per bot — non-owner messages dropped silently. Same as cc-telegram.
5. **Cross-platform daemon support.** All three OSes from v1: Windows (Task Scheduler), macOS (launchd), Linux (systemd user). Commands: `domlabs-bot start --daemon`, `domlabs-bot stop`, `domlabs-bot uninstall-daemon`.
6. **MIT license, public GitHub repo under Dom Labs (`johnniedom/domlabs-bot`).**
7. **pipx distribution.** `pipx install domlabs-bot && domlabs-bot init && domlabs-bot start`. Package name on PyPI: `domlabs-bot` (verified available 2026-05-02).
8. **Anthropic positioning** — strict nominative use:
    - Tagline: *"Use Claude Code from your phone. Ship from anywhere."*
    - Footer disclaimer: *"Not affiliated with Anthropic. Claude is a trademark of Anthropic, PBC."*
    - The string "Claude" or "Anthropic" must NOT appear in the package name, CLI command name, or any user-facing branding.

## Persona model — fully custom, no Dom anywhere

The reference impl's `persona.py` hardcodes "You are Dom" and points at `C:/Users/johnn/clawd/`. **Rewrite from scratch.**

Files live at `~/.domlabs-bot/` (override via `$DOMLABS_BOT_ROOT` env):
- `SOUL.md` — personality core, hand-authored by user
- `IDENTITY.md` — assistant's name, vibe
- `USER.md` — about the user (their name, preferences)
- `MEMORY.md` — long-term curated facts, agent-curated
- `memory/YYYY-MM-DD.md` — daily logs, agent-appended

Init wizard scaffolds these from templates the wizard fills in based on user input. The agent NEVER autonomously writes to SOUL/IDENTITY/USER — only to MEMORY.md and daily files.

The new `persona.py`:
- Reads `$DOMLABS_BOT_ROOT` (default `~/.domlabs-bot/`)
- If `IDENTITY.md` exists, extracts the assistant's name and vibe and templates them into the system prompt
- If `IDENTITY.md` is empty/missing (user skipped persona), use a neutral fallback ("You are a helpful CLI agent. Address the user as 'you'.")
- Generic meta rules ALWAYS included regardless of persona presence:
  - No filler ("Great question!", "I'd be happy to help!")
  - Have opinions, disagree when warranted
  - Truth over agreement
  - Be resourceful before asking
  - Concise when needed, thorough when it matters
  - No markdown tables (Telegram phone display)
  - Terminal output as proof
- Lists pointers to MEMORY.md + recent daily files so agent can read on demand
- Stays under 4 KB (Windows argv 32 KB limit on `--append-system-prompt`)

## Init wizard — exact UX

```
$ domlabs-bot init

Welcome to domlabs-bot.

Step 1/6 — Anthropic API key  [required]
  Get one: https://console.anthropic.com/settings/keys
  → Open in browser? [Y/n]
  Paste your key: sk-ant-...
  [validates with a /messages "hi" ping using claude-haiku-4-5-20251001, max_tokens=1]
  ✓ Verified

Step 2/6 — Pick a model  [optional, defaults to Sonnet 4.6]
  Which Claude model should your assistant use?
  [1] claude-sonnet-4-6      — balanced (recommended for chat)
  [2] claude-opus-4-7        — most capable, most expensive
  [3] claude-haiku-4-5       — cheapest, fastest
  [4] custom (enter a model ID)
  Choice [1]: 1
  ✓ claude-sonnet-4-6 selected.

Step 3/6 — Create your bot  [required]
  We'll open BotFather in your default browser / Telegram desktop.
  → Open https://t.me/BotFather now? [Y/n]
  ✓ Opened.
  In BotFather, run: /newbot
  Pick a display name and a username ending in 'bot'.
  When BotFather gives you a token (looks like 1234:ABC...), paste here:
  Token: ...
  [validates with getMe]
  ✓ @sage_bot verified — created just now.

Step 4/6 — Owner identification  [required]
  Open your new bot in Telegram and send the message: pair
  → Open https://t.me/sage_bot now? [Y/n]
  ✓ Opened.
  Waiting for the 'pair' message... (Ctrl+C to cancel)
  ✓ Got it — @paschal (ID 123456789). Owner gating enabled.

Step 5/6 — About you  [optional, type 'skip' to skip]
  Your name (how the assistant should address you): Paschal
  Your assistant's name: Sage
  Vibe in one sentence: warm but no-bullshit; pushes back when I'm wrong
  [if 'skip': writes neutral templates, agent addresses user as "you"]
  ✓ Persona templates written.

Step 6/6 — Projects  [first required, additional optional]
  Add a project. Path, then name. Type 'done' on path to finish.
  Path: /Users/paschal/code/fundbrave
  Name: fundbrave
  Path: done
  ✓ 1 project saved.

✓ Setup complete. Files written to ~/.domlabs-bot/

Run `domlabs-bot start` to go live.
Run `domlabs-bot start --daemon` to run on boot.
```

**Step 2 (model selection) implementation notes:**
- Static list of three known-good models with a "custom" escape hatch.
- Default is Sonnet 4.6 (right balance for phone-chat — Opus burns API budget on casual messages, Haiku is thin for coding assistance).
- Choice is written to `.env` as `MODEL=<id>`. Empty `MODEL` means SDK default applies.
- **No re-validation** of the chosen model against the user's API key. Some keys are tier-gated; probing here adds cost and a lot of error paths. If the chosen model is rejected at runtime, the user finds out at first message and can edit `.env`. Worth the simplicity tradeoff.
- Custom path warns "not validated against your key" so user knows they're on their own.

Implementation notes:
- Use `questionary` for interactive prompts (validation + retry on invalid input).
- Step 1: open URL via `webbrowser.open()` only after [Y/n] confirms. Validate with a real call to `https://api.anthropic.com/v1/messages` (model `claude-haiku-4-5-20251001`, body `{"role":"user","content":"hi"}`, `max_tokens=1`). Retry loop on 401/403.
- Step 2: same `webbrowser.open()` pattern → `https://t.me/BotFather`. Validate token with `https://api.telegram.org/bot{TOKEN}/getMe`. On success, surface bot username + first_name from response so user gets concrete confirmation, not just an abstract checkmark.
- **Step 3 — auto-detect owner ID via the bot itself.** Replaces the @userinfobot detour entirely. Flow:
  - Resolve the bot username from the `getMe` response captured in Step 2.
  - Open `https://t.me/<bot_username>` via `webbrowser.open()` after [Y/n] confirms.
  - Start a `getUpdates` long-polling loop (`offset` advances, 30s timeout per call, total wait cap ~10 min).
  - Filter incoming updates for messages whose `text == "pair"` (case-insensitive, exact match — no `/start`, no other text). The literal `pair` phrase disambiguates if the bot username happened to leak and a stranger messages it during setup.
  - First match wins. Extract `update.message.from.id` and `update.message.from.username` (or `first_name` if no username).
  - Echo confirmation, write `OWNER_USER_ID` to `.env`. On Ctrl+C, abort wizard cleanly.
- Step 4: free text, each of the three fields individually skippable (empty = skip, or whole step skippable with literal 'skip'). If skipped: write neutral templates with `{{ASSISTANT_NAME}}` → "Assistant", `{{USER_NAME}}` → "you", `{{VIBE}}` → empty.
- Step 5: at least one project required; loop until user types 'done' on path.

Browser-open behavior: `webbrowser.open()` will open the user's default handler. On most setups `https://t.me/...` URLs route to the Telegram desktop app if installed, otherwise to t.me's web interface which deep-links into Telegram Web. Always print the URL above the [Y/n] prompt so user can copy it manually if `webbrowser.open()` fails or they decline.

If user re-runs `init`, detect existing `~/.domlabs-bot/` and ask "Reconfigure? (existing files will be backed up to ~/.domlabs-bot.bak/)".

## Cross-platform daemon

`domlabs-bot start --daemon` needs to:
1. Detect OS (Windows/macOS/Linux)
2. Write the appropriate service definition
3. Register + start it

Suggested implementation paths (subagent picks the cleanest):
- **Windows:** generate Task Scheduler XML, register via `schtasks /Create`. Or use `pywin32` to bind directly. Should boot on user logon, run hidden, restart on failure.
- **macOS:** write `~/Library/LaunchAgents/com.domlabs.bot.plist`, `launchctl load ~/Library/LaunchAgents/com.domlabs.bot.plist`. `RunAtLoad = true`, `KeepAlive = true`.
- **Linux:** write `~/.config/systemd/user/domlabs-bot.service`, `systemctl --user enable --now domlabs-bot`. Document `loginctl enable-linger $USER` if user wants the service to survive logout.

`--stop` halts the running daemon. `--uninstall-daemon` halts + removes the service definition.

Logs go to `~/.domlabs-bot/logs/domlabs-bot.log` regardless of OS.

## Package layout

```
domlabs-bot/
├── pyproject.toml           # entry point: domlabs-bot = domlabs_bot.cli:main
├── README.md                # tagline, install, usage, disclaimer footer
├── LICENSE                  # MIT
├── .gitignore
├── .env.example             # commented template
├── domlabs_bot/
│   ├── __init__.py
│   ├── cli.py               # argparse entry: init/start/stop/status/logs/uninstall-daemon
│   ├── init_wizard.py       # the 6-step wizard
│   ├── config.py            # env + ~/.domlabs-bot/.env loading
│   ├── persona.py           # persona prompt builder (rewritten)
│   ├── session.py           # ported SessionManager
│   ├── projects.py          # ported project storage
│   ├── telegram_tools.py    # ported MCP server
│   ├── memory_writer.py     # ported auto-summary
│   ├── formatting.py        # ported
│   ├── voice/
│   │   ├── __init__.py
│   │   ├── tts.py           # ported, gated by VOICE_ENABLED
│   │   └── transcribe.py    # ported, gated by VOICE_ENABLED
│   ├── daemon/
│   │   ├── __init__.py      # OS detection + dispatch
│   │   ├── windows.py       # Task Scheduler
│   │   ├── macos.py         # launchd
│   │   └── linux.py         # systemd user
│   └── templates/
│       ├── SOUL.md.tmpl
│       ├── IDENTITY.md.tmpl
│       ├── USER.md.tmpl
│       └── MEMORY.md.tmpl
└── tests/
    └── (skip for v1 unless trivial)
```

`pyproject.toml` essentials:
- `[project]` name = `domlabs-bot`, version = `0.1.0`, license = `MIT`
- `dependencies`: `claude-agent-sdk`, `python-telegram-bot`, `python-dotenv`, `questionary` or `inquirer`, `httpx`
- `optional-dependencies.voice`: `edge-tts`, `google-genai` (or whatever the voice deps need)
- `[project.scripts]` `domlabs-bot = "domlabs_bot.cli:main"`

## README structure

```markdown
# domlabs-bot

**Use Claude Code from your phone. Ship from anywhere.**

A self-hosted Telegram bridge that lets you chat with Claude Code on your laptop
from your phone. Persistent multi-project sessions, owner-gated, customizable
persona.

## Install

    pipx install domlabs-bot
    domlabs-bot init
    domlabs-bot start

(...quick-start guide...)

## How it works

(...architecture diagram...)

## Persona

(...explain the bring-your-own model, how SOUL.md / IDENTITY.md / USER.md work...)

## Voice (optional)

    pipx install 'domlabs-bot[voice]'

(...)

## Roadmap

- v1.1: Homebrew tap
- v2: domlabs-bot-control (Windows screen + UIA control via MCP)

## License

MIT

---

*Not affiliated with Anthropic. Claude is a trademark of Anthropic, PBC.*
*Built by [Dom Labs](https://domlabs.dev).*
```

## What to skip / explicitly not build

- Tests (v1 ships without; cc-telegram doesn't have any either)
- Docker image (v2)
- Homebrew tap (v1.1)
- Multi-user-per-bot (single owner only)
- Web dashboard (never planned)
- Snap/screen control / claw-control MCP (separate package, v2)
- Provider abstraction for non-Claude LLMs (deferred)

## Audience priority

Paschal first (Lead Engineer + CEO of FundBrave, on Mac most likely — verify before shipping, but plan for Mac as primary). Then public.

## Definition of done for v1

- `pipx install domlabs-bot` works from PyPI test index
- `domlabs-bot init` runs the 6-step wizard, validates inputs, scaffolds `~/.domlabs-bot/`
- `domlabs-bot start` runs the bridge in foreground, Telegram messages flow to Claude and back
- `domlabs-bot start --daemon` registers + starts a service on Windows, macOS, AND Linux
- Multi-project switching works (`/project name` over Telegram)
- Owner-gating works (other Telegram user IDs silently dropped)
- README has the trademark disclaimer
- Public GitHub repo at `github.com/johnniedom/domlabs-bot` exists with MIT license

When all of those pass: ship v0.1.0 to PyPI, send Paschal the install command.

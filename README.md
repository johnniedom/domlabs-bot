# domlabs-bot

**Use Claude Code from your phone. Ship from anywhere.**

A self-hosted Telegram bridge that lets you chat with Claude Code on your
laptop from your phone. Persistent multi-project sessions, owner-gated,
fully-customizable persona.

## Prerequisites

Before you install, you need:

- **Python 3.10 or newer** — `python --version` to check.
- **An Anthropic API key** — get one at <https://console.anthropic.com/settings/keys>.
- **Telegram** (desktop, web, or mobile) — to message @BotFather and create your bot.
- **`pipx`** (recommended). If you don't have it:
  ```bash
  python -m pip install --user pipx
  python -m pipx ensurepath
  # restart your terminal so PATH picks up pipx
  ```

## Install

The fastest path — clone the repo, run the setup script, and chain straight into the wizard:

```bash
# macOS / Linux
./setup.sh --init

# Windows (PowerShell)
.\setup.ps1 -Init
```

The script:

- Auto-installs `pipx` if it's missing.
- Runs `pipx install -e . --force` against this directory.
- Filters pipx's noisy `done! ✨ 🌟 ✨` line out of the output.
- Optionally chains into `domlabs-bot init` (`--init` / `-Init` flag).

Or, if you'd rather drive pipx yourself:

```bash
pipx install domlabs-bot
domlabs-bot init
domlabs-bot start
```

That's it. The `init` wizard walks you through:

1. Anthropic API key (validated against the API)
2. Pick a model (defaults to Sonnet 4.6; choose Opus, Haiku, or a custom ID)
3. Creating a Telegram bot via BotFather (validated with `getMe`)
4. Owner identification — your bot opens; you send the message `pair`; the
   wizard auto-detects your Telegram user ID. No third-party detour.
5. Persona setup (optional, skippable)
6. Project paths the bot can switch between

Everything lives under `~/.domlabs-bot/`. Set `DOMLABS_BOT_ROOT` to put it
elsewhere.

## Run on boot

```bash
domlabs-bot start --daemon       # install + start as an OS service
domlabs-bot status               # check it's healthy
domlabs-bot stop                 # halt it
domlabs-bot uninstall-daemon     # remove the service definition
domlabs-bot logs -f              # tail the log file
```

Daemon installer:

- **Windows** — registers a per-user Scheduled Task (logon trigger, hidden, restart on failure)
- **macOS** — writes `~/Library/LaunchAgents/com.domlabs.bot.plist` and bootstraps it via `launchctl`
- **Linux** — writes `~/.config/systemd/user/domlabs-bot.service` and enables it. Run `loginctl enable-linger $USER` if you want it to survive logout.

## How it works

```
Telegram ──► python-telegram-bot poller ──► SessionManager ──► Claude Agent SDK ──► claude CLI
                                                ▲
                                                │
                                          per-project sessions, idle-recycled,
                                          auto-summarised to ~/.domlabs-bot/memory/
```

- One persistent Claude session per project. `/project name` switches the
  current target.
- Voice notes (optional) → Gemini transcription → session.
- Photos → vision-enabled multi-modal turn → session.
- Idle sessions are summarised into the daily memory file before disposal.
- The agent has Telegram-aware tools (`mcp__telegram__send_file`,
  `send_photo`, `send_code_as_file`) for delivering large/binary results.

## Persona — bring your own

`init` scaffolds four files under `~/.domlabs-bot/` you can edit by hand:

- `IDENTITY.md` — your assistant's name + vibe (the runtime parses these and
  templates them into the system prompt)
- `USER.md` — your name + anything you want the assistant to know about you
- `SOUL.md` — personality core, principles, taste. The agent reads it on demand.
- `MEMORY.md` — long-term curated facts and project state. The agent may
  update this; it will never autonomously edit `SOUL.md`, `IDENTITY.md`, or `USER.md`.

You can skip the persona during `init`. The bot still works — it just
addresses you as "you" and runs without character.

## Voice (optional)

Voice notes in / TTS replies out are gated behind an extras install:

```bash
pipx install 'domlabs-bot[voice]'
# then in ~/.domlabs-bot/.env:
VOICE_ENABLED=true
GEMINI_API_KEY=your-key-here
```

Toggle reply mode from Telegram: `/voice on`, `/voice once`, `/voice off`.

## Configuration

Hand-edit `~/.domlabs-bot/.env` for things the wizard doesn't ask:

```env
IDLE_TIMEOUT_MINUTES=15      # session recycle threshold
MODEL=claude-sonnet-4-6      # override default model (the wizard sets this)
CLAUDE_CLI_PATH=/usr/local/bin/claude   # if not on PATH
DEFAULT_CWD=/Users/me/code   # session default
```

## Telegram commands

```
/start           — banner + commands
/status          — session state
/project         — list / switch / add / rm projects
/new             — fresh session for the current project
/mem <text>      — quick-append to today's daily memory
/voice on|off|once — voice replies
```

Plain text, photos, and voice notes route to the current project session.

## Troubleshooting

**`domlabs-bot: command not found` after install.**
Pipx put the script in a directory not on your PATH. Run `pipx ensurepath` and restart your terminal. On Windows, the directory is typically `%USERPROFILE%\.local\bin`.

**The bot isn't replying.**
Two common causes:
- Another process is polling the same bot token (e.g. an older `cc-telegram` instance, or a second `domlabs-bot start`). Only one poller is allowed per bot. `domlabs-bot stop` to halt the daemon, or kill the conflicting process.
- The wizard's owner-detect grabbed the wrong user ID. Check `OWNER_USER_ID` in `~/.domlabs-bot/.env` against your Telegram ID. Re-run `domlabs-bot init` to reconfigure (your old config is backed up to `~/.domlabs-bot.bak/`).

**The wizard hangs on Step 4 ("Waiting for the 'pair' message").**
You're expected to open your new bot in Telegram and send the literal word `pair`. The wizard polls Telegram's `getUpdates` for that message. Cap is 10 minutes — Ctrl+C to abort, then re-run.

**Anthropic key validation fails with HTTP 4xx.**
401/403 means the key is wrong or revoked — generate a fresh one. Anything else (404, 5xx, network) means something rare happened; the wizard will let you proceed without validating.

**Logs.**
The bridge writes to `~/.domlabs-bot/logs/domlabs-bot.log`. Tail it live with:
```bash
domlabs-bot logs -f
```

**Reset everything.**
```bash
domlabs-bot uninstall-daemon
rm -rf ~/.domlabs-bot
```
Then `domlabs-bot init` to start fresh.

## Roadmap

- v1.1: Homebrew tap
- v2: domlabs-bot-control (Windows screen + UIA control via MCP)

## Contributing

Issues and PRs welcome at <https://github.com/johnniedom/domlabs-bot>.

## License

MIT — see [LICENSE](LICENSE).

---

*Not affiliated with Anthropic. Claude is a trademark of Anthropic, PBC.*
*Built by [Dom Labs](https://domlabs.dev).*

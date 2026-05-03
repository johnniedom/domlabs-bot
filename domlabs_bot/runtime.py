"""Telegram bot bridge to multi-project persistent Claude Agent SDK sessions.

Only messages from ``OWNER_USER_ID`` are processed. Everything else is dropped.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import tempfile
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config, memory_writer, paths, projects
from .formatting import split_for_telegram
from .session import SessionManager

log = logging.getLogger("domlabs-bot")

# Voice-reply toggle: "off" | "on" | "once"
voice_mode: str = "off"

session: SessionManager | None = None  # populated after config.load()


# Keyword → emoji rules for the "I saw your message" ack reaction.
# Only emojis from Telegram's standard bot-reaction set (no premium required).
# Checked in order; first match wins. Keywords lowercase.
_ACK_RULES: list[tuple[tuple[str, ...], str]] = [
    (("wow", "whoa", "insane", "crazy", "mind blown", "🤯"), "🤯"),
    (("fast", "quick", "zoom", "snappy", "speedy"), "⚡"),
    (("fire", "🔥", "dope", "sick", "sweet", "clean"), "🔥"),
    (("thank", "🙏", "appreciate", "grateful"), "🙏"),
    (("lol", "lmao", "haha", "hehe", "😂", "🤣"), "🤣"),
    (("love", "❤", "🥰"), "❤"),
    (("hi ", "hey", "hello", "yo ", "sup", "howdy"), "🫡"),
    (("tired", "exhausted", "sleepy", "sleep"), "😴"),
    (("bug", "error", "broken", "crash", "fail", "wtf"), "😱"),
    (("bad", "nope", "nah", " no ", "terrible", "awful"), "👎"),
    (("deploy", "ship", "merge", "commit", "push"), "✍"),
    (("ok", "got it", "cool", "sure", "alright"), "👌"),
    (("yes", "yep", "yeah", "good", "nice", "great"), "👍"),
    (("?",), "🤔"),
]
_ACK_FALLBACK: tuple[str, ...] = ("👀", "🤔", "👾")
_DONE_ACKS: tuple[str, ...] = ("🤝", "💯", "👌", "🔥", "🆒")


def _owner_only(handler):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != config.OWNER_USER_ID:
            log.warning(
                "Dropped message from non-owner id=%s username=%s",
                getattr(user, "id", None),
                getattr(user, "username", None),
            )
            return
        return await handler(update, ctx)

    return wrapper


async def _send_text(update: Update, text: str) -> None:
    for chunk in split_for_telegram(text):
        await update.effective_chat.send_message(chunk)


def _pick_ack_reaction(text: str | None) -> str:
    if not text:
        return "👀"
    lo = text.lower()
    for keywords, emoji in _ACK_RULES:
        for kw in keywords:
            if kw in lo:
                return emoji
    return random.choice(_ACK_FALLBACK)


async def _ack_received(update: Update, text: str | None = None) -> None:
    try:
        await update.message.set_reaction(reaction=_pick_ack_reaction(text))
    except TelegramError:
        pass


async def _ack_done(update: Update, *, ok: bool = True) -> None:
    emoji = random.choice(_DONE_ACKS) if ok else "😱"
    try:
        await update.message.set_reaction(reaction=emoji)
    except TelegramError:
        pass


async def _typing_pulse(update: Update, stop: asyncio.Event) -> None:
    """Refresh Telegram TYPING action every 4s until stop is set."""
    try:
        while not stop.is_set():
            try:
                await update.effective_chat.send_action(ChatAction.TYPING)
            except TelegramError:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        raise


async def _send_voice(update: Update, text: str) -> bool:
    """Try to send `text` as a TTS voice note. Returns True on success."""
    if not text.strip():
        return False
    if not config.VOICE_ENABLED:
        return False
    from .voice import tts  # deferred import — voice extras may not be installed

    path = await tts.synthesize(text)
    if path is None:
        return False
    try:
        with path.open("rb") as fh:
            await update.effective_chat.send_voice(fh)
        return True
    finally:
        try:
            path.unlink()
        except OSError:
            pass


@_owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "domlabs-bot online.\n\n"
        f"project: {session.current_project}\n"
        f"cwd: {session.cwd_of(session.current_project)}\n"
        f"idle timeout: {config.IDLE_TIMEOUT_MINUTES} min\n"
        f"voice: {'enabled' if config.VOICE_ENABLED else 'disabled'}\n\n"
        "Commands:\n"
        "/project — list / switch / add / rm projects\n"
        "/status — session state\n"
        "/new — fresh session (current project)\n"
        "/mem <text> — quick-append to today's daily memory\n"
        "/voice on|off|once — voice replies\n\n"
        "Plain text → current project session.\n"
        "Photos → analyzed by current project session.\n"
        "Voice notes → transcribed (if enabled) → sent to session."
    )
    await _send_text(update, msg)


@_owner_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [f"current: {session.current_project}", f"voice: {voice_mode}"]
    rows = session.status()
    if rows:
        lines.append("\nsessions:")
        for r in rows:
            flag = "alive" if r["alive"] else "idle/disposed"
            lines.append(f"  • {r['name']} [{flag}] — {r['cwd']}")
    else:
        lines.append("\nno sessions spawned yet.")
    await _send_text(update, "\n".join(lines))


@_owner_only
async def cmd_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    registry = projects.list_projects()

    if not args:
        lines = [f"current: {session.current_project}", "", "available:"]
        for name, cwd in sorted(registry.items()):
            marker = "→ " if name == session.current_project else "  "
            lines.append(f"  {marker}{name}  {cwd}")
        if not registry:
            lines.append("  (none — add one with `/project add`)")
        lines.append("\nusage:")
        lines.append("  /project <name>              — switch")
        lines.append("  /project add <name> <path>   — register")
        lines.append("  /project rm <name>           — remove")
        await _send_text(update, "\n".join(lines))
        return

    sub = args[0]
    if sub == "add":
        if len(args) < 3:
            await _send_text(update, "usage: /project add <name> <path>")
            return
        name = args[1]
        path = " ".join(args[2:])
        try:
            cwd = projects.add_project(name, path)
            await _send_text(update, f"added: {name} → {cwd}")
        except ValueError as e:
            await _send_text(update, f"error: {e}")
        return

    if sub == "rm":
        if len(args) < 2:
            await _send_text(update, "usage: /project rm <name>")
            return
        name = args[1]
        try:
            ok = projects.remove_project(name)
            await _send_text(update, "removed." if ok else f"no such project: {name}")
        except ValueError as e:
            await _send_text(update, f"error: {e}")
        return

    name = sub
    try:
        cwd = await session.switch(name)
        await _send_text(update, f"switched to {name}\ncwd: {cwd}")
    except ValueError as e:
        await _send_text(update, f"error: {e}")


@_owner_only
async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await session.reset_current()
    await _send_text(
        update,
        f"session reset for '{session.current_project}'. next message spawns fresh.",
    )


@_owner_only
async def cmd_mem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args or []).strip()
    if not text and update.message.reply_to_message:
        text = (update.message.reply_to_message.text or "").strip()
    if not text:
        await _send_text(update, "usage: /mem <text>  (or reply to a message with /mem)")
        return
    path = memory_writer.append_note(text)
    await _send_text(update, f"saved to {path.name}")


@_owner_only
async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global voice_mode
    if not config.VOICE_ENABLED:
        await _send_text(
            update,
            "voice is disabled. install voice extras and set VOICE_ENABLED=true:\n"
            "  pipx inject domlabs-bot 'domlabs-bot[voice]'\n"
            "  echo VOICE_ENABLED=true >> ~/.domlabs-bot/.env",
        )
        return
    args = ctx.args or []
    if not args:
        await _send_text(update, f"voice: {voice_mode}\nusage: /voice on|off|once")
        return
    mode = args[0].lower()
    if mode not in ("on", "off", "once"):
        await _send_text(update, "usage: /voice on|off|once")
        return
    voice_mode = mode
    await _send_text(update, f"voice → {voice_mode}")


async def _route_to_session(update: Update, prompt, prompt_preview: str) -> None:
    global voice_mode
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_pulse(update, stop_typing))
    buffer: list[str] = []
    crashed = False

    async def flush_for_chat():
        if buffer:
            await _send_text(update, "".join(buffer))
            buffer.clear()

    collected: list[str] = []

    try:
        async for event in session.send(prompt, prompt_preview):
            etype = event["type"]
            if etype == "text":
                t = event["text"]
                collected.append(t)
                buffer.append(t)
                if voice_mode == "off" and sum(len(s) for s in buffer) > 3500:
                    await flush_for_chat()
            elif etype == "assistant_done":
                if voice_mode == "off":
                    await flush_for_chat()
            elif etype == "tool":
                if voice_mode == "off":
                    await flush_for_chat()
    except Exception as e:
        crashed = True
        log.exception("session.send failed")
        try:
            await flush_for_chat()
        except Exception:
            log.exception("flush after crash failed")
        err_type = type(e).__name__
        err_msg = str(e)[:500] or "(no message)"
        try:
            await _send_text(
                update,
                (
                    f"error: session crashed ({err_type})\n\n{err_msg}\n\n"
                    f"logs: {paths.log_file()}\nfix: /new"
                ),
            )
        except Exception:
            log.exception("failed to send crash notice")
        await _ack_done(update, ok=False)
        return
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except (asyncio.CancelledError, Exception):
            pass

    full_reply = "".join(collected).strip()

    if voice_mode in ("on", "once") and full_reply and config.VOICE_ENABLED:
        buffer.clear()
        await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
        sent = await _send_voice(update, full_reply)
        if not sent:
            await _send_text(update, full_reply)
        if voice_mode == "once":
            voice_mode = "off"
    else:
        if buffer:
            await flush_for_chat()

    if not crashed:
        await _ack_done(update, ok=True)


@_owner_only
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    await _ack_received(update, text)
    await _route_to_session(update, text, prompt_preview=text)


@_owner_only
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photos = update.message.photo or []
    if not photos:
        return
    caption = (update.message.caption or "").strip()
    await _ack_received(update, caption or None)
    best = photos[-1]

    tg_file = await best.get_file()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
        tmp = Path(fh.name)
    try:
        await tg_file.download_to_drive(tmp)
        data_b64 = base64.standard_b64encode(tmp.read_bytes()).decode()
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    user_text = caption or (
        "Take a look at this image — what do you see, and what should I do with it?"
    )
    content = [
        {"type": "text", "text": user_text},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": data_b64,
            },
        },
    ]
    await _route_to_session(update, content, prompt_preview=f"[image] {user_text}")


@_owner_only
async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice or update.message.audio
    if voice is None:
        return
    await _ack_received(update)

    if not config.VOICE_ENABLED:
        await _send_text(
            update,
            "voice is disabled. install voice extras and set VOICE_ENABLED=true.",
        )
        return

    from .voice import transcribe  # deferred import

    await update.effective_chat.send_action(ChatAction.TYPING)
    tg_file = await voice.get_file()
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as fh:
        tmp = Path(fh.name)
    try:
        await tg_file.download_to_drive(tmp)
        transcript = await transcribe.transcribe_audio(tmp, mime="audio/ogg")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    if not transcript:
        await _send_text(
            update,
            "couldn't transcribe that voice note — check GEMINI_API_KEY in your .env.",
        )
        return

    await _send_text(update, f"heard: {transcript}")
    await _route_to_session(update, transcript, prompt_preview=f"[voice] {transcript}")


async def _summarize_and_save(project: str, transcript: list[tuple[str, str]]) -> None:
    """Called by the idle reaper just before a session is disposed."""
    try:
        rendered = memory_writer.format_transcript(transcript, limit=30)
        if not rendered:
            return
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query as one_shot_query,
        )

        opts = ClaudeAgentOptions(
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are summarising a Telegram conversation between a user and "
                "their Claude Code agent. Write a tight 2-4 bullet summary of "
                "decisions made, progress, and any follow-ups. No preamble."
            ),
        )
        if config.MODEL:
            opts.model = config.MODEL
        prompt = f"Conversation:\n\n{rendered}\n\nSummarise."
        out_chunks: list[str] = []
        async for msg in one_shot_query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        out_chunks.append(block.text)
        summary = "".join(out_chunks).strip()
        if summary:
            memory_writer.append_summary(project, summary)
            log.info("[%s] idle summary written", project)
    except Exception:
        log.exception("[%s] idle summary failed", project)


_BOT_COMMANDS = [
    BotCommand("start", "Show help and the command list"),
    BotCommand("status", "Show current session + project state"),
    BotCommand("project", "List, switch, add, or remove projects"),
    BotCommand("new", "Start a fresh session for the current project"),
    BotCommand("mem", "Append a quick note to today's memory file"),
    BotCommand("voice", "Toggle voice replies on / off / once"),
]


async def _post_init(app: Application) -> None:
    session.pre_dispose = _summarize_and_save
    await session.start_reaper()
    # Register the command list with Telegram so the client shows autocomplete
    # (and the "Menu" button) when the user types `/`. Cached server-side per
    # bot — only needs to fire once per change, but cheap to re-set on every
    # bridge start so it always reflects the current handler list.
    try:
        await app.bot.set_my_commands(_BOT_COMMANDS)
        log.info("registered %d bot commands with Telegram", len(_BOT_COMMANDS))
    except TelegramError:
        log.exception("failed to register bot commands (autocomplete may be stale)")


async def _post_shutdown(app: Application) -> None:
    await session.stop_reaper()


def build_app() -> Application:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("project", cmd_project))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("mem", cmd_mem))
    app.add_handler(CommandHandler("voice", cmd_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def _setup_logging() -> None:
    paths.ensure_root()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(paths.log_file(), encoding="utf-8"),
        ],
    )


def run() -> None:
    """Entry point — load config, build app, run polling."""
    global session
    config.load(strict=True)
    _setup_logging()
    session = SessionManager()
    log.info(
        "Starting domlabs-bot. owner=%s default_cwd=%s timeout=%dm cli_path=%s root=%s",
        config.OWNER_USER_ID,
        config.DEFAULT_CWD,
        config.IDLE_TIMEOUT_MINUTES,
        config.CLI_PATH or "<PATH search>",
        paths.root(),
    )
    if not config.CLI_PATH:
        log.warning(
            "No claude CLI found on PATH. Set CLAUDE_CLI_PATH in .env or "
            "install Claude Code: https://claude.com/code"
        )
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

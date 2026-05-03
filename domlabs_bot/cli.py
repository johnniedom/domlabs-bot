"""``domlabs-bot`` command-line interface.

Subcommands:
  init               run the 6-step setup wizard
  start [--daemon]   run the bot in foreground (or install + start as a service)
  stop               stop the daemon (does nothing in foreground mode)
  status             show daemon + config status
  logs [-f]          tail the bot's log file
  uninstall-daemon   remove the OS service definition

All persistent state lives under ``$DOMLABS_BOT_ROOT`` (default ``~/.domlabs-bot/``).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__, paths


def _cmd_init(args: argparse.Namespace) -> int:
    from . import init_wizard

    return init_wizard.run()


def _cmd_start(args: argparse.Namespace) -> int:
    if args.daemon:
        from . import daemon as d

        try:
            print(d.install())
        except Exception as e:
            print(f"daemon install failed: {e}", file=sys.stderr)
            return 1
        return 0
    # Foreground.
    from . import runtime

    try:
        runtime.run()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    from . import daemon as d

    try:
        print(d.stop())
    except Exception as e:
        print(f"stop failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from . import config, daemon as d

    print(f"domlabs-bot {__version__}")
    print(f"  root:       {paths.root()}")
    print(f"  env file:   {paths.env_file()} ({'present' if paths.env_file().exists() else 'missing'})")
    print(f"  log file:   {paths.log_file()}")
    try:
        config.load(strict=False)
        print(f"  bot token:  {'set' if config.BOT_TOKEN else 'unset'}")
        print(f"  owner id:   {config.OWNER_USER_ID or 'unset'}")
        print(f"  anthropic:  {'set' if config.ANTHROPIC_API_KEY else 'unset'}")
        print(f"  voice:      {'enabled' if config.VOICE_ENABLED else 'disabled'}")
        print(f"  cli path:   {config.CLI_PATH or 'not found on PATH'}")
    except Exception as e:
        print(f"  config:     load failed ({e})")
    print()
    print("Daemon status:")
    try:
        print(d.status())
    except Exception as e:
        print(f"  (could not query daemon: {e})")
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    log = paths.log_file()
    if not log.exists():
        print(f"no log file at {log}", file=sys.stderr)
        return 1
    if args.follow:
        # Cross-platform tail -f. Avoids depending on `tail` being on PATH.
        with log.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            try:
                while True:
                    line = fh.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
    # Non-follow: just print last N lines (-n, default 200).
    n = args.lines or 200
    with log.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    sys.stdout.writelines(lines[-n:])
    return 0


def _cmd_uninstall_daemon(args: argparse.Namespace) -> int:
    from . import daemon as d

    try:
        print(d.uninstall())
    except Exception as e:
        print(f"uninstall failed: {e}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="domlabs-bot",
        description="Use Claude Code from your phone via Telegram.",
    )
    p.add_argument("--version", action="version", version=f"domlabs-bot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="run the 6-step setup wizard")
    sp.set_defaults(func=_cmd_init)

    sp = sub.add_parser("start", help="run the bot (foreground or as a daemon)")
    sp.add_argument(
        "--daemon",
        action="store_true",
        help="install as an OS service and start it in the background",
    )
    sp.set_defaults(func=_cmd_start)

    sp = sub.add_parser("stop", help="stop the running daemon")
    sp.set_defaults(func=_cmd_stop)

    sp = sub.add_parser("status", help="show daemon + config status")
    sp.set_defaults(func=_cmd_status)

    sp = sub.add_parser("logs", help="show the bot's log file")
    sp.add_argument("-f", "--follow", action="store_true", help="tail -f mode")
    sp.add_argument("-n", "--lines", type=int, default=200, help="lines to show (default 200)")
    sp.set_defaults(func=_cmd_logs)

    sp = sub.add_parser("uninstall-daemon", help="remove the OS service definition")
    sp.set_defaults(func=_cmd_uninstall_daemon)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Linux daemon — installed as a systemd user unit.

Unit file lives at ``~/.config/systemd/user/domlabs-bot.service``. To survive
logout, the user should run ``loginctl enable-linger $USER``; we mention
this in the install message but don't run it ourselves (it requires root
on most distros).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from .. import paths

UNIT = "domlabs-bot.service"


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / UNIT


def _exec_args() -> list[str]:
    exe = shutil.which("domlabs-bot")
    if exe:
        return [exe, "start"]
    return [sys.executable, "-m", "domlabs_bot.cli", "start"]


def _unit_text() -> str:
    args = _exec_args()
    exec_start = " ".join(args)
    workdir = paths.root()
    return dedent(
        f"""\
        [Unit]
        Description=domlabs-bot — Telegram bridge to Claude Code
        After=network-online.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        WorkingDirectory={workdir}
        Restart=on-failure
        RestartSec=5
        Environment=PATH=/usr/local/bin:/usr/bin:/bin

        [Install]
        WantedBy=default.target
        """
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def install() -> str:
    paths.ensure_root()
    p = _unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_unit_text(), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    proc = _run(["systemctl", "--user", "enable", "--now", UNIT])
    if proc.returncode != 0:
        raise RuntimeError(
            f"systemctl --user enable --now failed: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return (
        f"Installed systemd user unit '{UNIT}' at {p}.\n"
        "Run `loginctl enable-linger $USER` if you want it to survive logout."
    )


def start() -> str:
    proc = _run(["systemctl", "--user", "start", UNIT])
    if proc.returncode != 0:
        raise RuntimeError(
            f"systemctl --user start failed: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Started '{UNIT}'."


def stop() -> str:
    proc = _run(["systemctl", "--user", "stop", UNIT])
    if proc.returncode != 0:
        raise RuntimeError(
            f"systemctl --user stop failed: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Stopped '{UNIT}'."


def uninstall() -> str:
    _run(["systemctl", "--user", "stop", UNIT])
    _run(["systemctl", "--user", "disable", UNIT])
    p = _unit_path()
    try:
        p.unlink()
    except OSError:
        pass
    _run(["systemctl", "--user", "daemon-reload"])
    return f"Removed systemd user unit '{UNIT}'."


def status() -> str:
    proc = _run(["systemctl", "--user", "status", UNIT, "--no-pager"])
    return proc.stdout.strip() or proc.stderr.strip() or f"unit '{UNIT}' not found"

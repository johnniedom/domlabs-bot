"""macOS daemon — installed as a per-user launchd LaunchAgent.

Plist lives at ``~/Library/LaunchAgents/com.domlabs.bot.plist``. We use
``launchctl`` rather than the SMAppService framework so we don't need a
runtime that calls into Cocoa.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from .. import paths

LABEL = "com.domlabs.bot"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _exec_args() -> list[str]:
    exe = shutil.which("domlabs-bot")
    if exe:
        return [exe, "start"]
    return [sys.executable, "-m", "domlabs_bot.cli", "start"]


def _plist_xml() -> str:
    args = _exec_args()
    program_args = "\n".join(f"        <string>{a}</string>" for a in args)
    log = paths.log_file()
    workdir = paths.root()
    return dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{LABEL}</string>
            <key>ProgramArguments</key>
            <array>
        {program_args}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>WorkingDirectory</key>
            <string>{workdir}</string>
            <key>StandardOutPath</key>
            <string>{log}</string>
            <key>StandardErrorPath</key>
            <string>{log}</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
            </dict>
        </dict>
        </plist>
        """
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def install() -> str:
    paths.ensure_root()
    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_plist_xml(), encoding="utf-8")
    # Try modern bootstrap first (macOS 11+), fall back to legacy load.
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    proc = _run(["launchctl", "bootstrap", f"gui/{uid}", str(p)])
    if proc.returncode != 0:
        # Already loaded? Re-bootstrap after unload.
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        proc = _run(["launchctl", "bootstrap", f"gui/{uid}", str(p)])
    if proc.returncode != 0:
        # Legacy fallback.
        legacy = _run(["launchctl", "load", "-w", str(p)])
        if legacy.returncode != 0:
            raise RuntimeError(
                f"launchctl bootstrap and load both failed: "
                f"{proc.stderr.strip()} / {legacy.stderr.strip()}"
            )
    return f"Installed LaunchAgent at {p} (label={LABEL})."


def start() -> str:
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    proc = _run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"])
    if proc.returncode != 0:
        # Legacy fallback.
        proc = _run(["launchctl", "start", LABEL])
    if proc.returncode != 0:
        raise RuntimeError(
            f"launchctl start failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Started '{LABEL}'."


def stop() -> str:
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    proc = _run(["launchctl", "kill", "TERM", f"gui/{uid}/{LABEL}"])
    if proc.returncode != 0:
        proc = _run(["launchctl", "stop", LABEL])
    if proc.returncode != 0:
        raise RuntimeError(
            f"launchctl stop failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Stopped '{LABEL}'."


def uninstall() -> str:
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    p = _plist_path()
    _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
    _run(["launchctl", "unload", str(p)])
    try:
        p.unlink()
    except OSError:
        pass
    return f"Removed LaunchAgent '{LABEL}'."


def status() -> str:
    proc = _run(["launchctl", "print", f"gui/$(id -u)/{LABEL}"])
    out = proc.stdout.strip() or proc.stderr.strip()
    return out or f"label '{LABEL}' not loaded"

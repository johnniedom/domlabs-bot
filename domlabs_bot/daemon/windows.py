"""Windows daemon — registered as a per-user Scheduled Task.

We use ``schtasks.exe`` rather than pywin32 so we don't need a native dep.
The task triggers at user logon, runs hidden (``/RL LIMITED`` keeps it in
the user session, no console window), and restarts on failure.

The XML we generate is the most portable form — it works on Windows 10+,
which is the practical floor for a Python 3.10+ install.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from .. import paths

TASK_NAME = "domlabs-bot"


def _python_exe() -> str:
    return sys.executable


def _bot_module_args() -> list[str]:
    # Use the console-script entry directly so we don't depend on
    # `python -m domlabs_bot` being on PATH.
    exe = shutil.which("domlabs-bot") or shutil.which("domlabs-bot.exe")
    if exe:
        return [exe, "start"]
    return [_python_exe(), "-m", "domlabs_bot.cli", "start"]


def _xml_for_task() -> str:
    args = _bot_module_args()
    program = args[0]
    arguments = " ".join(f'"{a}"' if " " in a else a for a in args[1:])
    workdir = paths.root()
    user = "%USERNAME%"
    return dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>domlabs-bot — Telegram bridge to Claude Code</Description>
          </RegistrationInfo>
          <Triggers>
            <LogonTrigger>
              <Enabled>true</Enabled>
              <UserId>{user}</UserId>
            </LogonTrigger>
          </Triggers>
          <Principals>
            <Principal id="Author">
              <UserId>{user}</UserId>
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>LeastPrivilege</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>true</AllowHardTerminate>
            <StartWhenAvailable>true</StartWhenAvailable>
            <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
            <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
            <RestartOnFailure>
              <Interval>PT1M</Interval>
              <Count>5</Count>
            </RestartOnFailure>
            <Hidden>true</Hidden>
            <IdleSettings>
              <StopOnIdleEnd>false</StopOnIdleEnd>
              <RestartOnIdle>false</RestartOnIdle>
            </IdleSettings>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{program}</Command>
              <Arguments>{arguments}</Arguments>
              <WorkingDirectory>{workdir}</WorkingDirectory>
            </Exec>
          </Actions>
        </Task>
        """
    )


def _xml_path() -> Path:
    return paths.root() / "domlabs-bot.task.xml"


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def install() -> str:
    paths.ensure_root()
    xml = _xml_for_task()
    xml_path = _xml_path()
    xml_path.write_text(xml, encoding="utf-16")
    # /F overwrites if it already exists.
    proc = _run_schtasks(
        ["/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"]
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /Create failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Registered Task Scheduler task '{TASK_NAME}' (XML at {xml_path})."


def start() -> str:
    proc = _run_schtasks(["/Run", "/TN", TASK_NAME])
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /Run failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Started '{TASK_NAME}'."


def stop() -> str:
    proc = _run_schtasks(["/End", "/TN", TASK_NAME])
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /End failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return f"Stopped '{TASK_NAME}'."


def uninstall() -> str:
    # Stop first; ignore errors if not running.
    _run_schtasks(["/End", "/TN", TASK_NAME])
    proc = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if proc.returncode != 0:
        raise RuntimeError(
            f"schtasks /Delete failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        _xml_path().unlink()
    except OSError:
        pass
    return f"Removed task '{TASK_NAME}'."


def status() -> str:
    proc = _run_schtasks(["/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    if proc.returncode != 0:
        return f"task '{TASK_NAME}' not registered"
    return proc.stdout.strip()

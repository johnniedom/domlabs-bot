"""Cross-platform daemon installer dispatch.

``install()``, ``start()``, ``stop()``, ``uninstall()``, and ``status()``
proxy to the OS-specific module — Windows Task Scheduler, macOS launchd,
or Linux systemd user.

All modules expose the same five functions and return short strings (or
raise on failure) so the CLI can present consistent output.
"""
from __future__ import annotations

import platform
import sys  # noqa: F401  (re-exported via python_executable)


def _impl():
    s = platform.system()
    if s == "Windows":
        from . import windows as impl  # type: ignore
    elif s == "Darwin":
        from . import macos as impl  # type: ignore
    elif s == "Linux":
        from . import linux as impl  # type: ignore
    else:
        raise RuntimeError(f"Unsupported platform: {s}")
    return impl


def install() -> str:
    return _impl().install()


def start() -> str:
    return _impl().start()


def stop() -> str:
    return _impl().stop()


def uninstall() -> str:
    return _impl().uninstall()


def status() -> str:
    return _impl().status()


def python_executable() -> str:
    """Path to the Python that should run the bot.

    pipx puts the bot's venv Python at sys.executable, which is what we want
    the OS service to invoke.
    """
    return sys.executable

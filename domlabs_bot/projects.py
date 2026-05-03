"""Project registry — named cwd presets for /project switching.

Stored as JSON at ``$DOMLABS_BOT_ROOT/projects.json``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)


def _load() -> dict[str, str]:
    p = paths.projects_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.exception("projects.json unreadable: %s", e)
        return {}


def _save(data: dict[str, str]) -> None:
    p = paths.projects_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_projects() -> dict[str, str]:
    return _load()


def get_cwd(name: str) -> str | None:
    return _load().get(name)


def add_project(name: str, cwd: str) -> str:
    path = Path(cwd).expanduser()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Not a directory: {path}")
    data = _load()
    data[name] = str(path.resolve())
    _save(data)
    return data[name]


def remove_project(name: str) -> bool:
    if name == "default":
        raise ValueError("cannot remove 'default' project")
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True

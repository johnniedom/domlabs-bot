"""Template files used by the init wizard.

These are plain Markdown files with ``{{KEY}}`` placeholders. We don't
depend on Jinja — a tiny ``str.replace()`` loop is enough.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path


def render(template_name: str, vars: dict[str, str]) -> str:
    """Load a template from this package and substitute ``{{KEY}}`` markers."""
    src = resources.files(__name__).joinpath(template_name).read_text(encoding="utf-8")
    for key, value in vars.items():
        src = src.replace("{{" + key + "}}", value)
    return src


def write(template_name: str, dest: Path, vars: dict[str, str]) -> Path:
    """Render a template and write it to ``dest`` (parents created)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(template_name, vars), encoding="utf-8")
    return dest

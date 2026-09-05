"""User-scoped directories. Windows-first, but correct on POSIX too."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Shawzify"


def _base_dir() -> Path:
    override = os.environ.get("SHAWZIFY_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return Path(root) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(root) / APP_NAME.lower()


def _ensure(p: Path) -> str:
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def app_dir() -> str:
    return _ensure(_base_dir())


def cache_dir() -> str:
    return _ensure(_base_dir() / "cache")


def model_dir() -> str:
    return _ensure(_base_dir() / "models")


def log_dir() -> str:
    return _ensure(_base_dir() / "logs")


def projects_dir() -> str:
    return _ensure(_base_dir() / "projects")


def redact(path: str | os.PathLike[str] | None) -> str:
    """Replace the user's home directory with ~ so paths can go into a bug report."""
    if path is None:
        return ""
    text = str(path)
    home = str(Path.home())
    if text.lower().startswith(home.lower()):
        return "~" + text[len(home):]
    return text

"""Input validation. Imported files and their metadata are untrusted."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from .errors import UnsafePathError, UnsupportedFormatError

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".aiff", ".aif", ".wma",
}
MIDI_EXTENSIONS = {".mid", ".midi"}
PROJECT_EXTENSIONS = {".shawzify"}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def resolve_input_path(path: str | os.PathLike[str]) -> Path:
    """Resolve a user-supplied input path; reject anything that is not a real file."""
    if path is None or str(path).strip() == "":
        raise UnsafePathError("No file was given.")
    text = str(path)
    if "\x00" in text:
        raise UnsafePathError("That file path contains an invalid character.")
    p = Path(text).expanduser()
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError(
            "SHAWZIFY could not find that file.", technical=str(exc)
        ) from exc
    if not p.is_file():
        raise UnsafePathError("That path is a folder, not a file.")
    return p


def classify_input(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MIDI_EXTENSIONS:
        return "midi"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in PROJECT_EXTENSIONS:
        return "project"
    raise UnsupportedFormatError(
        "SHAWZIFY does not support " + (ext or "files without an extension") + " yet.",
        hint="Supported inputs: WAV, MP3, FLAC, M4A, OGG and MIDI.",
    )


def sanitize_metadata_text(value: object, *, max_length: int = 200) -> str:
    """Make a tag or track name from an untrusted file safe to display and log."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL.sub(" ", text).strip()
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text


def safe_output_path(path: str | os.PathLike[str]) -> Path:
    p = Path(str(path)).expanduser()
    if "\x00" in str(p):
        raise UnsafePathError("That output path contains an invalid character.")
    parent = p.parent
    try:
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UnsafePathError(
            "SHAWZIFY could not write to that folder.", technical=str(exc)
        ) from exc
    return p

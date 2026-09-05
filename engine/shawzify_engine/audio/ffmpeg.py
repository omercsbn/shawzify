"""FFmpeg discovery and safe invocation.

Commands are always built as argument arrays -- never a concatenated shell
string -- so a filename with quotes, semicolons or ``&&`` in it cannot become
a command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common.errors import AudioDecodeError, FFmpegMissingError

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class FFmpegInfo:
    ffmpeg: str | None
    ffprobe: str | None
    version: str | None
    source: str  # "system" | "imageio" | "none"

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "version": self.version,
            "source": self.source,
            "hasFfprobe": self.ffprobe is not None,
        }


_cached: FFmpegInfo | None = None


def _run(args: Sequence[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    """Run a tool with stdin closed.

    ``stdin=DEVNULL`` is not optional: when SHAWZIFY runs as the desktop
    sidecar its own stdin is a pipe, and a child that inherits it can sit
    waiting on input forever instead of exiting.
    """
    return subprocess.run(  # noqa: S603 - argument array, never shell=True
        list(args),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=_CREATE_NO_WINDOW,
    )


def find_ffmpeg(refresh: bool = False) -> FFmpegInfo:
    """Locate ffmpeg: PATH first, then the pip-installed imageio binary."""
    global _cached
    if _cached is not None and not refresh:
        return _cached

    override = os.environ.get("SHAWZIFY_FFMPEG")
    candidates: list[tuple[str, str | None, str]] = []
    if override:
        candidates.append((override, shutil.which("ffprobe"), "override"))
    system = shutil.which("ffmpeg")
    if system:
        candidates.append((system, shutil.which("ffprobe"), "system"))
    try:
        import imageio_ffmpeg

        candidates.append((imageio_ffmpeg.get_ffmpeg_exe(), None, "imageio"))
    except Exception:  # noqa: BLE001 - optional dependency, any failure means "absent"
        pass

    for exe, probe, source in candidates:
        try:
            result = _run([exe, "-version"], timeout=15.0)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        first = result.stdout.decode("utf-8", "replace").splitlines()
        version = first[0].strip() if first else "unknown"
        _cached = FFmpegInfo(exe, probe, version, source)
        return _cached

    _cached = FFmpegInfo(None, None, None, "none")
    return _cached


def probe(path: str | Path) -> dict[str, Any]:
    """Container/stream metadata via ffprobe, or an ffmpeg fallback."""
    info = find_ffmpeg()
    if info.ffprobe:
        result = _run(
            [
                info.ffprobe, "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ]
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                pass
    if not info.available:
        raise FFmpegMissingError()
    # ffmpeg writes its stream summary to stderr; parsing it is crude but works
    # when only the bundled binary (no ffprobe) is present.
    result = _run([info.ffmpeg, "-i", str(path), "-hide_banner"])
    text = result.stderr.decode("utf-8", "replace")
    return {"raw": text, "format": {}, "streams": []}


def decode_to_pcm(
    path: str | Path,
    *,
    sample_rate: int = 44100,
    channels: int = 1,
    start: float | None = None,
    duration: float | None = None,
) -> bytes:
    """Decode any supported container to raw float32 little-endian PCM."""
    info = find_ffmpeg()
    if not info.available:
        raise FFmpegMissingError(
            hint="Install FFmpeg, or run scripts/setup.ps1 which installs a bundled copy."
        )
    args: list[str] = [info.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start is not None:
        args += ["-ss", f"{max(0.0, start):.6f}"]
    args += ["-i", str(path)]
    if duration is not None:
        args += ["-t", f"{max(0.0, duration):.6f}"]
    args += [
        "-map", "a:0",
        "-vn", "-sn", "-dn",
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", str(int(channels)),
        "-ar", str(int(sample_rate)),
        "-",
    ]
    try:
        result = subprocess.run(  # noqa: S603 - argument array, never shell=True
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioDecodeError(cause=exc) from exc
    if result.returncode != 0 or not result.stdout:
        raise AudioDecodeError(
            "That audio file could not be decoded.",
            technical=result.stderr.decode("utf-8", "replace")[-2000:],
        )
    return result.stdout


def encode_wav(
    pcm: bytes,
    path: str | Path,
    *,
    sample_rate: int = 44100,
    channels: int = 1,
) -> Path:
    """Write float32 PCM to a 16-bit WAV (for handing audio to other tools)."""
    info = find_ffmpeg()
    if not info.available:
        raise FFmpegMissingError()
    args = [
        info.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-f", "f32le", "-ar", str(sample_rate), "-ac", str(channels), "-i", "-",
        "-acodec", "pcm_s16le", str(path),
    ]
    result = subprocess.run(  # noqa: S603
        args, input=pcm, capture_output=True, check=False, creationflags=_CREATE_NO_WINDOW
    )
    if result.returncode != 0:
        raise AudioDecodeError(
            "SHAWZIFY could not write that audio file.",
            technical=result.stderr.decode("utf-8", "replace")[-2000:],
        )
    return Path(path)

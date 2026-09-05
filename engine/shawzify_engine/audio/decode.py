"""Audio loading into a predictable internal representation.

Everything downstream sees float32 PCM at a known sample rate. WAV/FLAC/OGG go
through libsndfile (fast, no subprocess); anything else goes through FFmpeg.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..common.errors import AudioDecodeError
from ..common.safety import sanitize_metadata_text
from .ffmpeg import decode_to_pcm, find_ffmpeg, probe

DEFAULT_SAMPLE_RATE = 44100

_SOUNDFILE_EXTENSIONS = {".wav", ".flac", ".ogg", ".aiff", ".aif", ".opus"}


@dataclass
class AudioMetadata:
    path: str
    filename: str
    duration: float
    sample_rate: int
    channels: int
    codec: str | None = None
    bitrate: int | None = None
    title: str | None = None
    artist: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "durationSeconds": round(self.duration, 3),
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "title": self.title,
            "artist": self.artist,
        }


@dataclass
class AudioBuffer:
    """Mono or stereo float32 samples, shape ``(channels, frames)``."""

    samples: np.ndarray
    sample_rate: int
    metadata: AudioMetadata

    @property
    def duration(self) -> float:
        return self.samples.shape[-1] / float(self.sample_rate)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[0])

    def mono(self) -> np.ndarray:
        if self.samples.shape[0] == 1:
            return self.samples[0]
        return self.samples.mean(axis=0)

    def slice_seconds(self, start: float, end: float) -> AudioBuffer:
        a = max(0, int(start * self.sample_rate))
        b = min(self.samples.shape[-1], int(end * self.sample_rate))
        return AudioBuffer(self.samples[:, a:b].copy(), self.sample_rate, self.metadata)


def _probe_metadata(path: Path) -> tuple[str | None, int | None, str | None, str | None]:
    """(codec, bitrate, title, artist) -- best effort, never fatal."""
    try:
        info = probe(path)
    except Exception:  # noqa: BLE001 - metadata is a nicety
        return (None, None, None, None)
    codec = None
    bitrate = None
    title = None
    artist = None
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            codec = stream.get("codec_name")
            if stream.get("bit_rate"):
                try:
                    bitrate = int(stream["bit_rate"])
                except (TypeError, ValueError):
                    pass
            break
    fmt = info.get("format", {})
    if bitrate is None and fmt.get("bit_rate"):
        try:
            bitrate = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            pass
    tags = fmt.get("tags") or {}
    for key, value in tags.items():
        low = key.lower()
        if low == "title":
            title = sanitize_metadata_text(value, max_length=120)
        elif low in ("artist", "album_artist"):
            artist = artist or sanitize_metadata_text(value, max_length=120)
    return (codec, bitrate, title, artist)


def load_audio(
    path: str | Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    mono: bool = True,
    max_seconds: float | None = None,
) -> AudioBuffer:
    """Decode a file to float32 PCM."""
    p = Path(path)
    channels = 1 if mono else 2
    codec, bitrate, title, artist = _probe_metadata(p)

    data: np.ndarray | None = None
    native_rate = sample_rate

    if p.suffix.lower() in _SOUNDFILE_EXTENSIONS:
        try:
            import soundfile as sf

            raw, native_rate = sf.read(str(p), dtype="float32", always_2d=True)
            data = np.ascontiguousarray(raw.T)  # (channels, frames)
            codec = codec or p.suffix.lower().lstrip(".")
        except Exception:  # noqa: BLE001 - fall through to ffmpeg
            data = None

    if data is None:
        pcm = decode_to_pcm(p, sample_rate=sample_rate, channels=channels,
                            duration=max_seconds)
        flat = np.frombuffer(pcm, dtype="<f4")
        if flat.size == 0:
            raise AudioDecodeError("That file contains no audio.")
        frames = flat.size // channels
        data = np.ascontiguousarray(flat[: frames * channels].reshape(frames, channels).T)
        native_rate = sample_rate

    if not np.isfinite(data).all():
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    if mono and data.shape[0] > 1:
        data = data.mean(axis=0, keepdims=True)
    elif not mono and data.shape[0] == 1:
        data = np.repeat(data, 2, axis=0)

    if native_rate != sample_rate:
        data = resample(data, native_rate, sample_rate)

    if max_seconds is not None:
        limit = int(max_seconds * sample_rate)
        data = data[:, :limit]

    duration = data.shape[-1] / float(sample_rate)
    meta = AudioMetadata(
        path=str(p),
        filename=p.name,
        duration=duration,
        sample_rate=sample_rate,
        channels=int(data.shape[0]),
        codec=codec,
        bitrate=bitrate,
        title=title or sanitize_metadata_text(p.stem, max_length=120),
        artist=artist,
    )
    return AudioBuffer(data.astype(np.float32, copy=False), sample_rate, meta)


def resample(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Polyphase resample, falling back to linear interpolation."""
    if source_rate == target_rate:
        return data
    try:
        from scipy.signal import resample_poly

        g = math.gcd(int(source_rate), int(target_rate))
        up = int(target_rate) // g
        down = int(source_rate) // g
        return np.ascontiguousarray(resample_poly(data, up, down, axis=-1).astype(np.float32))
    except Exception:  # noqa: BLE001
        n_out = int(round(data.shape[-1] * target_rate / source_rate))
        x_old = np.linspace(0.0, 1.0, data.shape[-1], endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        out = np.stack([np.interp(x_new, x_old, ch) for ch in data])
        return out.astype(np.float32)


def audio_available() -> bool:
    return find_ffmpeg().available

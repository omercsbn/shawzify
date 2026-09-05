"""Preview rendering.

``PreviewInstrument`` is the seam: the default is a Karplus-Strong plucked
string, which is a decent stand-in for the Shawzin's shamisen-like timbre.
A sampled instrument can be dropped in later without touching any caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..common.safety import safe_output_path
from ..music.events import NoteEvent
from ..music.pitch import midi_to_hz

DEFAULT_SR = 44100


class PreviewInstrument(ABC):
    id = "base"
    name = "Preview instrument"

    @abstractmethod
    def render_note(self, midi: int, seconds: float, velocity: float, sample_rate: int) -> np.ndarray:
        ...


class PluckedStringInstrument(PreviewInstrument):
    """Karplus-Strong: an excited delay line with a lowpass in the feedback path."""

    id = "pluck"
    name = "Plucked string"

    def __init__(self, *, damping: float = 0.4, brightness: float = 0.55) -> None:
        self.damping = damping
        self.brightness = brightness

    def render_note(
        self, midi: int, seconds: float, velocity: float, sample_rate: int
    ) -> np.ndarray:
        freq = midi_to_hz(midi)
        n = max(1, int(seconds * sample_rate))
        delay = max(2, int(round(sample_rate / freq)))

        # Deterministic excitation: a fixed pseudo-random burst shaped by
        # brightness. Seeded per pitch so the same note always sounds identical.
        rng = np.random.default_rng(1000 + int(midi))
        burst = rng.uniform(-1.0, 1.0, delay).astype(np.float32)
        # Lowpass the burst for a rounder attack at low brightness.
        alpha = 0.15 + 0.8 * self.brightness
        for i in range(1, delay):
            burst[i] = alpha * burst[i] + (1.0 - alpha) * burst[i - 1]

        buf = np.zeros(n + delay, dtype=np.float32)
        buf[:delay] = burst
        decay = 1.0 - min(0.5, self.damping * 0.5 / max(1.0, freq / 220.0)) * 0.02
        for i in range(delay, n + delay):
            buf[i] = decay * 0.5 * (buf[i - delay] + buf[i - delay + 1])
        out = buf[:n]

        # Gentle envelope so notes stop rather than click.
        release = min(n, max(1, int(0.06 * sample_rate)))
        env = np.ones(n, dtype=np.float32)
        env[-release:] = np.linspace(1.0, 0.0, release)
        attack = min(n, max(1, int(0.004 * sample_rate)))
        env[:attack] *= np.linspace(0.0, 1.0, attack)
        return out * env * (0.25 + 0.75 * float(np.clip(velocity, 0.0, 1.0)))


def render_preview(
    events: Sequence[NoteEvent],
    *,
    sample_rate: int = DEFAULT_SR,
    instrument: PreviewInstrument | None = None,
    tail_seconds: float = 1.0,
    note_seconds: float | None = None,
) -> np.ndarray:
    """Mix note events into a mono float32 buffer."""
    inst = instrument or PluckedStringInstrument()
    if not events:
        return np.zeros(1, dtype=np.float32)
    end = max(e.end_seconds for e in events) + tail_seconds
    total = max(1, int(end * sample_rate))
    out = np.zeros(total, dtype=np.float32)
    cache: dict[tuple[int, int], np.ndarray] = {}
    for ev in events:
        seconds = note_seconds if note_seconds is not None else max(0.12, ev.duration_seconds)
        key = (ev.pitch_midi, int(seconds * 100))
        rendered = cache.get(key)
        if rendered is None:
            rendered = inst.render_note(ev.pitch_midi, seconds, 1.0, sample_rate)
            cache[key] = rendered
        start = int(ev.start_seconds * sample_rate)
        stop = min(total, start + len(rendered))
        if stop <= start:
            continue
        gain = 0.25 + 0.75 * float(np.clip(ev.velocity, 0.0, 1.0))
        out[start:stop] += rendered[: stop - start] * gain
    peak = float(np.max(np.abs(out)) or 1.0)
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out


def write_preview_wav(
    events: Sequence[NoteEvent],
    path: str | Path,
    *,
    sample_rate: int = DEFAULT_SR,
    instrument: PreviewInstrument | None = None,
) -> Path:
    import soundfile as sf

    out = safe_output_path(path)
    audio = render_preview(events, sample_rate=sample_rate, instrument=instrument)
    sf.write(str(out), audio, sample_rate, subtype="PCM_16")
    return out

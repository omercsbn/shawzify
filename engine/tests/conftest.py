"""Shared fixtures: deterministic musical and audio material.

No copyrighted audio is committed. Every WAV used by the tests is synthesised
here from first principles, so the DSP tests run anywhere.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from shawzify_engine.music.events import NoteEvent
from shawzify_engine.shawzin.instrument import default_instrument

SR = 22050


# -- golden musical fixtures --------------------------------------------


def _seq(pitches, start=0.0, step=0.5, dur=0.45, velocity=0.8, source="fixture"):
    return [
        NoteEvent(p, start + i * step, dur, velocity, 1.0, source)
        for i, p in enumerate(pitches)
    ]


@pytest.fixture
def c_major_scale() -> list[NoteEvent]:
    return _seq([60, 62, 64, 65, 67, 69, 71, 72])


@pytest.fixture
def chromatic_scale() -> list[NoteEvent]:
    return _seq(list(range(60, 73)), step=0.25, dur=0.2)


@pytest.fixture
def twinkle() -> list[NoteEvent]:
    """Twinkle Twinkle Little Star -- public domain, and everyone can hum it."""
    pitches = [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60]
    durations = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0]
    out = []
    t = 0.0
    for p, d in zip(pitches, durations):
        out.append(NoteEvent(p, t, d * 0.9, 0.8, 1.0, "fixture:twinkle"))
        t += d
    return out


@pytest.fixture
def chord_progression() -> list[NoteEvent]:
    """C - F - G - C triads, one per bar at 60 BPM."""
    out = []
    for i, root in enumerate([60, 65, 67, 60]):
        for off in (0, 4, 7):
            out.append(NoteEvent(root + off, i * 1.0, 0.95, 0.8, 1.0, "fixture:chords"))
    return out


@pytest.fixture
def dense_chord() -> list[NoteEvent]:
    """A seven-note stack: far more than three strings can hold."""
    return [
        NoteEvent(p, 0.0, 1.0, 0.8, 1.0, "fixture:dense")
        for p in (48, 55, 60, 64, 67, 70, 74)
    ]


@pytest.fixture
def out_of_range_melody() -> list[NoteEvent]:
    """A real melodic shape spanning C2 to C7, far outside the Shawzin's reach.

    Deliberately not a stack of octaves: the point is to check that folding
    preserves the *contour*, which a run of identical pitch classes would hide.
    """
    return _seq(
        [36, 40, 43, 48, 55, 59, 64, 67, 72, 76, 83, 88, 96, 91, 79, 65, 52, 41],
        step=0.4,
        dur=0.35,
    )


@pytest.fixture
def fast_repeats() -> list[NoteEvent]:
    """Sixteen repeats of one pitch at 16 notes/second."""
    return _seq([64] * 16, step=1.0 / 16.0, dur=0.05)


@pytest.fixture
def instrument():
    return default_instrument()


# -- synthetic audio fixtures -------------------------------------------


def _adsr(n: int, sr: int, attack=0.01, release=0.08) -> np.ndarray:
    env = np.ones(n, dtype=np.float32)
    a = min(n, int(attack * sr))
    r = min(n - a, int(release * sr))
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a)
    if r > 0:
        env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def synth_tone(
    freq: float, seconds: float, sr: int = SR, *, harmonics: int = 4, amp: float = 0.5
) -> np.ndarray:
    n = max(1, int(seconds * sr))
    t = np.arange(n, dtype=np.float32) / sr
    wave = np.zeros(n, dtype=np.float32)
    for h in range(1, harmonics + 1):
        wave += (amp / h) * np.sin(2.0 * math.pi * freq * h * t).astype(np.float32)
    return wave * _adsr(n, sr)


def synth_sequence(
    midi_pitches, seconds_each: float = 0.5, sr: int = SR, *, gap: float = 0.0
) -> np.ndarray:
    from shawzify_engine.music.pitch import midi_to_hz

    parts = []
    for p in midi_pitches:
        parts.append(synth_tone(midi_to_hz(p), seconds_each, sr))
        if gap > 0:
            parts.append(np.zeros(int(gap * sr), dtype=np.float32))
    return np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)


def synth_polyphonic(
    chords, seconds_each: float = 0.8, sr: int = SR
) -> np.ndarray:
    from shawzify_engine.music.pitch import midi_to_hz

    parts = []
    for chord in chords:
        n = int(seconds_each * sr)
        acc = np.zeros(n, dtype=np.float32)
        for p in chord:
            acc += synth_tone(midi_to_hz(p), seconds_each, sr, amp=0.35)[:n]
        parts.append(acc)
    return np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)


@pytest.fixture
def sine_440() -> np.ndarray:
    t = np.arange(int(SR * 1.0), dtype=np.float32) / SR
    return (0.6 * np.sin(2 * math.pi * 440.0 * t)).astype(np.float32)


@pytest.fixture
def arpeggio_audio() -> np.ndarray:
    return synth_sequence([60, 64, 67, 72], 0.45)


@pytest.fixture
def melody_audio() -> np.ndarray:
    return synth_sequence([60, 62, 64, 65, 67, 65, 64, 62, 60], 0.4)


@pytest.fixture
def two_note_audio() -> np.ndarray:
    return synth_polyphonic([[60, 67]], 1.2)


@pytest.fixture
def wav_file(tmp_path: Path):
    """Factory writing a numpy array to a real WAV on disk."""
    import soundfile as sf

    counter = {"n": 0}

    def _write(samples: np.ndarray, sr: int = SR, name: str | None = None) -> Path:
        counter["n"] += 1
        path = tmp_path / (name or ("fixture" + str(counter["n"]) + ".wav"))
        sf.write(str(path), np.asarray(samples, dtype=np.float32), sr, subtype="PCM_16")
        return path

    return _write


@pytest.fixture
def midi_file(tmp_path: Path):
    """Factory writing NoteEvents to a real MIDI file."""
    from shawzify_engine.midi.writer import write_midi

    counter = {"n": 0}

    def _write(events, bpm: float = 120.0, name: str | None = None) -> Path:
        counter["n"] += 1
        path = tmp_path / (name or ("fixture" + str(counter["n"]) + ".mid"))
        return write_midi(events, path, bpm=bpm)

    return _write


@pytest.fixture(autouse=True)
def isolated_app_home(tmp_path, monkeypatch):
    """Keep tests out of the user's real cache and log directories."""
    monkeypatch.setenv("SHAWZIFY_HOME", str(tmp_path / "app"))
    yield

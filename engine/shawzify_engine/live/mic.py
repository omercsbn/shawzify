"""Microphone / live-input mode: hum a melody, the Shawzin plays it.

Deliberately monophonic and cheap: a low-latency autocorrelation tracker with
hysteresis, never Demucs or a neural model. The same note-decision core is
reused by MIDI keyboard input, which only replaces the pitch source.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..music.pitch import hz_to_midi
from ..shawzin.instrument import ShawzinInstrument, ShawzinNote, default_instrument
from ..shawzin.songcode import ShawzinEvent


@dataclass
class LiveInputSettings:
    minimum_confidence: float = 0.45
    #: Exponential smoothing of the pitch contour, 0 = none, 1 = frozen.
    pitch_smoothing: float = 0.55
    #: How far the smoothed pitch must move before a new note is triggered.
    note_change_threshold: float = 0.75
    #: Consecutive confident frames required before a note starts (debounce).
    onset_frames: int = 2
    #: Consecutive unvoiced frames before the note is considered released.
    release_frames: int = 3
    octave_lock: bool = False
    scale_lock: bool = True
    transpose: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimumConfidence": self.minimum_confidence,
            "pitchSmoothing": self.pitch_smoothing,
            "noteChangeThreshold": self.note_change_threshold,
            "onsetFrames": self.onset_frames,
            "releaseFrames": self.release_frames,
            "octaveLock": self.octave_lock,
            "scaleLock": self.scale_lock,
            "transpose": self.transpose,
        }


@dataclass
class LiveNote:
    midi: int
    position: str
    fret: str
    string: str
    name: str
    confidence: float
    frame: int

    def to_event(self, tick: int) -> ShawzinEvent:
        return ShawzinEvent(tick=tick, fret=self.fret, string=self.string)

    def to_dict(self) -> dict[str, Any]:
        return {
            "midi": self.midi,
            "position": self.position,
            "fret": self.fret,
            "string": self.string,
            "name": self.name,
            "confidence": round(self.confidence, 3),
            "frame": self.frame,
        }


def nearest_playable(
    midi: float,
    instrument: ShawzinInstrument,
    scale_id: str,
    *,
    octave_lock: bool = False,
    snap_out_of_scale: bool = True,
) -> ShawzinNote | None:
    """Best Shawzin position for a (possibly fractional) MIDI pitch.

    The pitch class is preserved whenever the scale contains it, even if a
    chromatic neighbour is numerically closer: humming a C above the Shawzin's
    range should play a C an octave down, not the B at the top of the range.

    ``octave_lock`` pins the output to the scale's lowest available octave, so
    a singer wandering between octaves still drives one register.
    ``snap_out_of_scale`` decides what happens to a pitch the scale cannot
    play: snap it to the nearest note, or emit nothing.
    """
    scale = instrument.scale(scale_id)
    if not scale.notes:
        return None
    target_pc = int(round(midi)) % 12
    same_pitch_class = [n for n in scale.notes if n.midi % 12 == target_pc]
    if same_pitch_class:
        if octave_lock:
            return min(same_pitch_class, key=lambda n: n.midi)
        return min(same_pitch_class, key=lambda n: (abs(n.midi - midi), n.midi))
    if not snap_out_of_scale:
        return None
    return min(scale.notes, key=lambda n: (abs(n.midi - midi), n.midi))


class LivePitchMapper:
    """Turns a stream of (f0, confidence) frames into Shawzin note triggers.

    Stateful and frame-by-frame so it can be driven from an audio callback,
    a file, or a test -- there is no audio device dependency in here.
    """

    def __init__(
        self,
        instrument: ShawzinInstrument | None = None,
        *,
        scale_id: str = "chrom",
        settings: LiveInputSettings | None = None,
    ) -> None:
        self.instrument = instrument or default_instrument()
        self.scale_id = scale_id
        self.settings = settings or LiveInputSettings()
        self.reset()

    def reset(self) -> None:
        self._smoothed: float | None = None
        self._current: LiveNote | None = None
        self._confident_run = 0
        self._silent_run = 0
        self._frame = 0

    @property
    def current(self) -> LiveNote | None:
        return self._current

    def push(self, f0_hz: float, confidence: float) -> LiveNote | None:
        """Feed one analysis frame. Returns a note when one should be struck."""
        s = self.settings
        self._frame += 1
        if f0_hz <= 0 or confidence < s.minimum_confidence:
            self._silent_run += 1
            self._confident_run = 0
            if self._silent_run >= s.release_frames:
                self._current = None
                self._smoothed = None
            return None

        self._silent_run = 0
        self._confident_run += 1
        midi = hz_to_midi(f0_hz) + s.transpose
        if self._smoothed is None:
            self._smoothed = midi
        else:
            a = max(0.0, min(0.99, s.pitch_smoothing))
            self._smoothed = a * self._smoothed + (1.0 - a) * midi

        if self._confident_run < s.onset_frames:
            return None

        target = nearest_playable(
            self._smoothed,
            self.instrument,
            self.scale_id,
            octave_lock=s.octave_lock,
            snap_out_of_scale=s.scale_lock,
        )
        if target is None:
            return None

        if self._current is not None:
            if target.midi == self._current.midi:
                return None
            if abs(self._smoothed - self._current.midi) < s.note_change_threshold:
                return None

        note = LiveNote(
            midi=target.midi,
            position=target.position,
            fret=target.fret,
            string=target.string,
            name=target.name,
            confidence=float(confidence),
            frame=self._frame,
        )
        self._current = note
        return note


def map_frames(
    frames: Iterable[tuple[float, float]],
    instrument: ShawzinInstrument | None = None,
    *,
    scale_id: str = "chrom",
    settings: LiveInputSettings | None = None,
) -> list[LiveNote]:
    """Convenience: run a whole (f0, confidence) stream through the mapper."""
    mapper = LivePitchMapper(instrument, scale_id=scale_id, settings=settings)
    out: list[LiveNote] = []
    for f0, conf in frames:
        note = mapper.push(f0, conf)
        if note is not None:
            out.append(note)
    return out


def frames_from_audio(
    samples: np.ndarray, sample_rate: int, *, hop: int = 256
) -> list[tuple[float, float]]:
    """Analyse a buffer into (f0, confidence) frames using the live tracker."""
    from ..transcription.pyin_transcriber import _autocorrelation_f0

    if samples.ndim > 1:
        samples = samples.mean(axis=0)
    f0, conf = _autocorrelation_f0(
        np.asarray(samples, dtype=np.float32), sample_rate, hop, 65.0, 1200.0
    )
    return list(zip(f0.tolist(), conf.tolist()))


@dataclass
class MidiKeyboardMapper:
    """MIDI note numbers -> Shawzin positions. Shares the live note policy."""

    instrument: ShawzinInstrument = field(default_factory=default_instrument)
    scale_id: str = "chrom"
    settings: LiveInputSettings = field(default_factory=LiveInputSettings)

    def map_note(self, midi: int, velocity: int = 100) -> LiveNote | None:
        if velocity <= 0:
            return None
        target = nearest_playable(
            midi + self.settings.transpose,
            self.instrument,
            self.scale_id,
            octave_lock=self.settings.octave_lock,
            snap_out_of_scale=self.settings.scale_lock,
        )
        if target is None:
            return None
        return LiveNote(
            midi=target.midi,
            position=target.position,
            fret=target.fret,
            string=target.string,
            name=target.name,
            confidence=1.0,
            frame=0,
        )


def microphone_available() -> tuple[bool, str]:
    """Whether a capture device can be opened right now."""
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001
        return (False, "The sounddevice package is not installed.")
    try:
        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if not inputs:
            return (False, "No microphone or input device was found.")
        return (True, str(inputs[0].get("name", "input device")))
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc))


def stream_microphone(
    on_note: Callable[[LiveNote], None],
    *,
    instrument: ShawzinInstrument | None = None,
    scale_id: str = "chrom",
    settings: LiveInputSettings | None = None,
    sample_rate: int = 22050,
    block: int = 1024,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Capture from the default input and emit Shawzin notes until stopped.

    Requires the optional ``sounddevice`` package; callers should check
    :func:`microphone_available` first and disable the feature in the UI when
    it returns False rather than showing a button that errors.
    """
    ok, message = microphone_available()
    if not ok:
        from ..common.errors import ShawzifyError

        raise ShawzifyError(
            "Microphone mode is unavailable: " + message,
            hint="Install the optional 'sounddevice' package to enable it.",
        )
    import sounddevice as sd

    from ..transcription.pyin_transcriber import _autocorrelation_f0

    mapper = LivePitchMapper(instrument, scale_id=scale_id, settings=settings)
    with sd.InputStream(samplerate=sample_rate, channels=1, blocksize=block) as stream:
        while should_stop is None or not should_stop():
            data, _overflow = stream.read(block)
            mono = np.asarray(data, dtype=np.float32).reshape(-1)
            f0, conf = _autocorrelation_f0(mono, sample_rate, block, 65.0, 1200.0)
            for hz, c in zip(f0.tolist(), conf.tolist()):
                note = mapper.push(hz, c)
                if note is not None:
                    on_note(note)

"""Monophonic pitch tracking (pYIN, with an autocorrelation fallback).

Used for two things: transcribing a clearly monophonic source such as an
isolated vocal, and driving the live microphone mode, where latency rules out
anything heavier.
"""

from __future__ import annotations

import numpy as np

from ..music.events import NoteEvent, clamp_durations
from ..music.pitch import hz_to_midi
from .base import ProgressFn, Transcriber, TranscriptionResult


def _autocorrelation_f0(
    samples: np.ndarray, sr: int, hop: int, fmin: float, fmax: float
) -> tuple[np.ndarray, np.ndarray]:
    """Frame-wise f0 and voicing confidence without librosa."""
    frame_length = int(sr / fmin * 2)
    frame_length = max(frame_length, 1024)
    frames = 1 + max(0, (len(samples) - frame_length) // hop)
    f0 = np.zeros(max(1, frames), dtype=np.float32)
    conf = np.zeros(max(1, frames), dtype=np.float32)
    min_lag = max(2, int(sr / fmax))
    max_lag = min(frame_length - 1, int(sr / fmin))
    if max_lag <= min_lag:
        return (f0, conf)
    window = np.hanning(frame_length).astype(np.float32)
    for t in range(max(1, frames)):
        chunk = samples[t * hop : t * hop + frame_length]
        if len(chunk) < frame_length:
            chunk = np.pad(chunk, (0, frame_length - len(chunk)))
        chunk = chunk * window
        energy = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        if energy < 1e-4:
            continue
        chunk = chunk - chunk.mean()
        corr = np.correlate(chunk, chunk, mode="full")[frame_length - 1 :]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        window_corr = corr[min_lag : max_lag + 1]
        lag = int(np.argmax(window_corr)) + min_lag
        strength = float(window_corr.max())
        if strength < 0.3:
            continue
        # Parabolic interpolation for sub-sample lag accuracy.
        if min_lag < lag < max_lag:
            y0, y1, y2 = corr[lag - 1], corr[lag], corr[lag + 1]
            denom = y0 - 2 * y1 + y2
            if abs(denom) > 1e-9:
                lag = lag + 0.5 * (y0 - y2) / denom
        f0[t] = sr / float(lag)
        conf[t] = strength
    return (f0, conf)


def track_f0(
    samples: np.ndarray,
    sr: int,
    *,
    hop: int = 256,
    fmin: float = 65.0,
    fmax: float = 1200.0,
) -> tuple[np.ndarray, np.ndarray, float]:
    """``(f0_hz, confidence, frame_seconds)``. Zero f0 means unvoiced."""
    try:
        import librosa

        f0, voiced, prob = librosa.pyin(
            y=samples, sr=sr, fmin=fmin, fmax=fmax, hop_length=hop, fill_na=0.0
        )
        f0 = np.nan_to_num(np.asarray(f0, dtype=np.float32))
        conf = np.nan_to_num(np.asarray(prob, dtype=np.float32))
        conf = np.where(np.asarray(voiced, dtype=bool), conf, 0.0)
        return (f0, conf.astype(np.float32), hop / float(sr))
    except Exception:  # noqa: BLE001
        f0, conf = _autocorrelation_f0(samples, sr, hop, fmin, fmax)
        return (f0, conf, hop / float(sr))


def segment_notes(
    f0: np.ndarray,
    confidence: np.ndarray,
    frame_seconds: float,
    *,
    min_confidence: float = 0.35,
    min_duration: float = 0.06,
    change_semitones: float = 0.6,
    source: str = "audio:pyin",
) -> list[NoteEvent]:
    """Turn a frame-wise f0 contour into discrete notes with hysteresis."""
    events: list[NoteEvent] = []
    current_pitch: float | None = None
    start_frame = 0
    values: list[float] = []
    confs: list[float] = []

    def flush(end_frame: int) -> None:
        nonlocal current_pitch, values, confs
        if current_pitch is None or not values:
            current_pitch = None
            values = []
            confs = []
            return
        duration = (end_frame - start_frame) * frame_seconds
        if duration >= min_duration:
            midi = int(round(float(np.median(values))))
            mean_conf = float(np.mean(confs))
            events.append(
                NoteEvent(
                    pitch_midi=midi,
                    start_seconds=start_frame * frame_seconds,
                    duration_seconds=duration,
                    velocity=float(min(1.0, 0.4 + mean_conf * 0.6)),
                    confidence=mean_conf,
                    source=source,
                )
            )
        current_pitch = None
        values = []
        confs = []

    for t in range(len(f0)):
        hz = float(f0[t])
        c = float(confidence[t])
        if hz <= 0 or c < min_confidence:
            flush(t)
            continue
        midi = hz_to_midi(hz)
        if current_pitch is None:
            current_pitch = midi
            start_frame = t
            values = [midi]
            confs = [c]
        elif abs(midi - float(np.median(values))) > change_semitones:
            flush(t)
            current_pitch = midi
            start_frame = t
            values = [midi]
            confs = [c]
        else:
            values.append(midi)
            confs.append(c)
    flush(len(f0))
    return clamp_durations(events)


class PyinTranscriber(Transcriber):
    id = "pyin"
    name = "Monophonic pitch tracker (pYIN)"
    polyphonic = False

    def __init__(self, *, hop: int = 256) -> None:
        self.hop = hop

    def available(self) -> bool:
        return True

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        min_confidence: float = 0.35,
    ) -> TranscriptionResult:
        if samples.ndim > 1:
            samples = samples.mean(axis=0)
        samples = np.asarray(samples, dtype=np.float32)
        if samples.size == 0:
            return TranscriptionResult([], self.id, False, {"reason": "empty audio"})
        peak = float(np.max(np.abs(samples)) or 1.0)
        samples = samples / peak
        if progress:
            progress(0.2, "Tracking pitch")
        f0, conf, frame_seconds = track_f0(samples, sample_rate, hop=self.hop)
        if progress:
            progress(0.8, "Segmenting notes")
        events = segment_notes(f0, conf, frame_seconds, min_confidence=min_confidence)
        if progress:
            progress(1.0, "Transcribed " + str(len(events)) + " notes")
        voiced = float(np.mean(conf > min_confidence)) if conf.size else 0.0
        return TranscriptionResult(
            events,
            self.id,
            False,
            {"frameSeconds": round(frame_seconds, 5), "voicedFraction": round(voiced, 3)},
        )

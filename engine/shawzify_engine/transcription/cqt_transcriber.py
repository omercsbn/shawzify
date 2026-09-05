"""Deterministic multi-pitch transcription from a constant-Q spectrogram.

This is the always-available backend: no model download, no torch, works on any
machine that can run numpy. The approach is classic multi-F0 estimation:

1. constant-Q transform at 3 bins per semitone (or a log-frequency STFT
   fallback when librosa is absent);
2. per-frame spectral whitening so a quiet passage is judged on its own terms;
3. harmonic summation -- each pitch accumulates energy from its first four
   partials, which lifts true fundamentals above their own overtones;
4. iterative cancellation of the strongest fundamental's harmonic series, so an
   octave above a strong bass note is not reported spuriously;
5. hysteresis note tracking (high threshold to start a note, lower to sustain)
   with a minimum duration.

Accuracy is well short of a trained model on dense mixes, which is why
Basic Pitch is preferred when installed -- but it is a genuine transcription,
and on monophonic or lightly polyphonic material it is good.
"""

from __future__ import annotations

import numpy as np

from ..music.events import NoteEvent, clamp_durations, merge_overlapping_same_pitch
from .base import ProgressFn, Transcriber, TranscriptionResult

MIN_MIDI = 24   # C1
MAX_MIDI = 96   # C7
BINS_PER_SEMITONE = 3
HARMONIC_WEIGHTS = (1.0, 0.55, 0.35, 0.22, 0.16)


def _cqt_librosa(samples: np.ndarray, sr: int, hop: int) -> tuple[np.ndarray, float] | None:
    try:
        import librosa
    except Exception:  # noqa: BLE001
        return None
    n_bins = (MAX_MIDI - MIN_MIDI) * BINS_PER_SEMITONE
    fmin = 440.0 * (2.0 ** ((MIN_MIDI - 69) / 12.0))
    try:
        c = np.abs(
            librosa.cqt(
                y=samples,
                sr=sr,
                hop_length=hop,
                fmin=fmin,
                n_bins=n_bins,
                bins_per_octave=12 * BINS_PER_SEMITONE,
            )
        )
    except Exception:  # noqa: BLE001
        return None
    return (c.astype(np.float32), hop / float(sr))


def _log_spectrogram(samples: np.ndarray, sr: int, hop: int) -> tuple[np.ndarray, float]:
    """Log-frequency magnitude spectrogram, used when librosa is unavailable."""
    n_fft = 8192
    window = np.hanning(n_fft).astype(np.float32)
    n_bins = (MAX_MIDI - MIN_MIDI) * BINS_PER_SEMITONE
    centres = MIN_MIDI + np.arange(n_bins) / float(BINS_PER_SEMITONE)
    centre_hz = 440.0 * (2.0 ** ((centres - 69) / 12.0))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    # Triangular filterbank, one filter per pitch bin.
    edges = 440.0 * (2.0 ** ((centres - 69 - 0.5 / BINS_PER_SEMITONE) / 12.0))
    upper = 440.0 * (2.0 ** ((centres - 69 + 0.5 / BINS_PER_SEMITONE) / 12.0))
    bank = np.zeros((n_bins, len(freqs)), dtype=np.float32)
    for i in range(n_bins):
        lo, mid, hi = edges[i], centre_hz[i], upper[i]
        left = (freqs >= lo) & (freqs <= mid)
        right = (freqs > mid) & (freqs <= hi)
        if mid > lo:
            bank[i, left] = (freqs[left] - lo) / (mid - lo)
        if hi > mid:
            bank[i, right] = (hi - freqs[right]) / (hi - mid)
        s = bank[i].sum()
        if s > 0:
            bank[i] /= s

    frames = 1 + max(0, (len(samples) - n_fft) // hop)
    out = np.zeros((n_bins, max(1, frames)), dtype=np.float32)
    for t in range(max(1, frames)):
        chunk = samples[t * hop : t * hop + n_fft]
        if len(chunk) < n_fft:
            chunk = np.pad(chunk, (0, n_fft - len(chunk)))
        spec = np.abs(np.fft.rfft(chunk * window))
        out[:, t] = bank @ spec
    return (out, hop / float(sr))


def _whiten(spec: np.ndarray) -> np.ndarray:
    """Per-frame normalisation plus a local spectral background subtraction."""
    out = np.log1p(spec * 50.0)
    # Subtract a wide moving average over frequency: removes broadband noise and
    # the slow spectral envelope, keeping peaks.
    k = BINS_PER_SEMITONE * 9
    if k >= 3 and out.shape[0] > k:
        kernel = np.ones(k, dtype=np.float32) / k
        background = np.apply_along_axis(
            lambda col: np.convolve(col, kernel, mode="same"), 0, out
        )
        out = out - background
    out = np.maximum(out, 0.0)
    peak = out.max(axis=0, keepdims=True)
    return out / np.maximum(peak, 1e-6)


#: Semitone offsets of the first partials above a fundamental, with the weight
#: each contributes to that fundamental's salience.
_HARMONIC_SHIFTS = tuple(
    (int(round(12.0 * np.log2(h))), w) for h, w in enumerate(HARMONIC_WEIGHTS, start=1)
)


def _collapse(spec: np.ndarray) -> np.ndarray:
    """Collapse the 3 bins per semitone by taking the max (tolerates detuning)."""
    n_semitones = MAX_MIDI - MIN_MIDI
    return spec.reshape(n_semitones, BINS_PER_SEMITONE, spec.shape[1]).max(axis=1)


def _harmonic_sum(per_semitone: np.ndarray) -> np.ndarray:
    """Sum each pitch's partials into a per-semitone salience map."""
    n_semitones = per_semitone.shape[0]
    salience = np.zeros_like(per_semitone)
    for shift, w in _HARMONIC_SHIFTS:
        if shift == 0:
            salience += w * per_semitone
        elif shift < n_semitones:
            salience[: n_semitones - shift] += w * per_semitone[shift:]
    return salience


def _iterative_f0(
    per_semitone: np.ndarray, *, max_polyphony: int, floor_ratio: float = 0.22
) -> np.ndarray:
    """Klapuri-style iterative estimation and cancellation.

    Each round takes the strongest fundamental in every frame, records it, and
    subtracts its harmonic series from the residual spectrum. Without this a
    loud low note produces phantom notes an octave and a twelfth above it --
    which is exactly the failure mode of a plain harmonic sum.
    """
    n_semitones, frames = per_semitone.shape
    residual = per_semitone.copy()
    detected = np.zeros_like(per_semitone)
    frame_idx = np.arange(frames)

    initial = _harmonic_sum(residual)
    floor = initial.max(axis=0) * floor_ratio

    for _ in range(max(1, max_polyphony)):
        salience = _harmonic_sum(residual)
        peaks = salience.argmax(axis=0)
        strength = salience[peaks, frame_idx]
        active = strength > floor
        if not np.any(active):
            break
        detected[peaks[active], frame_idx[active]] = np.maximum(
            detected[peaks[active], frame_idx[active]], strength[active]
        )
        # Subtract the detected fundamental's harmonic series from the residual.
        base = residual[peaks, frame_idx]
        for shift, w in _HARMONIC_SHIFTS:
            q = peaks + shift
            inside = active & (q < n_semitones)
            if not np.any(inside):
                continue
            qi = q[inside]
            ti = frame_idx[inside]
            residual[qi, ti] = np.maximum(
                0.0, residual[qi, ti] - w * base[inside] * 1.05
            )
    return detected


def _suppress_non_peaks(salience: np.ndarray) -> np.ndarray:
    """Zero anything that is not a local maximum across pitch.

    A real fundamental is a peak; energy smeared across neighbouring semitones
    is filter leakage, not a second note.
    """
    out = salience.copy()
    up = np.zeros_like(salience)
    down = np.zeros_like(salience)
    up[:-1] = salience[1:]
    down[1:] = salience[:-1]
    out[(salience < up) | (salience < down)] = 0.0
    return out


def _track_notes(
    salience: np.ndarray,
    frame_seconds: float,
    *,
    onset_threshold: float,
    sustain_threshold: float,
    min_frames: int,
    max_polyphony: int,
) -> list[tuple[int, float, float, float]]:
    """Hysteresis tracking -> ``(midi, start, end, strength)`` tuples."""
    n_semitones, frames = salience.shape
    # Keep only the strongest ``max_polyphony`` pitches per frame.
    mask = np.zeros_like(salience, dtype=bool)
    if max_polyphony >= n_semitones:
        mask[:] = True
    else:
        top = np.argpartition(-salience, max_polyphony - 1, axis=0)[:max_polyphony]
        for t in range(frames):
            mask[top[:, t], t] = True

    notes: list[tuple[int, float, float, float]] = []
    for p in range(n_semitones):
        row = salience[p]
        active = False
        start = 0
        acc = 0.0
        for t in range(frames):
            value = row[t] if mask[p, t] else row[t] * 0.5
            if not active:
                if value >= onset_threshold:
                    active = True
                    start = t
                    acc = value
            else:
                if value >= sustain_threshold:
                    acc += value
                else:
                    length = t - start
                    if length >= min_frames:
                        notes.append(
                            (
                                MIN_MIDI + p,
                                start * frame_seconds,
                                t * frame_seconds,
                                acc / length,
                            )
                        )
                    active = False
        if active:
            length = frames - start
            if length >= min_frames:
                notes.append(
                    (MIN_MIDI + p, start * frame_seconds, frames * frame_seconds, acc / length)
                )
    return notes


class CqtTranscriber(Transcriber):
    id = "cqt"
    name = "Built-in multi-pitch (CQT)"
    polyphonic = True

    def __init__(self, *, hop: int = 512, max_polyphony: int = 6) -> None:
        self.hop = hop
        self.max_polyphony = max_polyphony

    def available(self) -> bool:
        return True

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        min_confidence: float = 0.3,
    ) -> TranscriptionResult:
        if samples.ndim > 1:
            samples = samples.mean(axis=0)
        samples = np.asarray(samples, dtype=np.float32)
        if samples.size == 0:
            return TranscriptionResult([], self.id, True, {"reason": "empty audio"})

        peak = float(np.max(np.abs(samples)) or 1.0)
        samples = samples / peak

        if progress:
            progress(0.1, "Computing spectrogram")
        result = _cqt_librosa(samples, sample_rate, self.hop)
        backend_detail = "librosa-cqt"
        if result is None:
            result = _log_spectrogram(samples, sample_rate, self.hop)
            backend_detail = "numpy-logspec"
        spec, frame_seconds = result

        if progress:
            progress(0.45, "Estimating pitches")
        whitened = _whiten(spec)
        per_semitone = _collapse(whitened)
        salience = _iterative_f0(per_semitone, max_polyphony=self.max_polyphony)
        salience = _suppress_non_peaks(salience)

        # Smooth over time so a single noisy frame does not break a held note.
        if salience.shape[1] >= 3:
            kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
            salience = np.apply_along_axis(
                lambda row: np.convolve(row, kernel, mode="same"), 1, salience
            )

        top = float(salience.max() or 1.0)
        salience = salience / top

        if progress:
            progress(0.75, "Tracking notes")
        onset_threshold = max(0.16, min_confidence * 0.5)
        raw = _track_notes(
            salience,
            frame_seconds,
            onset_threshold=onset_threshold,
            sustain_threshold=onset_threshold * 0.55,
            min_frames=max(2, int(round(0.055 / frame_seconds))),
            max_polyphony=self.max_polyphony,
        )

        events: list[NoteEvent] = []
        for midi, start, end, strength in raw:
            confidence = float(min(1.0, strength / max(onset_threshold, 1e-6) * 0.5))
            if confidence < min_confidence:
                continue
            events.append(
                NoteEvent(
                    pitch_midi=int(midi),
                    start_seconds=float(start),
                    duration_seconds=float(max(0.05, end - start)),
                    velocity=float(min(1.0, 0.35 + strength * 1.4)),
                    confidence=confidence,
                    source="audio:cqt",
                )
            )
        events = clamp_durations(merge_overlapping_same_pitch(events, gap=0.04))
        if progress:
            progress(1.0, "Transcribed " + str(len(events)) + " notes")
        return TranscriptionResult(
            events,
            self.id,
            True,
            {
                "spectrogram": backend_detail,
                "frameSeconds": round(frame_seconds, 5),
                "maxPolyphony": self.max_polyphony,
                "onsetThreshold": round(onset_threshold, 3),
            },
        )

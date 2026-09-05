"""Track analysis: tempo, key, energy, density, register.

Every estimate ships with a confidence, because tempo and key detection are
genuinely ambiguous on real music and the UI should say so rather than assert.
Uses librosa when installed; falls back to a self-contained onset-autocorrelation
tempo estimator and a chroma-from-STFT key estimator so analysis never simply
becomes unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..music.key import MAJOR_PROFILE, MINOR_PROFILE, _correlate
from ..music.pitch import pitch_class_name


def librosa_available() -> bool:
    try:
        import librosa  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class TrackAnalysis:
    duration: float
    tempo_bpm: float
    tempo_confidence: float
    key: str
    mode: str
    key_confidence: float
    time_signature_estimate: str
    energy: float
    onset_density: float
    pitch_range: tuple[int, int]
    polyphony_estimate: float
    tonic_pitch_class: int
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "durationSeconds": round(self.duration, 3),
            "tempoBpm": round(self.tempo_bpm, 2),
            "tempoConfidence": round(self.tempo_confidence, 3),
            "key": self.key,
            "mode": self.mode,
            "keyConfidence": round(self.key_confidence, 3),
            "timeSignatureEstimate": self.time_signature_estimate,
            "energy": round(self.energy, 4),
            "onsetDensity": round(self.onset_density, 3),
            "pitchRange": list(self.pitch_range),
            "polyphonyEstimate": round(self.polyphony_estimate, 2),
            "tonicPitchClass": self.tonic_pitch_class,
            "backend": self.backend,
        }


def _onset_envelope(samples: np.ndarray, sample_rate: int, hop: int = 512) -> np.ndarray:
    """Spectral-flux onset strength, without librosa."""
    n_fft = 2048
    window = np.hanning(n_fft).astype(np.float32)
    frames = 1 + max(0, (len(samples) - n_fft) // hop)
    if frames < 2:
        return np.zeros(1, dtype=np.float32)
    prev = None
    flux = np.zeros(frames, dtype=np.float32)
    for i in range(frames):
        chunk = samples[i * hop : i * hop + n_fft]
        if len(chunk) < n_fft:
            chunk = np.pad(chunk, (0, n_fft - len(chunk)))
        spec = np.abs(np.fft.rfft(chunk * window))
        spec = np.log1p(spec)
        if prev is not None:
            diff = spec - prev
            flux[i] = float(np.sum(diff[diff > 0]))
        prev = spec
    if flux.max() > 0:
        flux = flux / flux.max()
    return flux


def _tempo_from_envelope(env: np.ndarray, sample_rate: int, hop: int) -> tuple[float, float]:
    """Autocorrelate the onset envelope; peak lag -> BPM, sharpness -> confidence."""
    if env.size < 8:
        return (120.0, 0.0)
    x = env - env.mean()
    corr = np.correlate(x, x, mode="full")[len(x) - 1 :]
    if corr[0] <= 0:
        return (120.0, 0.0)
    corr = corr / corr[0]
    frame_rate = sample_rate / hop
    min_lag = max(1, int(frame_rate * 60.0 / 220.0))  # 220 BPM
    max_lag = min(len(corr) - 1, int(frame_rate * 60.0 / 45.0))  # 45 BPM
    if max_lag <= min_lag:
        return (120.0, 0.0)
    window = corr[min_lag : max_lag + 1]
    best = int(np.argmax(window)) + min_lag
    bpm = 60.0 * frame_rate / best
    # Prefer the 60-180 range by testing octave multiples of the found tempo.
    for factor in (0.5, 2.0):
        alt = bpm * factor
        if 60.0 <= alt <= 180.0 and not (60.0 <= bpm <= 180.0):
            bpm = alt
    peak = float(window.max())
    others = np.sort(window)[::-1]
    runner = float(others[min(len(others) - 1, max(1, len(others) // 8))])
    confidence = max(0.0, min(1.0, (peak - runner) * 2.2 + peak * 0.4))
    return (float(bpm), confidence)


def _chroma(samples: np.ndarray, sample_rate: int, hop: int = 2048) -> np.ndarray:
    """12-bin chroma from an STFT, weighted by magnitude."""
    n_fft = 4096
    window = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    valid = freqs > 27.5
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69.0 + 12.0 * np.log2(np.where(valid, freqs, 440.0) / 440.0)
    bins = np.mod(np.round(midi).astype(int), 12)
    chroma = np.zeros(12, dtype=np.float64)
    frames = 1 + max(0, (len(samples) - n_fft) // hop)
    for i in range(max(1, frames)):
        chunk = samples[i * hop : i * hop + n_fft]
        if len(chunk) < n_fft:
            chunk = np.pad(chunk, (0, n_fft - len(chunk)))
        spec = np.abs(np.fft.rfft(chunk * window))
        spec = np.where(valid, spec, 0.0)
        np.add.at(chroma, bins, spec)
    total = chroma.sum()
    return chroma / total if total > 0 else chroma


def _key_from_chroma(chroma: np.ndarray) -> tuple[int, str, float]:
    scored: list[tuple[float, int, str]] = []
    for tonic in range(12):
        rotated = np.roll(chroma, -tonic)
        scored.append((_correlate(rotated.tolist(), MAJOR_PROFILE), tonic, "major"))
        scored.append((_correlate(rotated.tolist(), MINOR_PROFILE), tonic, "minor"))
    scored.sort(reverse=True)
    best, tonic, mode = scored[0]
    margin = max(0.0, best - scored[1][0])
    confidence = max(0.0, min(1.0, 0.55 * max(0.0, best) + 0.45 * min(1.0, margin * 4.0)))
    return (tonic, mode, confidence)


def analyze_audio_buffer(
    samples: np.ndarray, sample_rate: int, *, prefer_librosa: bool = True
) -> TrackAnalysis:
    """Analyse mono float32 samples."""
    if samples.ndim > 1:
        samples = samples.mean(axis=0)
    samples = np.asarray(samples, dtype=np.float32)
    duration = len(samples) / float(sample_rate)
    if len(samples) == 0:
        return TrackAnalysis(0.0, 120.0, 0.0, "C", "major", 0.0, "4/4", 0.0, 0.0, (0, 0), 0.0, 0, "empty")

    energy = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    hop = 512
    backend = "builtin"
    tempo = 120.0
    tempo_conf = 0.0
    onset_count = 0

    if prefer_librosa and librosa_available():
        try:
            import librosa

            backend = "librosa"
            env = librosa.onset.onset_strength(y=samples, sr=sample_rate, hop_length=hop)
            tempo_arr = librosa.feature.tempo(onset_envelope=env, sr=sample_rate, hop_length=hop)
            tempo = float(np.atleast_1d(tempo_arr)[0])
            onsets = librosa.onset.onset_detect(
                onset_envelope=env, sr=sample_rate, hop_length=hop, units="time"
            )
            onset_count = int(len(onsets))
            _, tempo_conf = _tempo_from_envelope(np.asarray(env, dtype=np.float32), sample_rate, hop)
            chroma = librosa.feature.chroma_cqt(y=samples, sr=sample_rate).mean(axis=1)
            chroma = chroma / (chroma.sum() or 1.0)
        except Exception:  # noqa: BLE001 - fall back rather than fail analysis
            backend = "builtin"

    if backend == "builtin":
        env = _onset_envelope(samples, sample_rate, hop)
        tempo, tempo_conf = _tempo_from_envelope(env, sample_rate, hop)
        threshold = float(env.mean() + env.std())
        peaks = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > threshold)
        onset_count = int(np.count_nonzero(peaks))
        chroma = _chroma(samples, sample_rate)

    tonic, mode, key_conf = _key_from_chroma(np.asarray(chroma, dtype=np.float64))
    onset_density = onset_count / duration if duration > 0 else 0.0

    # Register: bounds of the spectral energy, expressed as MIDI numbers.
    spec = np.abs(np.fft.rfft(samples[: min(len(samples), sample_rate * 30)]))
    freqs = np.fft.rfftfreq(min(len(samples), sample_rate * 30), 1.0 / sample_rate)
    if spec.size > 4 and spec.sum() > 0:
        cumulative = np.cumsum(spec)
        cumulative = cumulative / cumulative[-1]
        lo_f = float(freqs[int(np.searchsorted(cumulative, 0.05))])
        hi_f = float(freqs[int(np.searchsorted(cumulative, 0.95))])
        lo = int(round(69 + 12 * np.log2(max(lo_f, 20.0) / 440.0)))
        hi = int(round(69 + 12 * np.log2(max(hi_f, 40.0) / 440.0)))
        pitch_range = (max(0, min(127, lo)), max(0, min(127, hi)))
    else:
        pitch_range = (0, 0)

    # Polyphony proxy: spectral flatness. Tonal/monophonic material is peaky.
    flat = 0.0
    if spec.size > 4:
        s = spec + 1e-12
        flat = float(np.exp(np.mean(np.log(s))) / np.mean(s))
    polyphony = 1.0 + 5.0 * max(0.0, min(1.0, flat * 6.0))

    return TrackAnalysis(
        duration=duration,
        tempo_bpm=float(tempo),
        tempo_confidence=float(tempo_conf),
        key=pitch_class_name(tonic, flats=mode == "minor"),
        mode=mode,
        key_confidence=float(key_conf),
        time_signature_estimate="4/4",
        energy=energy,
        onset_density=onset_density,
        pitch_range=pitch_range,
        polyphony_estimate=polyphony,
        tonic_pitch_class=tonic,
        backend=backend,
    )

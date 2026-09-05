"""Waveform peaks for the UI.

The frontend never receives raw samples: a 4-minute track is ~10 million
floats. It gets min/max buckets at a resolution it can actually draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class WaveformPeaks:
    min_values: list[float]
    max_values: list[float]
    rms_values: list[float]
    buckets: int
    duration: float
    sample_rate: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "min": [round(v, 4) for v in self.min_values],
            "max": [round(v, 4) for v in self.max_values],
            "rms": [round(v, 4) for v in self.rms_values],
            "buckets": self.buckets,
            "durationSeconds": round(self.duration, 3),
            "sampleRate": self.sample_rate,
        }


def compute_peaks(
    samples: np.ndarray, sample_rate: int, *, buckets: int = 1600
) -> WaveformPeaks:
    """Downsample to ``buckets`` min/max/RMS triples."""
    if samples.ndim > 1:
        samples = samples.mean(axis=0)
    n = int(samples.shape[-1])
    duration = n / float(sample_rate)
    buckets = max(1, min(int(buckets), max(1, n)))
    if n == 0:
        return WaveformPeaks([0.0], [0.0], [0.0], 1, 0.0, sample_rate)

    edges = np.linspace(0, n, buckets + 1, dtype=np.int64)
    mins = np.empty(buckets, dtype=np.float32)
    maxs = np.empty(buckets, dtype=np.float32)
    rms = np.empty(buckets, dtype=np.float32)
    for i in range(buckets):
        a, b = edges[i], edges[i + 1]
        if b <= a:
            b = min(n, a + 1)
        chunk = samples[a:b]
        mins[i] = float(chunk.min())
        maxs[i] = float(chunk.max())
        rms[i] = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))

    peak = float(max(abs(mins.min()), abs(maxs.max()), 1e-9))
    if peak > 0:
        mins = mins / peak
        maxs = maxs / peak
        rms = rms / peak
    return WaveformPeaks(
        min_values=mins.astype(float).tolist(),
        max_values=maxs.astype(float).tolist(),
        rms_values=rms.astype(float).tolist(),
        buckets=buckets,
        duration=duration,
        sample_rate=sample_rate,
    )

"""Key estimation from note events (Krumhansl-Schmuckler correlation).

Reported with a confidence, because key detection is genuinely ambiguous for a
lot of real music and the UI should say so rather than pretend.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .events import NoteEvent
from .pitch import pitch_class, pitch_class_name

# Krumhansl-Kessler probe-tone profiles.
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


@dataclass(frozen=True)
class KeyEstimate:
    tonic_pitch_class: int
    mode: str  # "major" | "minor"
    confidence: float
    correlation: float
    runner_up: str | None = None

    @property
    def name(self) -> str:
        return pitch_class_name(self.tonic_pitch_class, flats=self.mode == "minor") + " " + self.mode.title()

    def to_dict(self) -> dict[str, object]:
        return {
            "tonicPitchClass": self.tonic_pitch_class,
            "tonic": pitch_class_name(self.tonic_pitch_class, flats=self.mode == "minor"),
            "mode": self.mode,
            "name": self.name,
            "confidence": round(self.confidence, 4),
            "correlation": round(self.correlation, 4),
            "runnerUp": self.runner_up,
        }


def pitch_class_histogram(
    events: Sequence[NoteEvent], *, weight_by_duration: bool = True
) -> list[float]:
    """Duration- and velocity-weighted pitch-class distribution."""
    hist = [0.0] * 12
    for ev in events:
        w = 1.0
        if weight_by_duration:
            w *= max(0.05, min(4.0, ev.duration_seconds))
        w *= 0.5 + 0.5 * max(0.0, min(1.0, ev.velocity))
        w *= max(0.1, min(1.0, ev.confidence))
        hist[pitch_class(ev.pitch_midi)] += w
    return hist


def _correlate(hist: Sequence[float], profile: Sequence[float]) -> float:
    n = len(hist)
    mh = sum(hist) / n
    mp = sum(profile) / n
    num = sum((hist[i] - mh) * (profile[i] - mp) for i in range(n))
    dh = math.sqrt(sum((hist[i] - mh) ** 2 for i in range(n)))
    dp = math.sqrt(sum((profile[i] - mp) ** 2 for i in range(n)))
    if dh <= 1e-9 or dp <= 1e-9:
        return 0.0
    return num / (dh * dp)


def estimate_key(events: Sequence[NoteEvent]) -> KeyEstimate:
    """Best (tonic, mode) plus a confidence from the margin over the runner-up."""
    hist = pitch_class_histogram(events)
    if sum(hist) <= 0:
        return KeyEstimate(0, "major", 0.0, 0.0)

    scored: list[tuple[float, int, str]] = []
    for tonic in range(12):
        rotated = hist[tonic:] + hist[:tonic]
        scored.append((_correlate(rotated, MAJOR_PROFILE), tonic, "major"))
        scored.append((_correlate(rotated, MINOR_PROFILE), tonic, "minor"))
    scored.sort(reverse=True)

    best_corr, tonic, mode = scored[0]
    second_corr, s_tonic, s_mode = scored[1]
    margin = max(0.0, best_corr - second_corr)
    # Confidence blends absolute fit with how decisively it beat the alternative.
    confidence = max(0.0, min(1.0, 0.55 * max(0.0, best_corr) + 0.45 * min(1.0, margin * 4.0)))
    runner = pitch_class_name(s_tonic, flats=s_mode == "minor") + " " + s_mode.title()
    return KeyEstimate(tonic, mode, confidence, best_corr, runner)


def scale_pitch_classes(tonic: int, mode: str) -> frozenset[int]:
    intervals = (0, 2, 4, 5, 7, 9, 11) if mode == "major" else (0, 2, 3, 5, 7, 8, 10)
    return frozenset((tonic + i) % 12 for i in intervals)

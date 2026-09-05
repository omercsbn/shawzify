"""Density management.

Removing the globally least important notes wrecks quiet passages to pay for
loud ones. Instead a sliding window finds the passages that actually exceed the
budget and thins only those, while protecting beat anchors, melodic peaks and
phrase edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..music.events import NoteEvent
from ..music.phrases import Phrase


@dataclass
class DensityResult:
    kept: list[int]
    removed: list[int]
    peak_density: float
    window_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "keptCount": len(self.kept),
            "removedCount": len(self.removed),
            "peakDensity": round(self.peak_density, 3),
            "windowSeconds": self.window_seconds,
        }


def measure_density(events: Sequence[NoteEvent], window: float = 1.0) -> float:
    """Peak notes-per-second over a sliding window."""
    if not events:
        return 0.0
    times = sorted(e.start_seconds for e in events)
    best = 0
    j = 0
    for i in range(len(times)):
        while times[i] - times[j] > window:
            j += 1
        best = max(best, i - j + 1)
    return best / window


def reduce_density(
    events: Sequence[NoteEvent],
    importance: Sequence[float],
    *,
    max_notes_per_second: float,
    window: float = 1.0,
    phrases: Sequence[Phrase] | None = None,
    protect_indices: Sequence[int] | None = None,
    bpm: float | None = None,
) -> DensityResult:
    """Thin dense passages down to ``max_notes_per_second``.

    Notes are dropped one at a time, always the least important note inside the
    currently worst window, so removal is spread through the passage rather than
    gouged out of one spot.
    """
    n = len(events)
    if n == 0:
        return DensityResult([], [], 0.0, window)
    budget = max(1.0, float(max_notes_per_second))
    alive = [True] * n
    protected = set(protect_indices or ())

    # Beat anchors and phrase edges get a floor on their effective importance
    # so they are the last thing to go.
    effective = list(importance)
    if bpm and bpm > 0:
        beat = 60.0 / bpm
        for i, ev in enumerate(events):
            off = abs((ev.start_seconds / beat) - round(ev.start_seconds / beat))
            if off < 0.08:
                effective[i] = max(effective[i], effective[i] * 0.5 + 0.5)
    if phrases:
        for p in phrases:
            if not p.event_indices:
                continue
            order = sorted(p.event_indices)
            for edge in (order[0], order[-1]):
                if edge < n:
                    effective[edge] = max(effective[edge], effective[edge] * 0.4 + 0.6)

    times = [e.start_seconds for e in events]
    max_in_window = max(1, int(round(budget * window)))

    def worst_window() -> tuple[int, int, int] | None:
        """Return (start_index, end_index_exclusive, count) of the densest window."""
        live = [i for i in range(n) if alive[i]]
        if not live:
            return None
        best: tuple[int, int, int] | None = None
        j = 0
        for k, i in enumerate(live):
            while times[i] - times[live[j]] > window:
                j += 1
            count = k - j + 1
            if best is None or count > best[2]:
                best = (j, k + 1, count)
        return best

    removed: list[int] = []
    guard = 0
    while guard < n * 2:
        guard += 1
        live = [i for i in range(n) if alive[i]]
        w = worst_window()
        if w is None or w[2] <= max_in_window:
            break
        window_indices = [live[x] for x in range(w[0], w[1])]
        candidates = [i for i in window_indices if i not in protected]
        if not candidates:
            candidates = window_indices
            if not candidates:
                break
        victim = min(candidates, key=lambda i: (effective[i], -times[i]))
        alive[victim] = False
        removed.append(victim)

    kept = [i for i in range(n) if alive[i]]
    peak = measure_density([events[i] for i in kept], window)
    return DensityResult(kept, sorted(removed), peak, window)


def suggest_density(events: Sequence[NoteEvent], *, complexity: float) -> float:
    """A sensible per-song density budget when the user has not set one."""
    if not events:
        return 8.0
    observed = measure_density(events, 1.0)
    # Never below 3 n/s (that is unplayably sparse) and never above the source.
    low, high = 3.0, max(4.0, observed)
    return low + (high - low) * max(0.0, min(1.0, complexity))

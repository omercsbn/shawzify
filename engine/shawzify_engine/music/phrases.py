"""Phrase detection.

Phrases matter twice: density reduction must not tear a phrase apart, and song
splitting should cut between phrases rather than mid-figure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .events import NoteEvent, group_by_onset, sort_events


@dataclass(frozen=True)
class Phrase:
    index: int
    start_seconds: float
    end_seconds: float
    event_indices: tuple[int, ...]
    boundary_strength: float  # how strong the gap that opened this phrase was

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "startSeconds": round(self.start_seconds, 4),
            "endSeconds": round(self.end_seconds, 4),
            "noteCount": len(self.event_indices),
            "boundaryStrength": round(self.boundary_strength, 4),
        }


def detect_phrases(
    events: Sequence[NoteEvent],
    *,
    bpm: float | None = None,
    min_notes: int = 3,
    gap_factor: float = 2.2,
) -> list[Phrase]:
    """Split on rests that are unusually long for this piece.

    The threshold is relative (``gap_factor`` times the median inter-onset gap)
    with a musical floor of one beat, so it adapts to tempo and density instead
    of using a fixed number of seconds.
    """
    ordered = sort_events(events)
    if not ordered:
        return []
    groups = group_by_onset(ordered, 0.03)
    onsets = [g[0].start_seconds for g in groups]
    if len(onsets) < 2:
        return [
            Phrase(
                0,
                ordered[0].start_seconds,
                max(e.end_seconds for e in ordered),
                tuple(range(len(ordered))),
                1.0,
            )
        ]

    gaps = [b - a for a, b in zip(onsets, onsets[1:])]
    ordered_gaps = sorted(gaps)
    median_gap = ordered_gaps[len(ordered_gaps) // 2]
    beat = 60.0 / bpm if bpm and bpm > 0 else 0.5
    threshold = max(median_gap * gap_factor, beat * 0.9, 0.25)

    # Index every event by its group so phrase membership stays exact.
    index_of: dict[int, int] = {}
    for i, ev in enumerate(ordered):
        index_of[id(ev)] = i

    phrases: list[Phrase] = []
    current: list[int] = list(index_of[id(e)] for e in groups[0])
    current_start = onsets[0]
    strength = 1.0
    pending_strength = 1.0
    for gi in range(1, len(groups)):
        gap = onsets[gi] - onsets[gi - 1]
        if gap >= threshold and len(current) >= min_notes:
            end = max(ordered[i].end_seconds for i in current)
            phrases.append(
                Phrase(len(phrases), current_start, min(end, onsets[gi]), tuple(sorted(current)), strength)
            )
            current = []
            current_start = onsets[gi]
            strength = pending_strength = min(1.0, gap / max(threshold, 1e-6))
        current.extend(index_of[id(e)] for e in groups[gi])
    if current:
        end = max(ordered[i].end_seconds for i in current)
        phrases.append(Phrase(len(phrases), current_start, end, tuple(sorted(current)), pending_strength))
    return phrases


def phrase_of_event(phrases: Sequence[Phrase], event_index: int) -> Phrase | None:
    for p in phrases:
        if event_index in p.event_indices:
            return p
    return None


def phrase_position(phrases: Sequence[Phrase], event_index: int) -> float:
    """Where in its phrase an event sits: 0.0 at the start, 1.0 at the end."""
    p = phrase_of_event(phrases, event_index)
    if p is None or len(p.event_indices) < 2:
        return 0.0
    order = sorted(p.event_indices)
    return order.index(event_index) / (len(order) - 1)


def boundary_seconds(phrases: Sequence[Phrase]) -> list[float]:
    """Times that make good cut points, best (longest rest) first is *not*
    applied here -- order is chronological so callers can pick by position."""
    return [p.start_seconds for p in phrases[1:]]

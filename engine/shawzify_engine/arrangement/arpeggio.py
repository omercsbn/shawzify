"""Chord to arpeggio conversion.

Only used when notes genuinely cannot sound together and there is *time* to
spread them: at 180 BPM in sixteenths there is no room, and forcing an arpeggio
there would smear the rhythm. The pattern is chosen from tempo and available
space, not applied uniformly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class ArpeggioPattern(str, Enum):
    UP = "up"
    DOWN = "down"
    ROOT_THIRD_FIFTH = "root_third_fifth"
    ALTERNATING = "alternating"


@dataclass(frozen=True)
class ArpeggioPlan:
    pattern: ArpeggioPattern
    tick_offsets: tuple[int, ...]
    order: tuple[int, ...]  # indices into the input list, in playing order

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern.value,
            "tickOffsets": list(self.tick_offsets),
            "order": list(self.order),
        }


def _order_for(pattern: ArpeggioPattern, pitches: Sequence[int]) -> list[int]:
    idx = list(range(len(pitches)))
    if pattern is ArpeggioPattern.UP:
        return sorted(idx, key=lambda i: pitches[i])
    if pattern is ArpeggioPattern.DOWN:
        return sorted(idx, key=lambda i: -pitches[i])
    if pattern is ArpeggioPattern.ROOT_THIRD_FIFTH:
        # Lowest first, then upward -- the same as UP for a close voicing, but
        # kept distinct because it starts from the bass even when the melody is
        # listed first.
        return sorted(idx, key=lambda i: pitches[i])
    # ALTERNATING: outside-in, which keeps the top and bottom both audible.
    ascending = sorted(idx, key=lambda i: pitches[i])
    out: list[int] = []
    lo, hi = 0, len(ascending) - 1
    while lo <= hi:
        out.append(ascending[lo])
        if lo != hi:
            out.append(ascending[hi])
        lo += 1
        hi -= 1
    return out


def plan_arpeggio(
    pitches: Sequence[int],
    *,
    available_ticks: int,
    bpm: float | None = None,
    ticks_per_second: int = 16,
    preferred: ArpeggioPattern | None = None,
) -> ArpeggioPlan | None:
    """Spread ``pitches`` over ticks, or return None if there is no room.

    ``available_ticks`` is the gap to the next musical event; the arpeggio must
    finish inside it or it will collide with the following beat.
    """
    n = len(pitches)
    if n < 2:
        return None
    if available_ticks < n - 1:
        return None

    # One tick is 1/16 s. Aim for roughly a 32nd note, floored at one tick, and
    # never let the figure use more than the gap available.
    if bpm and bpm > 0:
        beat_ticks = (60.0 / bpm) * ticks_per_second
        step = max(1, int(round(beat_ticks / 8.0)))
    else:
        step = 1
    while step > 1 and step * (n - 1) > available_ticks:
        step -= 1
    if step * (n - 1) > available_ticks:
        return None

    pattern = preferred
    if pattern is None:
        # Fast passages get a plain upward roll (least attention-grabbing);
        # slower ones can afford a shape.
        if step <= 1:
            pattern = ArpeggioPattern.UP
        elif n >= 3:
            pattern = ArpeggioPattern.ROOT_THIRD_FIFTH
        else:
            pattern = ArpeggioPattern.UP

    order = _order_for(pattern, pitches)
    offsets = tuple(step * k for k in range(len(order)))
    return ArpeggioPlan(pattern, offsets, tuple(order))


def should_arpeggiate(
    *,
    unplaced_count: int,
    available_ticks: int,
    notes_per_second: float,
    enabled: bool,
) -> bool:
    """Guard so arpeggiation stays the exception, not the default texture."""
    if not enabled or unplaced_count <= 0:
        return False
    if available_ticks < 2:
        return False
    # Above roughly eight notes a second the listener hears a smear, not a chord.
    return notes_per_second <= 8.0

"""Note importance.

When the Shawzin cannot play everything, importance decides what survives.
The weights below are a starting point tuned on the golden fixtures, not
gospel -- ``ImportanceWeights`` is a parameter everywhere it is used, and the
tests assert on *relative* ordering (a melody peak beats an inner voice), never
on exact numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from .events import NoteEvent, group_by_onset, sort_events
from .phrases import Phrase, detect_phrases


@dataclass(frozen=True)
class ImportanceWeights:
    confidence: float = 0.20
    velocity: float = 0.15
    melodic_prominence: float = 0.20
    duration: float = 0.15
    rhythmic_salience: float = 0.15
    phrase_significance: float = 0.15

    def normalized(self) -> ImportanceWeights:
        total = sum(asdict(self).values())
        if total <= 0:
            return ImportanceWeights()
        return ImportanceWeights(**{k: v / total for k, v in asdict(self).items()})

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class ImportanceFactors:
    """Per-note breakdown, kept so the UI can explain a removal."""

    confidence: float
    velocity: float
    melodic_prominence: float
    duration: float
    rhythmic_salience: float
    phrase_significance: float
    total: float

    def to_dict(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in asdict(self).items()}


def _metrical_strength(seconds: float, bpm: float | None, beats_per_bar: int = 4) -> float:
    """1.0 on a downbeat, less on weaker subdivisions."""
    if not bpm or bpm <= 0:
        return 0.5
    beat = 60.0 / bpm
    position = (seconds / beat) % beats_per_bar
    nearest = round(position) % beats_per_bar
    off_grid = abs(position - round(position))
    if nearest == 0:
        base = 1.0
    elif beats_per_bar >= 4 and nearest == beats_per_bar // 2:
        base = 0.8
    else:
        base = 0.6
    # An onset far from any beat is syncopation, which is still musical but
    # less structurally load-bearing than a clean beat hit.
    return base * (1.0 - min(1.0, off_grid * 1.2)) + 0.25 * min(1.0, off_grid * 1.2)


def compute_importance(
    events: Sequence[NoteEvent],
    *,
    bpm: float | None = None,
    weights: ImportanceWeights | None = None,
    phrases: Sequence[Phrase] | None = None,
    onset_tolerance: float = 0.03,
) -> list[ImportanceFactors]:
    """Score every event 0..1. Output order matches ``sort_events(events)``."""
    ordered = sort_events(events)
    if not ordered:
        return []
    w = (weights or ImportanceWeights()).normalized()
    if phrases is None:
        phrases = detect_phrases(ordered, bpm=bpm)

    durations = [e.duration_seconds for e in ordered]
    max_duration = max(durations) or 1.0
    median_duration = sorted(durations)[len(durations) // 2] or 1.0

    groups = group_by_onset(ordered, onset_tolerance)
    index_of = {id(e): i for i, e in enumerate(ordered)}

    # Melodic prominence: top voice in its simultaneity group, plus contour
    # peaks (local maxima/minima of the top line) which carry recognition.
    prominence = [0.0] * len(ordered)
    top_line: list[tuple[int, int]] = []  # (event index, pitch)
    for group in groups:
        pitches = [e.pitch_midi for e in group]
        top = max(pitches)
        bottom = min(pitches)
        for e in group:
            i = index_of[id(e)]
            if e.pitch_midi == top:
                prominence[i] = 1.0 if len(group) > 1 else 0.85
            elif e.pitch_midi == bottom:
                prominence[i] = 0.55  # bass carries harmony
            else:
                prominence[i] = 0.35
        top_event = max(group, key=lambda e: e.pitch_midi)
        top_line.append((index_of[id(top_event)], top_event.pitch_midi))

    for k in range(1, len(top_line) - 1):
        prev_p = top_line[k - 1][1]
        cur_i, cur_p = top_line[k]
        next_p = top_line[k + 1][1]
        is_peak = cur_p > prev_p and cur_p > next_p
        is_valley = cur_p < prev_p and cur_p < next_p
        leap_in = abs(cur_p - prev_p) >= 5
        if is_peak:
            prominence[cur_i] = min(1.0, prominence[cur_i] + 0.25)
        elif is_valley or leap_in:
            prominence[cur_i] = min(1.0, prominence[cur_i] + 0.12)
    if top_line:
        prominence[top_line[0][0]] = min(1.0, prominence[top_line[0][0]] + 0.15)

    # Repetition: a pitch heard many times is more identifiable, with
    # diminishing returns so a drone does not dominate.
    counts: dict[int, int] = {}
    for e in ordered:
        counts[e.pitch_midi] = counts.get(e.pitch_midi, 0) + 1
    max_count = max(counts.values()) or 1

    out: list[ImportanceFactors] = []
    for i, ev in enumerate(ordered):
        conf = max(0.0, min(1.0, ev.confidence))
        vel = max(0.0, min(1.0, ev.velocity))
        dur = 0.6 * min(1.0, ev.duration_seconds / max_duration) + 0.4 * min(
            1.0, ev.duration_seconds / (median_duration * 2.0)
        )
        rhythm = _metrical_strength(ev.start_seconds, bpm)
        rep = math.log1p(counts[ev.pitch_midi]) / math.log1p(max_count)
        rhythm = 0.75 * rhythm + 0.25 * rep

        phrase_score = 0.5
        for p in phrases:
            if i in p.event_indices:
                order = sorted(p.event_indices)
                pos = order.index(i) / max(1, len(order) - 1)
                # Phrase openings and closes carry the shape.
                edge = max(0.0, 1.0 - min(pos, 1.0 - pos) * 3.0)
                phrase_score = 0.45 + 0.4 * edge + 0.15 * min(1.0, p.boundary_strength)
                break

        total = (
            w.confidence * conf
            + w.velocity * vel
            + w.melodic_prominence * prominence[i]
            + w.duration * dur
            + w.rhythmic_salience * rhythm
            + w.phrase_significance * phrase_score
        )
        out.append(
            ImportanceFactors(
                confidence=conf,
                velocity=vel,
                melodic_prominence=prominence[i],
                duration=dur,
                rhythmic_salience=rhythm,
                phrase_significance=phrase_score,
                total=max(0.0, min(1.0, total)),
            )
        )
    return out


def melody_line(
    events: Sequence[NoteEvent],
    *,
    bpm: float | None = None,
    onset_tolerance: float = 0.03,
) -> list[NoteEvent]:
    """Extract one note per simultaneity group: the melody as a listener hears it.

    Highest-voice wins, except where the top note is a short decoration and a
    longer note underneath is clearly the sustained melody.
    """
    ordered = sort_events(events)
    scores = compute_importance(ordered, bpm=bpm)
    index_of = {id(e): i for i, e in enumerate(ordered)}
    out: list[NoteEvent] = []
    for group in group_by_onset(ordered, onset_tolerance):
        if len(group) == 1:
            out.append(group[0])
            continue
        best = max(
            group,
            key=lambda e: (
                scores[index_of[id(e)]].total * 0.6 + (e.pitch_midi / 127.0) * 0.4
            ),
        )
        out.append(best)
    return out

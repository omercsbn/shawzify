"""Polyphony reduction under the Shawzin's fret constraint.

The constraint that shapes everything here: notes sounding at the same instant
must share one fret state, and each scale note lives at exactly one
(fret, string). So the only notes playable *with* a given note are the two
others on its fret row. Picking survivors at random would be musically
arbitrary; this module ranks by harmonic function and voice leading.

Combined fret states (12/23/13/123) are the other option -- they play a fixed
three-note chord. When a source chord's pitch classes line up with one of those
voicings, using it preserves far more harmony than two scale notes could.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..music.events import NoteEvent
from ..music.pitch import pitch_class
from ..shawzin.instrument import ShawzinChord, ShawzinNote, ShawzinScale

#: Interval above the chord root -> priority (lower survives first).
#: Root and third define the chord's identity, the seventh its colour, and the
#: fifth is the classic first note to drop.
FUNCTION_PRIORITY: dict[int, int] = {
    0: 0,   # root
    4: 1,   # major third
    3: 1,   # minor third
    10: 2,  # minor seventh
    11: 2,  # major seventh
    7: 4,   # fifth
    2: 3,   # ninth / sus2
    5: 3,   # eleventh / sus4
    9: 3,   # sixth / thirteenth
    6: 3,   # tritone (as #11 or b5, it is characteristic)
    8: 4,   # augmented fifth / minor sixth
    1: 5,   # flat ninth
}


@dataclass(frozen=True)
class Placement:
    """One note placed on the instrument."""

    source_index: int
    midi: int
    fret: str
    string: str
    exact: bool
    octave_shift: int

    @property
    def position(self) -> str:
        return self.fret + "-" + self.string


def estimate_root(pitches: Sequence[int]) -> int:
    """Pitch class most likely to be the chord root.

    Prefers the interpretation under which the other notes form recognisable
    intervals; falls back to the lowest note, which is right more often than not.
    """
    if not pitches:
        return 0
    pcs = sorted({pitch_class(p) for p in pitches})
    if len(pcs) == 1:
        return pcs[0]
    best_pc = pitch_class(min(pitches))
    best_score = -1e9
    for cand in pcs:
        score = 0.0
        for p in pcs:
            interval = (p - cand) % 12
            score += {0: 3.0, 7: 2.5, 4: 2.2, 3: 2.2, 10: 1.4, 11: 1.2}.get(interval, -0.4)
        if pitch_class(min(pitches)) == cand:
            score += 1.5  # bass note bias
        if score > best_score:
            best_score = score
            best_pc = cand
    return best_pc


def rank_notes(
    events: Sequence[NoteEvent],
    indices: Sequence[int],
    *,
    lead_index: int,
    importance: Sequence[float],
) -> list[int]:
    """Order source indices by which should survive, most important first."""
    pitches = [events[i].pitch_midi for i in indices]
    root = estimate_root(pitches)
    top = max(pitches)
    bottom = min(pitches)

    def key(i: int) -> tuple:
        if i == lead_index:
            return (-1, 0, 0.0, 0)
        p = events[i].pitch_midi
        interval = (pitch_class(p) - root) % 12
        priority = FUNCTION_PRIORITY.get(interval, 5)
        # The bass note anchors the harmony; the top note carries the tune.
        if p == bottom:
            priority = min(priority, 1)
        if p == top:
            priority = min(priority, 1)
        return (priority, 0, -importance[i], -p)

    return sorted(indices, key=key)


def score_chord_substitution(
    chord: ShawzinChord, pitches: Sequence[int], *, root_pc: int
) -> float:
    """How well a Shawzin chord position stands in for a set of source pitches (0..1)."""
    if not pitches:
        return 0.0
    src_pcs = {pitch_class(p) for p in pitches}
    chord_pcs = set(chord.pitch_classes)
    overlap = len(src_pcs & chord_pcs) / max(1, len(src_pcs))
    extra = len(chord_pcs - src_pcs) / max(1, len(chord_pcs))
    root_bonus = 0.25 if root_pc in chord_pcs else 0.0
    # Register matters: a chord voiced two octaves away is the wrong colour.
    src_centre = sum(pitches) / len(pitches)
    chord_centre = sum(chord.midi) / len(chord.midi)
    register = max(0.0, 1.0 - abs(src_centre - chord_centre) / 24.0)
    return max(0.0, min(1.0, 0.55 * overlap - 0.2 * extra + root_bonus + 0.25 * register))


def best_chord_position(
    scale: ShawzinScale, pitches: Sequence[int], *, minimum: float = 0.62
) -> tuple[ShawzinChord, float] | None:
    """Best combined-fret chord for these pitches, or None if nothing fits well."""
    if not scale.chords or len(pitches) < 2:
        return None
    root = estimate_root(pitches)
    best: tuple[ShawzinChord, float] | None = None
    for chord in scale.chords:
        s = score_chord_substitution(chord, pitches, root_pc=root)
        if best is None or s > best[1]:
            best = (chord, s)
    if best is None or best[1] < minimum:
        return None
    return best


def notes_on_fret(scale: ShawzinScale, fret: str) -> list[ShawzinNote]:
    return sorted((n for n in scale.notes if n.fret == fret), key=lambda n: n.midi)


def reduce_group(
    events: Sequence[NoteEvent],
    indices: Sequence[int],
    scale: ShawzinScale,
    *,
    lead_index: int,
    lead_note: ShawzinNote,
    importance: Sequence[float],
    max_voices: int,
    harmony_weight: float,
    semitone_tolerance: int = 1,
) -> tuple[list[Placement], list[int]]:
    """Place as many notes of a simultaneity group as the fret row allows.

    Returns ``(placements, unplaced_source_indices)``. The lead is always placed.
    """
    fret = lead_note.fret
    row = {n.string: n for n in notes_on_fret(scale, fret)}
    used: set[str] = {lead_note.string}
    placements = [
        Placement(lead_index, lead_note.midi, fret, lead_note.string, True, 0)
    ]
    if max_voices <= 1 or harmony_weight <= 0.0:
        return placements, [i for i in indices if i != lead_index]

    unplaced: list[int] = []
    ranked = rank_notes(events, indices, lead_index=lead_index, importance=importance)
    for i in ranked:
        if i == lead_index:
            continue
        if len(placements) >= max_voices:
            unplaced.append(i)
            continue
        pitch = events[i].pitch_midi
        target_pc = pitch_class(pitch)
        best: tuple[float, ShawzinNote] | None = None
        for string, note in row.items():
            if string in used:
                continue
            same_pc = pitch_class(note.midi) == target_pc
            error = 0 if same_pc else min(
                abs(pitch_class(note.midi) - target_pc) % 12,
                12 - (abs(pitch_class(note.midi) - target_pc) % 12),
            )
            if not same_pc and error > semitone_tolerance:
                continue
            octave_dist = abs(note.midi - pitch) / 12.0
            cost = error * 2.0 + octave_dist
            if best is None or cost < best[0]:
                best = (cost, note)
        if best is None:
            unplaced.append(i)
            continue
        note = best[1]
        used.add(note.string)
        placements.append(
            Placement(
                i,
                note.midi,
                fret,
                note.string,
                pitch_class(note.midi) == target_pc,
                round((note.midi - pitch) / 12.0),
            )
        )
    return placements, unplaced

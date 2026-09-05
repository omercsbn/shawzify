"""Scale and transposition search.

For every (scale, transpose) pair the Shawzin offers, estimate how much of the
source survives. This runs before the expensive mapping stage, so it uses a
fast analytic model rather than actually arranging: pitch-class coverage,
range fit, weighted-importance coverage, contour preservation and tonal
anchoring. The winner is then arranged for real.

9 scales x 25 transpositions x N notes stays comfortably interactive: the inner
loop is O(N) with a 12-entry lookup, so a 2000-note piece costs a few hundred
thousand integer operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..music.events import NoteEvent, group_by_onset, sort_events
from ..music.importance import ImportanceFactors
from ..music.key import KeyEstimate
from ..music.pitch import pitch_class
from ..shawzin.instrument import ShawzinInstrument, ShawzinScale
from .options import ArrangementOptions


@dataclass(frozen=True)
class ScaleCandidate:
    scale_id: str
    scale_name: str
    transpose: int
    score: float
    pitch_coverage: float
    weighted_coverage: float
    range_fit: float
    contour_fit: float
    tonal_fit: float
    mean_pitch_error: float
    octave_folds: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scaleId": self.scale_id,
            "scaleName": self.scale_name,
            "transpose": self.transpose,
            "score": round(self.score * 100.0, 2),
            "pitchCoverage": round(self.pitch_coverage, 4),
            "weightedCoverage": round(self.weighted_coverage, 4),
            "rangeFit": round(self.range_fit, 4),
            "contourFit": round(self.contour_fit, 4),
            "tonalFit": round(self.tonal_fit, 4),
            "meanPitchError": round(self.mean_pitch_error, 3),
            "octaveFolds": self.octave_folds,
        }


#: The table covers well past MIDI range so an extreme transposition still hits it.
_TABLE_LOW = -48
_TABLE_HIGH = 176


def _nearest_playable(pitch: int, playable: Sequence[int], pcs: frozenset[int]) -> tuple[int, int, bool]:
    """Nearest playable pitch, its distance, and whether the pitch class matched.

    Same-pitch-class candidates are preferred even when a chromatic neighbour is
    closer: an octave displacement keeps the harmony, a semitone shift does not.
    """
    exact_pc = pitch_class(pitch) in pcs
    best = playable[0]
    best_dist = abs(playable[0] - pitch)
    best_pc_match = pitch_class(playable[0]) == pitch_class(pitch)
    for cand in playable[1:]:
        dist = abs(cand - pitch)
        pc_match = pitch_class(cand) == pitch_class(pitch)
        better = False
        if pc_match and not best_pc_match:
            better = True
        elif pc_match == best_pc_match and dist < best_dist:
            better = True
        if better:
            best, best_dist, best_pc_match = cand, dist, pc_match
    return best, best_dist, exact_pc


@lru_cache(maxsize=64)
def _nearest_table(
    playable: tuple[int, ...], pcs: frozenset[int]
) -> tuple[tuple[int, int, bool], ...]:
    """Precomputed :func:`_nearest_playable` for every pitch, per scale.

    The search is over nine scales and twenty-five transpositions, so a
    two-thousand-note piece would otherwise call the inner scan half a million
    times. One 224-entry table per scale turns that into an index.
    """
    return tuple(
        _nearest_playable(p, playable, pcs) for p in range(_TABLE_LOW, _TABLE_HIGH)
    )


def evaluate_candidate(
    events: Sequence[NoteEvent],
    scale: ShawzinScale,
    transpose: int,
    *,
    importance: Sequence[float] | None = None,
    key: KeyEstimate | None = None,
    weights: dict[str, float] | None = None,
    top_indices: Sequence[int] | None = None,
) -> ScaleCandidate:
    """Score one (scale, transpose) pair. Higher is better; 0..1.

    ``top_indices`` is the index of the top note of each simultaneity group.
    It depends only on ``events``, so the caller computes it once for the whole
    search rather than per candidate.
    """
    if not events:
        return ScaleCandidate(scale.id, scale.name, transpose, 0.0, 0, 0, 0, 0, 0, 0.0, 0)

    w = {
        "coverage": 0.30,
        "weighted": 0.26,
        "range": 0.16,
        "contour": 0.14,
        "tonal": 0.14,
    }
    if weights:
        w.update(weights)

    playable = scale.playable_midi
    pcs = scale.pitch_classes
    lo, hi = playable[0], playable[-1]

    imp = list(importance) if importance is not None else [1.0] * len(events)
    total_weight = sum(imp) or 1.0

    exact = 0
    weighted_hit = 0.0
    in_range = 0
    pitch_errors: list[float] = []
    folds = 0
    mapped: list[int] = []

    table = _nearest_table(playable, pcs)
    for i, ev in enumerate(events):
        p = ev.pitch_midi + transpose
        if _TABLE_LOW <= p < _TABLE_HIGH:
            target, dist, pc_ok = table[p - _TABLE_LOW]
        else:
            target, dist, pc_ok = _nearest_playable(p, playable, pcs)
        mapped.append(target)
        if lo <= p <= hi:
            in_range += 1
        if pc_ok:
            exact += 1
            weighted_hit += imp[i]
            if target != p:
                folds += 1
        else:
            # Partial credit: a semitone off still resembles the source.
            weighted_hit += imp[i] * max(0.0, 1.0 - min(dist, 6) / 6.0) * 0.45
        pitch_errors.append(abs(target - p))

    n = len(events)
    pitch_coverage = exact / n
    weighted_coverage = weighted_hit / total_weight
    range_fit = in_range / n

    # Contour: does the mapped line move the same direction as the source?
    tops = list(top_indices) if top_indices is not None else melody_indices(events)
    contour_hits = 0
    contour_total = 0
    for ia, ib in zip(tops, tops[1:]):
        src = events[ib].pitch_midi - events[ia].pitch_midi
        out = mapped[ib] - mapped[ia]
        contour_total += 1
        if src == 0:
            contour_hits += 1 if out == 0 else 0
        elif (src > 0) == (out > 0) and out != 0:
            # Full credit for direction, reduced when the leap size changed a lot.
            ratio = min(abs(src), abs(out)) / max(abs(src), abs(out), 1)
            contour_hits += 0.6 + 0.4 * ratio
    contour_fit = contour_hits / contour_total if contour_total else 1.0

    # Tonal anchoring: the detected tonic (and its fifth) should be playable.
    if key is not None:
        tonic = (key.tonic_pitch_class + transpose) % 12
        fifth = (tonic + 7) % 12
        third = (tonic + (4 if key.mode == "major" else 3)) % 12
        tonal_fit = (
            0.5 * (1.0 if tonic in pcs else 0.0)
            + 0.25 * (1.0 if fifth in pcs else 0.0)
            + 0.25 * (1.0 if third in pcs else 0.0)
        )
        tonal_fit = tonal_fit * (0.4 + 0.6 * key.confidence) + (1.0 - key.confidence) * 0.3
    else:
        tonal_fit = 0.5

    mean_error = sum(pitch_errors) / n
    score = (
        w["coverage"] * pitch_coverage
        + w["weighted"] * weighted_coverage
        + w["range"] * range_fit
        + w["contour"] * contour_fit
        + w["tonal"] * tonal_fit
    )
    # Among near-ties, prefer the transposition that changes the music least.
    # A whole-octave shift keeps the key intact, so it costs far less than a
    # shift that lands the song in a different key.
    pc_shift = abs(transpose) % 12
    pc_shift = min(pc_shift, 12 - pc_shift)
    score -= pc_shift * 0.012 + (abs(transpose) // 12) * 0.0015
    return ScaleCandidate(
        scale_id=scale.id,
        scale_name=scale.name,
        transpose=transpose,
        score=max(0.0, min(1.0, score)),
        pitch_coverage=pitch_coverage,
        weighted_coverage=weighted_coverage,
        range_fit=range_fit,
        contour_fit=contour_fit,
        tonal_fit=tonal_fit,
        mean_pitch_error=mean_error,
        octave_folds=folds,
    )


def melody_indices(events: Sequence[NoteEvent], tolerance: float = 0.03) -> list[int]:
    """Index of the top note in each simultaneity group -- the melody line."""
    index_of = {id(e): i for i, e in enumerate(events)}
    return [
        index_of[id(max(g, key=lambda e: e.pitch_midi))]
        for g in group_by_onset(events, tolerance)
    ]


def find_best_shawzin_mapping(
    events: Sequence[NoteEvent],
    instrument: ShawzinInstrument,
    options: ArrangementOptions,
    *,
    importance: Sequence[ImportanceFactors] | Sequence[float] | None = None,
    key: KeyEstimate | None = None,
    top_n: int = 5,
) -> list[ScaleCandidate]:
    """Rank (scale, transpose) candidates, best first.

    Honours a pinned scale and/or transpose from ``options``; AUTO searches.
    """
    ordered = sort_events(events)
    if not ordered:
        return []

    imp_values: list[float] | None = None
    if importance:
        first = importance[0]
        if isinstance(first, ImportanceFactors):
            imp_values = [f.total for f in importance]  # type: ignore[union-attr]
        else:
            imp_values = [float(v) for v in importance]  # type: ignore[arg-type]

    if isinstance(options.scale, str):
        scales = [instrument.scale(options.scale)]
    else:
        scales = list(instrument.scales)

    if isinstance(options.transpose, int):
        transposes = [options.transpose]
    else:
        span = max(0, int(options.transpose_search))
        transposes = list(range(-span, span + 1))
        # Centre the search on the source's own register so a bass-heavy or
        # piccolo-register piece is not judged purely on pitch class.
        median = sorted(e.pitch_midi for e in ordered)[len(ordered) // 2]
        centre = instrument.overall_range[0] + 12
        suggested = centre - median
        for extra in (suggested, suggested + 12, suggested - 12):
            if abs(extra) <= 36 and extra not in transposes:
                transposes.append(extra)
        transposes.sort(key=lambda t: (abs(t), t))

    profile = options.profile
    weights = {
        "coverage": 0.30,
        "weighted": 0.20 + 0.10 * profile.melody_weight,
        "range": 0.16,
        "contour": 0.06 + 0.14 * profile.contour_weight,
        "tonal": 0.10 + 0.08 * profile.harmony_weight,
    }
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    # Group structure depends only on the events, so compute it once.
    tops = melody_indices(ordered)

    results: list[ScaleCandidate] = []
    for scale in scales:
        for t in transposes:
            results.append(
                evaluate_candidate(
                    ordered, scale, t,
                    importance=imp_values, key=key, weights=weights, top_indices=tops,
                )
            )
    # Deterministic tie-break so identical inputs always yield identical output.
    results.sort(key=lambda c: (-c.score, abs(c.transpose), c.scale_id, c.transpose))

    # Keep only the best transposition per scale in the shortlist, so the UI
    # shows genuinely different options instead of nine near-identical rows.
    seen: set[str] = set()
    shortlist: list[ScaleCandidate] = []
    for c in results:
        if c.scale_id in seen:
            continue
        seen.add(c.scale_id)
        shortlist.append(c)
        if len(shortlist) >= top_n:
            break
    return shortlist

"""Melody mapping by dynamic programming.

Mapping each note independently to its nearest playable pitch is what makes
naive converters sound wrong: the line jumps octaves at range boundaries and
the contour breaks. Instead every source note gets a *set* of playable
candidates (all octave-equivalents in the scale, plus near-miss neighbours when
the pitch class is unavailable) and a Viterbi pass picks the path minimising

    per-note cost  (pitch displacement, pitch-class mismatch, range pressure)
  + transition cost (voice-leading distance, contour direction, interval size)

which is O(N * K^2) with K around 3 candidates -- negligible next to
transcription.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..music.pitch import octave_equivalents, pitch_class
from ..shawzin.instrument import ShawzinScale


@dataclass(frozen=True)
class Candidate:
    """One playable option for a source note."""

    midi: int
    exact_pitch_class: bool
    octave_shift: int  # in octaves, relative to the transposed source pitch
    semitone_error: int


@dataclass(frozen=True)
class MappingCosts:
    pitch_displacement: float = 1.0
    pitch_class_miss: float = 6.0
    octave_shift: float = 2.2
    #: Cost of moving to a different octave than the previous note used.
    #:
    #: Without this, the octave was effectively chosen per note. A reviewer
    #: spotted it from a skim of the source and was right: measured on Fur
    #: Elise, 53% of consecutive notes inside a phrase changed register, and
    #: one phrase was spread over four octaves. Each note was individually
    #: reasonable and the line lurched between registers. Folding is a decision
    #: about a phrase, not about a note.
    register_change: float = 3.4
    range_edge: float = 1.2
    voice_leading: float = 0.55
    contour_break: float = 5.0
    interval_distortion: float = 0.9

    def scaled(self, *, contour_weight: float, pitch_weight: float) -> MappingCosts:
        return MappingCosts(
            pitch_displacement=self.pitch_displacement * pitch_weight,
            pitch_class_miss=self.pitch_class_miss * pitch_weight,
            octave_shift=self.octave_shift,
            register_change=self.register_change,
            range_edge=self.range_edge,
            voice_leading=self.voice_leading,
            contour_break=self.contour_break * contour_weight,
            interval_distortion=self.interval_distortion * contour_weight,
        )


def candidates_for(
    pitch: int, scale: ShawzinScale, *, max_octave_shift: int = 2, max_semitone_error: int = 2
) -> list[Candidate]:
    """Playable options for one (already transposed) source pitch."""
    playable = scale.playable_midi
    lo, hi = playable[0], playable[-1]
    pcs = scale.pitch_classes
    out: list[Candidate] = []

    if pitch_class(pitch) in pcs:
        for cand in octave_equivalents(pitch, lo, hi):
            shift = (cand - pitch) // 12
            if abs(shift) > max_octave_shift:
                continue
            if cand in playable:
                out.append(Candidate(cand, True, shift, 0))
    if not out:
        # Pitch class unavailable (or every octave out of range): fall back to
        # the closest playable pitches, near-misses first.
        scored = sorted(playable, key=lambda m: (abs(m - pitch), m))
        for cand in scored:
            err = abs(cand - pitch)
            if err > max_semitone_error + 12 * max_octave_shift:
                break
            same_pc = pitch_class(cand) == pitch_class(pitch)
            shift = round((cand - pitch) / 12.0)
            semis = abs(cand - pitch - shift * 12)
            out.append(Candidate(cand, same_pc, shift, semis))
            if len(out) >= 5:
                break
    if not out:
        nearest = min(playable, key=lambda m: abs(m - pitch))
        out.append(
            Candidate(nearest, pitch_class(nearest) == pitch_class(pitch), 0, abs(nearest - pitch))
        )
    return out


def _node_cost(c: Candidate, scale: ShawzinScale, costs: MappingCosts) -> float:
    playable = scale.playable_midi
    lo, hi = playable[0], playable[-1]
    span = max(1, hi - lo)
    cost = costs.octave_shift * abs(c.octave_shift)
    cost += costs.pitch_displacement * c.semitone_error
    if not c.exact_pitch_class:
        cost += costs.pitch_class_miss
    # Range-edge pressure: sitting on the very top or bottom note leaves no
    # room for the next leap, so mildly prefer the interior.
    edge = min(c.midi - lo, hi - c.midi) / span
    cost += costs.range_edge * max(0.0, 0.25 - edge) * 4.0
    return cost


def _transition_cost(
    prev_src: int,
    prev_out: Candidate,
    cur_src: int,
    cur_out: Candidate,
    costs: MappingCosts,
    *,
    new_phrase: bool = False,
) -> float:
    src_interval = cur_src - prev_src
    out_interval = cur_out.midi - prev_out.midi
    cost = costs.voice_leading * min(abs(out_interval), 24) / 12.0

    # Staying in one register matters within a phrase and not across phrases:
    # a phrase that begins somewhere new sounds like a phrase, whereas a note
    # that jumps mid-phrase sounds like a mistake. Folding an octave can even
    # *shrink* the output interval, so without this the voice-leading term
    # rewarded it.
    if not new_phrase and cur_out.octave_shift != prev_out.octave_shift:
        cost += costs.register_change * abs(cur_out.octave_shift - prev_out.octave_shift)

    if src_interval == 0:
        cost += costs.contour_break if out_interval != 0 else 0.0
        return cost
    src_dir = 1 if src_interval > 0 else -1
    out_dir = 0 if out_interval == 0 else (1 if out_interval > 0 else -1)
    if out_dir != src_dir:
        cost += costs.contour_break
    cost += costs.interval_distortion * abs(abs(out_interval) - abs(src_interval)) / 12.0
    return cost


def map_melody(
    pitches: Sequence[int],
    scale: ShawzinScale,
    *,
    costs: MappingCosts | None = None,
    max_octave_shift: int = 2,
    phrase_starts: Sequence[int] | None = None,
) -> list[Candidate]:
    """Viterbi over candidate sets. Returns one candidate per input pitch.

    ``phrase_starts`` gives the indices that begin a phrase, where changing
    register is free. Everywhere else it is paid for.
    """
    if not pitches:
        return []
    c = costs or MappingCosts()
    lattice = [candidates_for(p, scale, max_octave_shift=max_octave_shift) for p in pitches]
    boundaries = set(phrase_starts or ())

    n = len(pitches)
    best_cost: list[list[float]] = [[0.0] * len(col) for col in lattice]
    back: list[list[int]] = [[-1] * len(col) for col in lattice]

    for j, cand in enumerate(lattice[0]):
        best_cost[0][j] = _node_cost(cand, scale, c)

    for i in range(1, n):
        for j, cand in enumerate(lattice[i]):
            node = _node_cost(cand, scale, c)
            best = float("inf")
            arg = 0
            for k, prev in enumerate(lattice[i - 1]):
                total = best_cost[i - 1][k] + _transition_cost(
                    pitches[i - 1], prev, pitches[i], cand, c, new_phrase=i in boundaries
                )
                if total < best:
                    best = total
                    arg = k
            best_cost[i][j] = best + node
            back[i][j] = arg

    end = min(range(len(lattice[-1])), key=lambda j: best_cost[-1][j])
    path = [end]
    for i in range(n - 1, 0, -1):
        path.append(back[i][path[-1]])
    path.reverse()
    return [lattice[i][path[i]] for i in range(n)]


def map_single(pitch: int, scale: ShawzinScale, *, near: int | None = None) -> Candidate:
    """Map one pitch, optionally preferring the option closest to ``near``.

    Used for harmony notes, which are placed relative to an already-fixed
    melody note rather than as part of a line.
    """
    options = candidates_for(pitch, scale)
    if near is None:
        return min(options, key=lambda c: (_node_cost(c, scale, MappingCosts()), c.midi))
    return min(
        options,
        key=lambda c: (
            _node_cost(c, scale, MappingCosts()) + 0.4 * abs(c.midi - near),
            c.midi,
        ),
    )

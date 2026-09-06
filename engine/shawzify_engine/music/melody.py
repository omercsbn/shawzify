"""Follow one melodic line through polyphony.

Taking the highest note sounding at each moment is the obvious way to find a
melody and it is wrong for anything with two hands in it. When the right hand
rests, the top note becomes whatever the left hand is playing, so the "melody"
drops two octaves and comes back. Measured on Rob Dougan's "Clubbed to Death",
the line that reached the arranger leapt an octave or more between 55% of
consecutive notes, with a mean leap of 14.5 semitones and a maximum of five
octaves. No melody moves like that: melodies move mostly by step.

Everything downstream then inherits it. Octave folding follows a line that was
already jumping, so the result lurches between registers no matter how careful
the mapping is, and a listener does not hear a tune at all. A reviewer noticed
the lurching from a skim of the mapping code and thought the folding was to
blame; the folding was faithfully reproducing a line that never existed.

So choose the line properly: at each moment, prefer the note that continues
where the melody already was, with a bias towards the upper voice and towards
notes the importance model rates highly. It is the same shape of problem as
mapping pitches to an instrument, and it gets the same treatment: a small
dynamic program over the alternatives rather than a greedy pick.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .events import NoteEvent

#: Beyond this, a leap is a different voice rather than a melodic step.
_LEAP_LIMIT_SEMITONES = 12.0

#: The top-voice preference stops growing past this, so a strongly marked inner
#: voice can still win. Without the cap, being two octaves below the top cost
#: four times as much as being a fifth below, which no amount of emphasis could
#: overcome.
_TOP_VOICE_CAP_SEMITONES = 12.0


@dataclass(frozen=True)
class MelodyCosts:
    """What the line is willing to pay for.

    Defaults chosen so that a stepwise continuation beats jumping to a note a
    fifth higher, while a genuine octave leap in a monophonic line still wins
    when there is nothing else to continue to.
    """

    #: Per semitone of movement from the previous note of the line.
    step: float = 1.0
    #: Extra, per semitone, once a leap is larger than an octave.
    leap: float = 2.0
    #: Reward for taking the top voice of a chord, per semitone below it.
    top_voice: float = 0.55
    #: Reward for notes the importance model rates highly.
    #:
    #: Set above the capped top-voice preference on purpose: when the model is
    #: confident that an inner voice carries the tune, that outranks the
    #: default assumption that the melody sits on top. Within a chord the
    #: scores usually differ by a fraction, so this rarely dominates.
    importance: float = 8.0
    #: Cost of the line falling silent for one moment.
    #:
    #: The melody rests, and the accompaniment does not. A line forced to pick
    #: a note from every moment therefore abandons a resting tune and follows
    #: the unbroken bass instead, which is what happened to a two-handed
    #: fixture here: stepwise nonsense beat the actual melody. Resting has to
    #: be available, and has to cost something, or the line rests everywhere.
    rest: float = 7.0


def select_melody_line(
    groups: Sequence[Sequence[NoteEvent]],
    *,
    importance: Sequence[Sequence[float]] | None = None,
    costs: MelodyCosts | None = None,
    allow_rests: bool = True,
) -> list[int | None]:
    """Pick the melodic note in each simultaneous group, or ``None`` for a rest.

    ``groups`` are notes that sound together, in time order. ``importance``, if
    given, is a matching structure of 0..1 scores. A group returns ``None``
    when the melody is silent through it, so that a resting tune is not
    replaced by whatever else happens to be sounding.
    """
    if not groups:
        return []

    c = costs or MelodyCosts()

    def node_cost(gi: int, ni: int) -> float:
        group = groups[gi]
        note = group[ni]
        top = max(e.pitch_midi for e in group)
        cost = c.top_voice * min(top - note.pitch_midi, _TOP_VOICE_CAP_SEMITONES)
        if importance is not None:
            cost -= c.importance * importance[gi][ni]
        return cost

    def transition_cost(previous_pitch: int, pitch: int) -> float:
        distance = abs(pitch - previous_pitch)
        cost = c.step * distance
        if distance > _LEAP_LIMIT_SEMITONES:
            cost += c.leap * (distance - _LEAP_LIMIT_SEMITONES)
        return cost

    # States per group: one per note, plus a rest. A rest carries the pitch the
    # line was last on, so the melody resumes where it left off instead of
    # continuing from whatever filled the silence.
    rest_state = -1

    def states(gi: int) -> list[int]:
        options = list(range(len(groups[gi])))
        return [*options, rest_state] if allow_rests else options

    best: dict[int, float] = {}
    reference: dict[int, int] = {}
    back: list[dict[int, int]] = []

    for si in states(0):
        if si == rest_state:
            best[si] = c.rest
            reference[si] = max(e.pitch_midi for e in groups[0])
        else:
            best[si] = node_cost(0, si)
            reference[si] = groups[0][si].pitch_midi
    back.append({})

    for gi in range(1, len(groups)):
        row: dict[int, float] = {}
        refs: dict[int, int] = {}
        arg: dict[int, int] = {}
        for si in states(gi):
            here = c.rest if si == rest_state else node_cost(gi, si)
            cheapest = float("inf")
            chosen = rest_state
            for pi, prev_cost in best.items():
                if si == rest_state:
                    step = 0.0
                else:
                    step = transition_cost(reference[pi], groups[gi][si].pitch_midi)
                total = prev_cost + step
                if total < cheapest:
                    cheapest = total
                    chosen = pi
            row[si] = cheapest + here
            arg[si] = chosen
            refs[si] = (
                reference[chosen] if si == rest_state else groups[gi][si].pitch_midi
            )
        best, reference = row, refs
        back.append(arg)

    end = min(best, key=lambda si: best[si])
    path = [end]
    for gi in range(len(groups) - 1, 0, -1):
        path.append(back[gi][path[-1]])
    path.reverse()
    return [None if si == rest_state else si for si in path]

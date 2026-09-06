"""Following one line through polyphony, instead of skimming the top of it."""

from __future__ import annotations

from shawzify_engine.music.events import NoteEvent, group_by_onset
from shawzify_engine.music.melody import select_melody_line


def note(pitch: int, start: float, duration: float = 0.4) -> NoteEvent:
    return NoteEvent(
        pitch_midi=pitch,
        start_seconds=start,
        duration_seconds=duration,
        velocity=0.8,
        confidence=0.9,
    )


def two_hands() -> list[list[NoteEvent]]:
    """A tune over an accompaniment, with the tune resting every other beat.

    This is the shape that broke the old rule. While the melody holds or rests,
    the highest sounding note becomes the accompaniment two octaves below, so
    "take the top note" produces a line that falls two octaves and climbs back
    on every rest.
    """
    groups = []
    tune = [72, 74, 76, 74]
    for i, pitch in enumerate(tune):
        groups.append([note(pitch, i * 1.0), note(48 + (i % 3) * 2, i * 1.0)])
        # The half-beat where the tune is silent and only the bass sounds.
        groups.append([note(50 + (i % 3) * 2, i * 1.0 + 0.5)])
    return groups


def leaps(line: list[NoteEvent]) -> list[int]:
    return [abs(b.pitch_midi - a.pitch_midi) for a, b in zip(line, line[1:])]


def test_the_line_stays_with_the_tune_over_an_accompaniment():
    groups = two_hands()
    choice = select_melody_line(groups)

    # Where the tune is playing, the tune is chosen, not the bass under it.
    chosen_with_tune = [
        groups[gi][ci].pitch_midi
        for gi, ci in enumerate(choice)
        if len(groups[gi]) > 1 and ci is not None
    ]
    assert chosen_with_tune == [72, 74, 76, 74]


def test_the_line_rests_rather_than_following_the_bass():
    """A resting melody must not be replaced by whatever else is sounding."""
    groups = two_hands()
    choice = select_melody_line(groups)

    bass_only = [gi for gi, g in enumerate(groups) if len(g) == 1]
    assert bass_only, "fixture should contain moments where the tune is silent"
    assert all(choice[gi] is None for gi in bass_only)


def test_tracking_leaps_less_than_taking_the_top_note():
    """The measured failure: 55% of steps leapt an octave or more."""
    groups = two_hands()
    top = [max(g, key=lambda e: e.pitch_midi) for g in groups]
    tracked = [
        groups[gi][ci]
        for gi, ci in enumerate(select_melody_line(groups))
        if ci is not None
    ]

    assert max(leaps(top)) > max(leaps(tracked))
    assert sum(leaps(tracked)) < sum(leaps(top))


def test_a_single_voice_is_left_exactly_as_it_is():
    """Nothing to choose between, so nothing should change."""
    events = [note(60 + (i % 5), i * 0.5) for i in range(12)]
    groups = group_by_onset(events, 0.03)
    choice = select_melody_line(groups)
    assert all(ci == 0 for ci in choice), "a single voice has nothing to rest for"
    assert [groups[gi][ci].pitch_midi for gi, ci in enumerate(choice)] == [
        e.pitch_midi for e in events
    ]


def test_importance_can_pull_the_line_off_the_top_voice():
    """A quiet top note over an emphasised inner voice is not the melody."""
    groups = [
        [note(84, 0.0), note(60, 0.0)],
        [note(85, 1.0), note(62, 1.0)],
    ]
    # The upper notes are rated as incidental, the lower ones as the tune.
    scores = [[0.05, 0.95], [0.05, 0.95]]
    choice = select_melody_line(groups, importance=scores)
    assert [groups[gi][ci].pitch_midi for gi, ci in enumerate(choice) if ci is not None] == [
        60,
        62,
    ]


def test_nothing_in_means_nothing_out():
    assert select_melody_line([]) == []

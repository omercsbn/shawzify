"""Pitch arithmetic, note naming and the canonical event model."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from shawzify_engine.music.events import (
    NoteEvent,
    NoteSequence,
    clamp_durations,
    group_by_onset,
    merge_overlapping_same_pitch,
    sort_events,
)
from shawzify_engine.music.pitch import (
    hz_to_midi,
    interval_class,
    midi_to_hz,
    note_name,
    octave_equivalents,
    parse_note_name,
    pitch_class,
    transpose,
)

MIDI = st.integers(min_value=0, max_value=127)


def test_middle_c_naming():
    assert note_name(60) == "C4"
    assert note_name(69) == "A4"
    assert note_name(48) == "C3"
    assert note_name(21) == "A0"
    assert note_name(61, flats=True) == "Db4"


def test_a440_reference():
    assert midi_to_hz(69) == pytest.approx(440.0)
    assert hz_to_midi(440.0) == pytest.approx(69.0)
    assert midi_to_hz(60) == pytest.approx(261.6256, abs=1e-3)


@given(MIDI)
def test_hz_midi_round_trip(m):
    assert hz_to_midi(midi_to_hz(m)) == pytest.approx(m, abs=1e-6)


@given(MIDI)
def test_transpose_octave_preserves_pitch_class(m):
    """Property: shifting by 12 never changes the pitch class."""
    assert pitch_class(transpose(m, 12)) == pitch_class(m)
    assert pitch_class(transpose(m, -12)) == pitch_class(m)
    assert pitch_class(transpose(m, 24)) == pitch_class(m)


@given(MIDI, st.integers(min_value=-24, max_value=24))
def test_transpose_is_additive(m, semitones):
    assert transpose(m, semitones) == m + semitones


@given(st.sampled_from(["C4", "F#3", "Bb5", "A0", "G#-1", "Eb2"]))
def test_parse_note_name_round_trip(name):
    midi = parse_note_name(name)
    assert parse_note_name(note_name(midi)) == midi


def test_parse_note_name_rejects_nonsense():
    for bad in ("", "H4", "C", "C#x"):
        with pytest.raises(ValueError):
            parse_note_name(bad)


def test_interval_class_is_symmetric_and_bounded():
    assert interval_class(60, 67) == 5
    assert interval_class(67, 60) == 5
    assert interval_class(60, 66) == 6
    assert interval_class(60, 72) == 0


@given(MIDI, st.integers(min_value=0, max_value=60), st.integers(min_value=61, max_value=127))
def test_octave_equivalents_share_pitch_class_and_stay_in_range(m, lo, hi):
    """Property: every equivalent is in range and has the same pitch class."""
    for cand in octave_equivalents(m, lo, hi):
        assert lo <= cand <= hi
        assert pitch_class(cand) == pitch_class(m)


def test_sort_events_is_stable_and_total():
    events = [
        NoteEvent(64, 1.0, 0.5),
        NoteEvent(60, 1.0, 0.5),
        NoteEvent(62, 0.0, 0.5),
    ]
    ordered = sort_events(events)
    assert [e.pitch_midi for e in ordered] == [62, 60, 64]
    # Property: sorting an already-sorted list is a no-op.
    assert sort_events(ordered) == ordered


def test_group_by_onset_keeps_rolled_chords_together():
    events = [
        NoteEvent(60, 0.000, 1.0),
        NoteEvent(64, 0.010, 1.0),
        NoteEvent(67, 0.025, 1.0),
        NoteEvent(72, 0.500, 1.0),
    ]
    groups = group_by_onset(events, 0.03)
    assert len(groups) == 2
    assert len(groups[0]) == 3
    assert len(groups[1]) == 1


def test_group_by_onset_does_not_chain_past_tolerance():
    """A run of closely spaced notes must not merge into one giant group."""
    events = [NoteEvent(60 + i, i * 0.025, 0.1) for i in range(10)]
    groups = group_by_onset(events, 0.03)
    assert len(groups) > 1
    for g in groups:
        span = max(e.start_seconds for e in g) - min(e.start_seconds for e in g)
        assert span <= 0.03 + 1e-9


def test_merge_overlapping_same_pitch():
    events = [
        NoteEvent(60, 0.0, 0.5),
        NoteEvent(60, 0.505, 0.5),  # continuation fragment
        NoteEvent(60, 3.0, 0.5),    # separate note
    ]
    merged = merge_overlapping_same_pitch(events, gap=0.02)
    assert len(merged) == 2
    assert merged[0].duration_seconds == pytest.approx(1.005)


def test_clamp_durations_bounds():
    events = [NoteEvent(60, 0.0, 0.001), NoteEvent(62, 1.0, 100.0)]
    out = clamp_durations(events, minimum=0.03, maximum=8.0)
    assert out[0].duration_seconds == 0.03
    assert out[1].duration_seconds == 8.0


def test_note_sequence_statistics(chord_progression):
    seq = NoteSequence(chord_progression)
    assert len(seq) == 12
    assert seq.max_polyphony() == 3
    assert seq.mean_polyphony() == pytest.approx(3.0)
    assert seq.pitch_range == (60, 74)


def test_note_event_serialisation_round_trip():
    ev = NoteEvent(64, 1.25, 0.5, 0.7, 0.9, "test", voice=2)
    assert NoteEvent.from_dict(ev.to_dict()) == ev

"""Removing what the transcriber invented, without removing what it heard."""

from __future__ import annotations

from shawzify_engine.music.cleanup import TICK_SECONDS, clean_transcription
from shawzify_engine.music.events import NoteEvent


def line(count: int = 40, pitch: int = 60, confidence: float = 0.8) -> list[NoteEvent]:
    """A plain melody: one note every half second, all in one register."""
    return [
        NoteEvent(
            pitch_midi=pitch + (i % 5),
            start_seconds=i * 0.5,
            duration_seconds=0.4,
            velocity=0.7,
            confidence=confidence,
        )
        for i in range(count)
    ]


def test_an_uncertain_note_far_outside_the_music_is_dropped():
    """The failure this exists for: a handful of ghosts decide the register.

    Range fit, transposition and octave folding all read the extremes of the
    note set. On a real track, 135 invented notes out of 4829 stretched the
    apparent range by two octaves and took pitch accuracy from 56% to 4.6%.
    """
    events = line()
    ghost = NoteEvent(
        pitch_midi=100,  # three octaves above everything else
        start_seconds=3.0,
        duration_seconds=0.3,
        velocity=0.4,
        confidence=0.2,
    )
    cleaned, report = clean_transcription([*events, ghost])

    assert report.outliers_removed == 1
    assert all(e.pitch_midi < 90 for e in cleaned)


def test_a_confident_note_outside_the_range_is_kept():
    """A piccolo really does play up there. Doubt is what makes an outlier."""
    events = line()
    real = NoteEvent(
        pitch_midi=100,
        start_seconds=3.0,
        duration_seconds=0.4,
        velocity=0.9,
        confidence=0.95,
    )
    cleaned, report = clean_transcription([*events, real])

    assert report.outliers_removed == 0
    assert any(e.pitch_midi == 100 for e in cleaned)


def test_a_fragment_joins_the_note_it_belongs_to():
    """A wavering vocal becomes one note, not a stutter or a silence."""
    held = NoteEvent(60, 1.0, 0.30, 0.8, 0.9)
    wobble = NoteEvent(60, 1.34, 0.02, 0.6, 0.7)  # far shorter than a tick
    cleaned, report = clean_transcription([*line(), held, wobble])

    assert report.fragments_merged == 1
    survivor = next(e for e in cleaned if e.start_seconds == 1.0 and e.pitch_midi == 60)
    assert survivor.duration_seconds > 0.3


def test_an_isolated_unplayable_fragment_is_dropped():
    orphan = NoteEvent(75, 100.0, TICK_SECONDS / 4, 0.5, 0.8)
    cleaned, report = clean_transcription([*line(), orphan])

    assert report.fragments_removed == 1
    assert all(e.duration_seconds >= TICK_SECONDS for e in cleaned)


def test_a_short_excerpt_is_left_alone():
    """Too few notes to reason about a distribution, so do not guess."""
    events = line(count=8)
    cleaned, report = clean_transcription(events)

    assert cleaned == events
    assert report.removed == 0


def test_nothing_is_reported_when_nothing_happened():
    _, report = clean_transcription(line())
    assert report.summary() is None


def test_the_report_says_what_it_did():
    ghost = NoteEvent(100, 3.0, 0.3, 0.4, 0.1)
    _, report = clean_transcription([*line(), ghost])
    summary = report.summary()
    assert summary and "1 uncertain" in summary


def test_midi_precision_is_not_disturbed_by_cleanup(midi_file, twinkle):
    """MIDI is exact: its extremes are the composer's, not an artefact."""
    from shawzify_engine.pipeline import load_source

    source = load_source(midi_file(twinkle))
    assert len(source.events) == len(twinkle)
    assert not any("Cleaned up" in w for w in source.warnings)

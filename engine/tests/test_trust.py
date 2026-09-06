"""Saying what the compatibility score does and does not know."""

from __future__ import annotations

from shawzify_engine.music.events import NoteEvent
from shawzify_engine.music.trust import assess_transcription


def notes(count: int, *, confidence: float = 0.5, spacing: float = 0.5) -> list[NoteEvent]:
    return [
        NoteEvent(
            pitch_midi=60 + (i % 7),
            start_seconds=i * spacing,
            duration_seconds=0.3,
            velocity=0.7,
            confidence=confidence,
        )
        for i in range(count)
    ]


def test_midi_needs_no_caveat():
    """A MIDI file is the notes. There is nothing to be unsure about."""
    trust = assess_transcription(notes(20), 10.0, kind="midi")
    assert trust.label == "exact"
    assert trust.note() is None


def test_audio_always_says_what_the_score_covers():
    """The sentence that was missing: a high score is about the arrangement.

    BFG Division transcribed to 1.6 notes per second, arranged to 88%, and
    sounded nothing like the track. The score was not wrong; it was answering a
    different question than the one being read off it.
    """
    trust = assess_transcription(notes(40), 20.0)
    assert trust.label == "good"
    note = trust.note()
    assert note and "cannot hear the recording" in note


def test_an_empty_transcription_says_so_plainly():
    trust = assess_transcription(notes(2), 60.0)
    assert trust.label == "empty"
    assert "Almost nothing pitched" in (trust.note() or "")


def test_nothing_at_all_is_empty_rather_than_a_crash():
    trust = assess_transcription([], 30.0)
    assert trust.label == "empty"
    assert trust.confidence == 0.0


def test_deep_uncertainty_is_reported():
    trust = assess_transcription(notes(40, confidence=0.15), 20.0)
    assert trust.label == "uncertain"
    assert "unsure" in (trust.note() or "")


def test_the_normal_confidence_band_is_not_treated_as_a_failure():
    """Basic Pitch sits near 0.5 whether the result is good or unrecognisable.

    Four very different tracks measured between 0.46 and 0.52, so a threshold
    inside that band would fire at random. This pins the decision not to.
    """
    for confidence in (0.46, 0.50, 0.52):
        assert assess_transcription(notes(40, confidence=confidence), 20.0).label == "good"


def test_a_thin_but_not_empty_transcription_is_not_flagged():
    """The BFG Division case, locked in as documented rather than claimed.

    1.8 notes per second over a track whose riff runs at eight to sixteen is a
    failed transcription, and this module cannot tell it from an honest sparse
    ballad. Three detectors were tried; the docstring records all three. This
    test exists so the docstring cannot quietly become untrue: if someone raises
    the threshold to catch this track, they have to come here and argue for it.
    """
    events = [
        NoteEvent(pitch_midi=52 + (i % 4), start_seconds=i * 0.55,
                  duration_seconds=0.3, velocity=0.8, confidence=0.5)
        for i in range(180)
    ]
    trust = assess_transcription(events, 100.0, kind="audio")

    assert trust.notes_per_second > 1.5
    assert trust.label == "good"
    note = trust.note()
    assert note and "cannot hear the recording" in note

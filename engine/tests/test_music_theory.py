"""Quantization, phrasing, importance and key estimation."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from shawzify_engine.music.events import NoteEvent
from shawzify_engine.music.importance import (
    ImportanceWeights,
    compute_importance,
    melody_line,
)
from shawzify_engine.music.key import estimate_key, pitch_class_histogram
from shawzify_engine.music.phrases import detect_phrases, phrase_position
from shawzify_engine.music.quantize import (
    choose_grid,
    grid_alignment_score,
    grid_seconds,
    quantize_events,
    snap_to_ticks,
)

# -- quantization --------------------------------------------------------


def test_grid_seconds_matches_tempo():
    assert grid_seconds(120.0, "1/4") == pytest.approx(0.5)
    assert grid_seconds(120.0, "1/8") == pytest.approx(0.25)
    assert grid_seconds(120.0, "1/8t") == pytest.approx(1 / 6)
    assert grid_seconds(60.0, "1/16") == pytest.approx(0.25)


def test_perfectly_aligned_onsets_score_one():
    events = [NoteEvent(60, i * 0.25, 0.2) for i in range(16)]
    assert grid_alignment_score(events, 120.0, "1/8", 0.0) == pytest.approx(1.0)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.lists(st.floats(min_value=0.0, max_value=20.0), min_size=4, max_size=40),
    st.sampled_from(["1/4", "1/8", "1/16"]),
)
def test_full_strength_quantization_lands_on_the_grid(times, grid):
    """Property: at strength 1.0 every onset sits exactly on a grid point."""
    events = [NoteEvent(60, t, 0.2) for t in times]
    out = quantize_events(events, 120.0, grid, strength=1.0, origin=0.0)
    step = grid_seconds(120.0, grid)
    for ev in out:
        assert abs(ev.start_seconds / step - round(ev.start_seconds / step)) < 1e-6


def test_zero_strength_quantization_is_a_no_op():
    events = [NoteEvent(60, 0.13, 0.2), NoteEvent(62, 0.41, 0.2)]
    out = quantize_events(events, 120.0, "1/8", strength=0.0)
    assert [e.start_seconds for e in out] == [0.13, 0.41]


def test_partial_strength_moves_partway():
    events = [NoteEvent(60, 0.30, 0.2)]
    out = quantize_events(events, 120.0, "1/4", strength=0.5, origin=0.0)
    # Nearest 1/4 grid point at 120 BPM is 0.5; halfway is 0.4.
    assert out[0].start_seconds == pytest.approx(0.4)


def test_quantization_preserves_count_and_order():
    events = [NoteEvent(60 + i, i * 0.17, 0.1) for i in range(20)]
    out = quantize_events(events, 128.0, "1/16", strength=0.9)
    assert len(out) == len(events)
    starts = [e.start_seconds for e in out]
    assert starts == sorted(starts)


def test_choose_grid_finds_eighths():
    events = [NoteEvent(60, i * 0.25, 0.2) for i in range(24)]
    grid, score, _origin = choose_grid(events, 120.0, ticks_per_second=16)
    assert grid == "1/8"
    assert score > 0.95


def test_choose_grid_finds_triplets():
    step = (60.0 / 120.0) / 3.0
    events = [NoteEvent(60, i * step, 0.1) for i in range(24)]
    grid, score, _origin = choose_grid(events, 120.0, ticks_per_second=16)
    assert grid in ("1/8t", "1/16t")
    assert score > 0.9


def test_choose_grid_never_goes_finer_than_the_tick_grid():
    """A grid step under ~1.5 ticks cannot survive encoding, so it is excluded."""
    events = [NoteEvent(60, i * 0.03, 0.02) for i in range(40)]
    grid, _score, _origin = choose_grid(events, 200.0, ticks_per_second=16)
    assert grid_seconds(200.0, grid) >= 1.5 / 16.0


def test_choose_grid_avoids_collapsing_distinct_onsets():
    """A grid that merges two different onsets has destroyed information."""
    events = [NoteEvent(60, i * 0.25, 0.2) for i in range(16)]
    grid, _score, origin = choose_grid(events, 120.0, ticks_per_second=16)
    step = grid_seconds(120.0, grid)
    slots = {round((e.start_seconds - origin) / step) for e in events}
    assert len(slots) == len(events)


def test_snap_to_ticks_spaces_repeated_notes():
    events = [NoteEvent(60, i * 0.02, 0.01) for i in range(5)]
    snapped = snap_to_ticks(events, 16, min_gap_ticks=1)
    ticks = [t for t, _ in snapped]
    assert ticks == sorted(ticks)
    assert len(set(ticks)) == len(ticks)


# -- phrases -------------------------------------------------------------


def test_detect_phrases_splits_on_long_rests():
    events = (
        [NoteEvent(60 + i, i * 0.25, 0.2) for i in range(8)]
        + [NoteEvent(60 + i, 4.0 + i * 0.25, 0.2) for i in range(8)]
    )
    phrases = detect_phrases(events, bpm=120.0)
    assert len(phrases) == 2
    assert phrases[0].start_seconds == pytest.approx(0.0)
    assert phrases[1].start_seconds == pytest.approx(4.0)


def test_detect_phrases_does_not_split_a_continuous_line():
    events = [NoteEvent(60 + (i % 5), i * 0.25, 0.2) for i in range(32)]
    assert len(detect_phrases(events, bpm=120.0)) == 1


def test_every_event_belongs_to_exactly_one_phrase():
    events = [NoteEvent(60 + (i % 6), i * 0.3 + (3.0 if i > 10 else 0.0), 0.2) for i in range(24)]
    phrases = detect_phrases(events, bpm=100.0)
    seen: set[int] = set()
    for p in phrases:
        assert not (seen & set(p.event_indices))
        seen.update(p.event_indices)
    assert seen == set(range(len(events)))


def test_phrase_position_runs_zero_to_one():
    events = [NoteEvent(60, i * 0.25, 0.2) for i in range(8)]
    phrases = detect_phrases(events, bpm=120.0)
    assert phrase_position(phrases, 0) == pytest.approx(0.0)
    assert phrase_position(phrases, 7) == pytest.approx(1.0)


# -- importance ----------------------------------------------------------


def test_importance_is_bounded(twinkle):
    for f in compute_importance(twinkle, bpm=120.0):
        assert 0.0 <= f.total <= 1.0


def test_melody_beats_inner_voice():
    """The top note of a chord must outrank the note buried inside it."""
    events = [
        NoteEvent(60, 0.0, 1.0, velocity=0.6),
        NoteEvent(64, 0.0, 1.0, velocity=0.6),
        NoteEvent(72, 0.0, 1.0, velocity=0.9),
    ]
    factors = compute_importance(events, bpm=120.0)
    assert factors[2].total > factors[1].total


def test_louder_note_outranks_quieter_identical_note():
    events = [NoteEvent(60, 0.0, 0.5, velocity=0.2), NoteEvent(60, 2.0, 0.5, velocity=1.0)]
    factors = compute_importance(events, bpm=120.0)
    assert factors[1].velocity > factors[0].velocity


def test_low_confidence_note_scores_lower():
    events = [
        NoteEvent(60, 0.0, 0.5, velocity=0.8, confidence=0.2),
        NoteEvent(60, 2.0, 0.5, velocity=0.8, confidence=1.0),
    ]
    factors = compute_importance(events, bpm=120.0)
    assert factors[1].total > factors[0].total


def test_weights_are_normalised():
    w = ImportanceWeights(confidence=2.0, velocity=2.0).normalized()
    assert sum(w.to_dict().values()) == pytest.approx(1.0)


def test_melody_line_picks_one_note_per_moment(chord_progression):
    line = melody_line(chord_progression, bpm=60.0)
    assert len(line) == 4
    assert [n.pitch_midi for n in line] == [67, 72, 74, 67]


# -- key estimation ------------------------------------------------------


def test_c_major_scale_is_detected_as_c_major(c_major_scale):
    key = estimate_key(c_major_scale)
    assert key.tonic_pitch_class == 0
    assert key.mode == "major"
    assert key.confidence > 0.3


def test_a_minor_triads_are_detected_as_minor():
    events = []
    for i, root in enumerate([57, 62, 64, 57]):
        for off in (0, 3, 7):
            events.append(NoteEvent(root + off, i * 1.0, 0.9))
    key = estimate_key(events)
    assert key.mode == "minor"


def test_key_confidence_is_low_for_a_chromatic_run(chromatic_scale):
    key = estimate_key(chromatic_scale)
    assert key.confidence < 0.5


def test_histogram_weights_by_duration():
    events = [NoteEvent(60, 0.0, 4.0), NoteEvent(62, 4.0, 0.1)]
    hist = pitch_class_histogram(events)
    assert hist[0] > hist[2]


def test_empty_input_gives_zero_confidence():
    assert estimate_key([]).confidence == 0.0

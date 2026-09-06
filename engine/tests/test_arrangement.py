"""The arrangement engine, exercised against the golden musical fixtures.

Assertions are about *musical outcomes* and *invariants*, not about specific
tuning constants -- the weights are meant to be tunable without breaking tests.
"""

from __future__ import annotations

import pytest

from shawzify_engine.arrangement.arranger import arrange_for_shawzin
from shawzify_engine.arrangement.decisions import Operation
from shawzify_engine.arrangement.density import measure_density, reduce_density
from shawzify_engine.arrangement.mapping import candidates_for, map_melody
from shawzify_engine.arrangement.options import (
    AUTO,
    ArrangementMode,
    ArrangementOptions,
)
from shawzify_engine.arrangement.polyphony import (
    best_chord_position,
    estimate_root,
    rank_notes,
)
from shawzify_engine.arrangement.scale_optimizer import find_best_shawzin_mapping
from shawzify_engine.music.events import NoteEvent
from shawzify_engine.music.importance import compute_importance
from shawzify_engine.music.pitch import pitch_class
from shawzify_engine.shawzin.songcode import decode, validate_events

# -- the universal invariant --------------------------------------------


def assert_playable(arrangement):
    """Every generated event must satisfy the instrument model. No exceptions."""
    inst = arrangement.instrument
    scale = arrangement.scale
    song = arrangement.song

    validate_events(song.events, inst, offset=song.events[0].tick if song.events else 0)

    valid_single = {n.position for n in scale.notes}
    valid_chord = {c.position for c in scale.chords}
    for ev in song.events:
        assert ev.string, "event with no string"
        assert set(ev.string) <= {"1", "2", "3"}
        assert ev.fret in ("0", "1", "2", "3", "12", "13", "23", "123")
        assert 0 <= ev.tick <= inst.format.max_ticks
        for ch in ev.string:
            position = ev.fret + "-" + ch
            assert position in (valid_chord if ev.is_chord_fret else valid_single)

    ticks = [e.tick for e in song.events]
    assert ticks == sorted(ticks), "events must stay time-ordered"

    # Everything the arrangement outputs must be a pitch the scale can produce.
    playable = set(scale.playable_midi)
    for chord in scale.chords:
        playable.update(chord.midi)
    for note in arrangement.output_notes():
        assert note.pitch_midi in playable

    # And the code must encode without complaint.
    code = arrangement.to_code()
    if song.events:
        assert code
        decode(code, inst)


@pytest.mark.parametrize("mode", list(ArrangementMode))
def test_every_mode_produces_playable_output(mode, twinkle):
    a = arrange_for_shawzin(twinkle, options=ArrangementOptions(mode=mode), bpm=120.0)
    assert_playable(a)
    assert a.song.events


def test_all_golden_fixtures_are_playable(
    c_major_scale, chromatic_scale, twinkle, chord_progression,
    dense_chord, out_of_range_melody, fast_repeats,
):
    for fixture in (
        c_major_scale, chromatic_scale, twinkle, chord_progression,
        dense_chord, out_of_range_melody, fast_repeats,
    ):
        for mode in ArrangementMode:
            a = arrange_for_shawzin(fixture, options=ArrangementOptions(mode=mode), bpm=120.0)
            assert_playable(a)


def test_empty_input_is_handled():
    a = arrange_for_shawzin([])
    assert a.song.events == []
    assert a.to_code() == ""


# -- determinism ---------------------------------------------------------


def test_arrangement_is_deterministic(twinkle):
    """Same notes, same options, same engine version -> identical output."""
    opts = ArrangementOptions(mode=ArrangementMode.BALANCED)
    first = arrange_for_shawzin(twinkle, options=opts, bpm=120.0)
    second = arrange_for_shawzin(twinkle, options=opts, bpm=120.0)
    assert first.to_code() == second.to_code()
    assert first.report.scale_id == second.report.scale_id
    assert first.report.transpose == second.report.transpose
    assert [d.to_dict() for d in first.decisions] == [d.to_dict() for d in second.decisions]


# -- scale optimisation --------------------------------------------------


def _interval_error(arrangement) -> float:
    """Mean distance, in semitones, between each melodic step and the original.

    Matched through the decision records, which say which source note each
    played note came from; matching by position drifts apart at the first
    removed note.
    """
    kept = [
        d
        for d in sorted(arrangement.decisions, key=lambda d: d.source_index)
        if d.output_midi is not None
    ]
    if len(kept) < 2:
        return 0.0
    error = sum(
        abs((b.original.pitch_midi - a.original.pitch_midi) - (b.output_midi - a.output_midi))
        for a, b in zip(kept, kept[1:])
    )
    return error / (len(kept) - 1)


def test_c_major_melody_prefers_a_diatonic_scale(instrument, c_major_scale):
    a = arrange_for_shawzin(c_major_scale, instrument, bpm=120.0)
    # C major maps perfectly onto the Major scale (or Minor, its relative).
    assert a.report.scale_id in ("maj", "min")
    # And it comes out as the same tune: every step the same size as before.
    assert _interval_error(a) == 0.0


def test_chromatic_melody_prefers_the_chromatic_scale(instrument, chromatic_scale):
    a = arrange_for_shawzin(chromatic_scale, instrument, bpm=120.0)
    assert a.report.scale_id == "chrom"


def test_transposing_beats_folding_a_tune_that_would_not_fit(instrument, c_major_scale):
    """Given the choice, move the whole tune rather than break its shape.

    This used to assert the opposite: that the transposition stays a whole
    number of octaves so the key is preserved. Measuring real tracks showed
    what that costs. Keeping the key and folding what does not fit leaves every
    pitch class right and every leap wrong, which is precisely the case where
    people say the notes are correct but the song is unrecognisable. A
    transposed tune is still the tune; a folded one is not.
    """
    a = arrange_for_shawzin(c_major_scale, instrument, bpm=120.0)
    folded = [d for d in a.decisions if any("fold" in str(op) for op in d.operations)]
    assert folded == []
    assert _interval_error(a) == 0.0


def test_pinned_scale_is_honoured(instrument, twinkle):
    a = arrange_for_shawzin(
        twinkle, instrument, ArrangementOptions(scale="pmin"), bpm=120.0
    )
    assert a.report.scale_id == "pmin"
    assert_playable(a)


def test_pinned_transpose_is_honoured(instrument, twinkle):
    a = arrange_for_shawzin(
        twinkle, instrument, ArrangementOptions(transpose=-12), bpm=120.0
    )
    assert a.report.transpose == -12


def test_scale_candidates_are_ranked_and_distinct(instrument, twinkle):
    factors = compute_importance(twinkle, bpm=120.0)
    candidates = find_best_shawzin_mapping(
        twinkle, instrument, ArrangementOptions(), importance=factors, top_n=5
    )
    assert len(candidates) >= 3
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert len({c.scale_id for c in candidates}) == len(candidates)


# -- octave folding and contour -----------------------------------------


def test_out_of_range_notes_are_folded_not_clamped(instrument, out_of_range_melody):
    """A melody spanning C2-C7 must keep its shape, not flatten onto the top note."""
    a = arrange_for_shawzin(out_of_range_melody, instrument, bpm=120.0)
    assert_playable(a)
    kept = [d for d in a.decisions if not d.removed and d.output_midi is not None]
    assert kept
    outputs = [d.output_midi for d in kept]
    assert len(set(outputs)) > 3, "folding collapsed the melody onto too few pitches"
    assert any(Operation.OCTAVE_FOLD in d.operations for d in kept)


def test_octave_folding_preserves_pitch_class(instrument, out_of_range_melody):
    a = arrange_for_shawzin(out_of_range_melody, instrument, bpm=120.0)
    for d in a.decisions:
        if d.removed or d.output_midi is None:
            continue
        if Operation.OCTAVE_FOLD in d.operations and Operation.SIMPLIFY not in d.operations:
            expected = d.original.pitch_midi + a.report.transpose
            assert pitch_class(d.output_midi) == pitch_class(expected)


def test_dp_mapping_beats_independent_nearest_note(instrument):
    """A rising line that leaves the range should keep rising, not zig-zag."""
    scale = instrument.scale("maj")
    pitches = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76]
    mapped = [c.midi for c in map_melody(pitches, scale)]
    ups = sum(1 for a, b in zip(mapped, mapped[1:]) if b > a)
    assert ups >= len(mapped) - 3, "the DP path broke the ascending contour"


def test_candidates_include_every_octave_in_range(instrument):
    scale = instrument.scale("pmin")  # C at 48, 60 and 72
    cands = candidates_for(60, scale)
    midis = sorted(c.midi for c in cands if c.exact_pitch_class)
    assert 48 in midis and 60 in midis and 72 in midis


# -- polyphony -----------------------------------------------------------


def test_simultaneous_notes_always_share_one_fret(instrument, chord_progression):
    """The core physical constraint, verified on output rather than assumed."""
    a = arrange_for_shawzin(chord_progression, instrument, bpm=60.0)
    by_tick: dict[int, set[str]] = {}
    for ev in a.song.events:
        by_tick.setdefault(ev.tick, set()).add(ev.fret)
    for frets in by_tick.values():
        assert len(frets) == 1


def test_dense_chord_is_reduced_not_dropped(instrument, dense_chord):
    a = arrange_for_shawzin(dense_chord, instrument, bpm=60.0)
    assert_playable(a)
    assert a.song.events, "a seven-note stack should still produce something"
    assert a.song.note_count <= 3 * len(a.song.events)


def test_chordal_mode_uses_chord_positions(instrument, chord_progression):
    a = arrange_for_shawzin(
        chord_progression, instrument,
        ArrangementOptions(mode=ArrangementMode.CHORDAL), bpm=60.0,
    )
    assert any(ev.is_chord_fret for ev in a.song.events)


def test_melody_mode_is_monophonic(instrument, chord_progression):
    a = arrange_for_shawzin(
        chord_progression, instrument,
        ArrangementOptions(mode=ArrangementMode.MELODY), bpm=60.0,
    )
    for ev in a.song.events:
        assert len(ev.string) == 1


def test_modes_produce_increasing_note_counts(instrument, chord_progression):
    counts = {}
    for mode in (ArrangementMode.MELODY, ArrangementMode.BALANCED, ArrangementMode.CHORDAL):
        a = arrange_for_shawzin(
            chord_progression, instrument, ArrangementOptions(mode=mode), bpm=60.0
        )
        counts[mode] = a.report.metrics.output_notes
    assert counts[ArrangementMode.MELODY] < counts[ArrangementMode.CHORDAL]


def test_estimate_root_finds_the_chord_root():
    assert estimate_root([60, 64, 67]) == 0    # C major
    assert estimate_root([57, 60, 64]) == 9    # A minor
    assert estimate_root([62, 65, 69]) == 2    # D minor


def test_rank_notes_keeps_root_and_third_before_fifth():
    events = [
        NoteEvent(60, 0.0, 1.0),  # root
        NoteEvent(64, 0.0, 1.0),  # third
        NoteEvent(67, 0.0, 1.0),  # fifth
        NoteEvent(72, 0.0, 1.0),  # melody / octave
    ]
    importance = [0.5, 0.5, 0.5, 0.9]
    order = rank_notes(events, [0, 1, 2, 3], lead_index=3, importance=importance)
    assert order[0] == 3          # the lead always survives
    assert order.index(2) > order.index(0)  # the fifth goes before the root


def test_best_chord_position_matches_a_c_major_triad(instrument):
    scale = instrument.scale("maj")
    found = best_chord_position(scale, [60, 64, 67])
    assert found is not None
    chord, quality = found
    assert quality > 0.6
    assert 0 in {pitch_class(m) for m in chord.midi}


# -- density and repeats -------------------------------------------------


def test_density_reduction_respects_the_budget():
    events = [NoteEvent(60 + (i % 5), i * 0.05, 0.04) for i in range(60)]
    importance = [0.5 + 0.005 * i for i in range(60)]
    result = reduce_density(events, importance, max_notes_per_second=6.0, window=1.0)
    kept = [events[i] for i in result.kept]
    assert measure_density(kept, 1.0) <= 7.0
    assert result.removed


def test_density_reduction_protects_the_melody():
    events = [NoteEvent(60 + (i % 4), i * 0.05, 0.04) for i in range(40)]
    importance = [0.2] * 40
    protect = [0, 10, 20, 30]
    result = reduce_density(
        events, importance, max_notes_per_second=4.0, protect_indices=protect
    )
    for i in protect:
        assert i in result.kept


def test_fast_repeats_are_thinned_and_spaced(instrument, fast_repeats):
    """16 notes/second cannot survive a 16 ticks/second grid intact."""
    a = arrange_for_shawzin(fast_repeats, instrument, bpm=120.0)
    assert_playable(a)
    ticks = [e.tick for e in a.song.events]
    assert len(ticks) == len(set(ticks)), "two plucks landed on one tick"
    assert a.report.metrics.removed_notes > 0


def test_complexity_controls_how_much_survives(instrument):
    events = [NoteEvent(60 + (i % 7), i * 0.06, 0.05) for i in range(80)]
    low = arrange_for_shawzin(
        events, instrument, ArrangementOptions(complexity=0.05), bpm=120.0
    )
    high = arrange_for_shawzin(
        events, instrument, ArrangementOptions(complexity=1.0), bpm=120.0
    )
    assert high.report.metrics.output_notes > low.report.metrics.output_notes


# -- reporting -----------------------------------------------------------


def test_compatibility_improves_over_the_original(instrument, out_of_range_melody):
    a = arrange_for_shawzin(out_of_range_melody, instrument, bpm=120.0)
    assert a.report.compatibility_after.overall > a.report.compatibility_before.overall


def test_compatibility_is_not_just_playable_over_total(instrument):
    """A perfectly in-range melody that is butchered must not score 100%."""
    good = [NoteEvent(48 + i, i * 0.5, 0.4) for i in range(12)]
    a = arrange_for_shawzin(good, instrument, ArrangementOptions(scale="chrom", transpose=0), bpm=120.0)
    assert a.report.compatibility_after.overall > 0.9
    crowded = [NoteEvent(48 + (i % 12), i * 0.02, 0.02) for i in range(120)]
    b = arrange_for_shawzin(crowded, instrument, ArrangementOptions(scale="chrom", transpose=0), bpm=120.0)
    assert b.report.compatibility_after.overall < a.report.compatibility_after.overall


def test_every_decision_has_a_reason(instrument, chord_progression):
    a = arrange_for_shawzin(chord_progression, instrument, bpm=60.0)
    for d in a.decisions:
        assert d.operations, "a decision with no recorded operation"
        assert d.reason, "a decision with no explanation"


def test_report_metrics_are_consistent(instrument, twinkle):
    a = arrange_for_shawzin(twinkle, instrument, bpm=120.0)
    m = a.report.metrics
    assert m.source_notes == len(twinkle)
    assert m.output_notes + m.removed_notes == m.source_notes
    assert 0.0 <= m.melody_retention <= 1.0


def test_warnings_are_actionable(instrument, out_of_range_melody):
    a = arrange_for_shawzin(out_of_range_melody, instrument, bpm=120.0)
    assert a.report.warnings
    for w in a.report.warnings:
        assert w.endswith(".") or w.endswith(")")
        assert len(w) > 20


# -- options -------------------------------------------------------------


def test_options_round_trip_through_dict():
    opts = ArrangementOptions(
        mode=ArrangementMode.VIRTUOSO, scale="hex", transpose=-3,
        quantization="1/16", complexity=0.3, max_density=12.0,
    )
    back = ArrangementOptions.from_dict(opts.to_dict())
    assert back == opts


def test_auto_options_round_trip():
    opts = ArrangementOptions()
    back = ArrangementOptions.from_dict(opts.to_dict())
    assert back.scale is AUTO
    assert back.transpose is AUTO
    assert back.quantization is AUTO


def test_quantization_off_leaves_timing_alone(instrument, twinkle):
    a = arrange_for_shawzin(
        twinkle, instrument, ArrangementOptions(quantization="off"), bpm=120.0
    )
    assert a.resolved.quantization == "off"
    for d in a.decisions:
        assert Operation.QUANTIZE not in d.operations


def test_shawzin_variant_changes_the_constraint(instrument, chord_progression):
    """The monophonic Corbu cannot produce a two-string event."""
    a = arrange_for_shawzin(
        chord_progression, instrument,
        ArrangementOptions(mode=ArrangementMode.CHORDAL, shawzin_variant="corbu"),
        bpm=60.0,
    )
    assert_playable(a)
    for ev in a.song.events:
        assert len(ev.string) == 1


def test_range_beats_pitch_classes_when_the_tune_is_wide(instrument):
    """A tune wider than the scale should not be squeezed into the chromatic one.

    Chromatic has every pitch class and less than one octave of range. The
    search used to take it for exactly that reason, because coverage counted an
    octave-folded note as a perfect hit. Measured on a real vocal line, that
    left every leap 3.46 semitones out against 1.57 for a scale with room, and
    listeners could not recognise the song. Range is not a tie-breaker here.
    """
    from shawzify_engine.music.events import NoteEvent

    # Two and a half octaves of a plain minor line, well past chromatic's reach.
    pitches = [57, 60, 64, 67, 72, 76, 79, 76, 72, 67, 64, 60, 57]
    events = [
        NoteEvent(
            pitch_midi=p,
            start_seconds=i * 0.4,
            duration_seconds=0.35,
            velocity=0.8,
            confidence=1.0,
        )
        for i, p in enumerate(pitches)
    ]

    a = arrange_for_shawzin(events, instrument, bpm=120.0)
    scale = instrument.scale(a.report.scale_id)
    span = scale.playable_midi[-1] - scale.playable_midi[0]

    assert a.report.scale_id != "chrom"
    assert span >= 18, "chose a scale too narrow to hold the melody"
    assert _interval_error(a) < 2.0


def test_scoring_weights_cannot_saturate(instrument, c_major_scale):
    """Every candidate scoring 1.0 is not a decision, it is a coin toss.

    The caller normalises its own weights, so a term added to the scorer later
    fell outside that sum, pushed good candidates past 1.0, and the clamp
    flattened them into a tie broken by list order. A perfect mapping lost to a
    worse one that way.
    """
    a = arrange_for_shawzin(c_major_scale, instrument, bpm=120.0)
    top = a.scale_candidates[:5]
    assert top[0].score < 1.0 or len({round(c.score, 6) for c in top}) > 1
    assert _interval_error(a) == 0.0

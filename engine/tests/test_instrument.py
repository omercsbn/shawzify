"""The Shawzin instrument model, checked against the researched format."""

from __future__ import annotations

import pytest

from shawzify_engine.music.pitch import note_name
from shawzify_engine.shawzin.instrument import (
    CHORD_FRETS,
    SINGLE_FRETS,
    STRINGS,
    default_instrument,
    load_instrument,
)

#: Documented in-game scale order, from the WARFRAME Wiki controls table.
EXPECTED_SCALE_ORDER = [
    "Pentatonic Minor",
    "Pentatonic Major",
    "Chromatic",
    "Hexatonic",
    "Major",
    "Minor",
    "Phrygian Dominant",  # the wiki calls this "Phrygian"; the intervals are Phrygian Dominant
    "Yo",
    "Hirajoshi",
]


def test_nine_scales_in_documented_order(instrument):
    assert len(instrument.scales) == 9
    names = [s.name for s in instrument.scales]
    assert names == [
        "Pentatonic Minor", "Pentatonic Major", "Chromatic", "Hexatonic",
        "Major", "Minor", "Hirajoshi", "Phrygian Dominant", "Yo",
    ]
    assert set(names) == set(EXPECTED_SCALE_ORDER)


def test_scale_codes_are_one_through_nine(instrument):
    assert [s.code for s in instrument.scales] == list("123456789")


def test_every_scale_has_twelve_single_notes(instrument):
    for scale in instrument.scales:
        assert len(scale.notes) == 12
        positions = {n.position for n in scale.notes}
        expected = {f + "-" + s for f in SINGLE_FRETS for s in STRINGS}
        assert positions == expected


def test_chromatic_scale_is_one_octave_from_c3(instrument):
    """Cross-check against ShawzinBot's empirical MIDI table: C3 == 48."""
    chrom = instrument.scale("chrom")
    assert chrom.lowest_midi == 48
    assert chrom.highest_midi == 59
    assert note_name(chrom.lowest_midi) == "C3"
    assert sorted(chrom.pitch_classes) == list(range(12))
    # Positions run 0-1, 0-2, 0-3, 1-1 ... ascending by semitone.
    ordered = sorted(chrom.notes, key=lambda n: n.midi)
    assert [n.position for n in ordered] == [
        "0-1", "0-2", "0-3", "1-1", "1-2", "1-3",
        "2-1", "2-2", "2-3", "3-1", "3-2", "3-3",
    ]


@pytest.mark.parametrize(
    "scale_id,intervals",
    [
        ("pmin", (0, 3, 5, 7, 10)),           # minor pentatonic
        ("pmaj", (0, 2, 4, 7, 9)),            # major pentatonic
        ("maj", (0, 2, 4, 5, 7, 9, 11)),      # ionian
        ("min", (0, 2, 3, 5, 7, 8, 10)),      # aeolian
        ("phry", (0, 1, 4, 5, 7, 8, 10)),     # phrygian dominant
        ("hex", (0, 3, 5, 6, 7, 10)),         # blues
    ],
)
def test_scale_intervals_are_musically_correct(instrument, scale_id, intervals):
    assert instrument.scale(scale_id).intervals == intervals


def test_scales_have_distinct_ranges(instrument):
    """Range differences are what make the scale choice matter."""
    ranges = {s.id: (s.lowest_midi, s.highest_midi) for s in instrument.scales}
    assert ranges["chrom"] == (48, 59)     # one octave, every semitone
    assert ranges["pmin"] == (48, 75)      # over two octaves, five notes each
    assert ranges["maj"] == (48, 67)
    assert len({r[1] for r in ranges.values()}) > 3


def test_chord_positions_use_combined_frets(instrument):
    for scale in instrument.scales:
        assert len(scale.chords) == 12
        frets = {c.fret for c in scale.chords}
        assert frets == set(CHORD_FRETS)
        for chord in scale.chords:
            assert len(chord.midi) >= 1
            assert chord.name


def test_major_scale_chords_include_expected_triads(instrument):
    names = {c.name for c in instrument.scale("maj").chords}
    for expected in ("C", "Dm", "Em", "F", "G", "Am"):
        assert expected in names


def test_tiamat_uses_slap_instead_of_chords():
    """The Tiamat produces slap-bass versions of notes, not chords."""
    tiamat = load_instrument("tiamat")
    assert tiamat.variant.chord_type == "slap"
    scale = tiamat.scale("pmin")
    assert len(scale.chords) == 12
    for chord in scale.chords:
        assert len(chord.midi) == 1  # a slap is one pitch
        assert "slap" in chord.name


def test_polyphony_differs_between_variants():
    assert load_instrument("dax").max_simultaneous_strings == 3       # polyphonic
    assert load_instrument("corbu").max_simultaneous_strings == 1     # monophonic
    assert load_instrument("void").max_simultaneous_strings == 2      # duophonic


def test_format_constants_match_the_game(instrument):
    fmt = instrument.format
    assert fmt.ticks_per_second == 16
    assert fmt.max_song_seconds == 240      # the game caps at exactly 4 minutes
    assert fmt.max_ticks == 3840
    assert fmt.encodable_max_ticks == 4095  # the format itself reaches 4m16s
    assert fmt.max_notes == 1000
    assert fmt.chat_link_max_notes == 100
    assert fmt.seconds_to_ticks(1.0) == 16
    assert fmt.ticks_to_seconds(16) == pytest.approx(1.0)


def test_all_variants_share_the_same_note_pitches():
    """Skins change timbre, not tuning -- so an arrangement is portable."""
    base = default_instrument()
    reference = {s.id: s.playable_midi for s in base.scales}
    for variant_id in base.variant_ids:
        variant = load_instrument(variant_id)
        for scale in variant.scales:
            assert scale.playable_midi == reference[scale.id], variant_id


def test_instrument_is_cached():
    assert load_instrument("dax") is load_instrument("dax")


def test_overall_range(instrument):
    lo, hi = instrument.overall_range
    assert note_name(lo) == "C3"
    assert note_name(hi) == "D#5"

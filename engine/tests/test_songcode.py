"""Song code encoding, decoding and format constraints.

The golden fixture is a real in-game code published in a community guide; it is
what pins our encoder to the actual format rather than to our own assumptions.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from shawzify_engine.common.errors import SongCodeError
from shawzify_engine.shawzin.instrument import default_instrument
from shawzify_engine.shawzin.songcode import (
    ALPHABET,
    ShawzinEvent,
    ShawzinSong,
    b64_to_int,
    decode,
    decode_note_byte,
    describe,
    encode,
    encode_note_byte,
    events_to_midi_notes,
    int_to_b64,
    validate_events,
)

#: A real Warframe Shawzin song code: an ascending pentatonic-minor run.
#: Source: community Shawzin song-code guide (see docs/research/shawzin-format.md).
GOLDEN_CODE = "1BAACAIEAQJAYKAgMAo"


def test_alphabet_is_standard_base64_order():
    assert ALPHABET.startswith("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert "abcdefghijklmnopqrstuvwxyz" in ALPHABET
    assert ALPHABET.endswith("0123456789+/")
    assert len(ALPHABET) == 64
    assert len(set(ALPHABET)) == 64


def test_golden_code_decodes_to_expected_music(instrument):
    info = describe(GOLDEN_CODE, instrument)
    assert info["scaleId"] == "pmin"
    assert info["scaleName"] == "Pentatonic Minor"
    assert info["eventCount"] == 6
    names = [n["name"] for n in info["soundingNotes"]]
    assert names == ["C3", "D#3", "F3", "G3", "A#3", "C4"]
    times = [n["seconds"] for n in info["soundingNotes"]]
    assert times == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]


def test_golden_code_round_trips_byte_exact(instrument):
    assert encode(decode(GOLDEN_CODE, instrument), instrument) == GOLDEN_CODE


def test_golden_code_positions(instrument):
    song = decode(GOLDEN_CODE, instrument)
    assert [e.position for e in song.events] == [
        "0-1", "0-2", "0-3", "1-1", "1-2", "1-3"
    ]
    assert [e.tick for e in song.events] == [0, 8, 16, 24, 32, 40]


@given(st.integers(min_value=0, max_value=63))
def test_base64_char_round_trip(value):
    assert b64_to_int(int_to_b64(value)) == value


@given(
    st.sampled_from(["0", "1", "2", "3", "12", "13", "23", "123"]),
    st.sampled_from(["1", "2", "3", "12", "13", "23", "123"]),
)
def test_note_byte_round_trip(fret, string):
    """Property: packing then unpacking a position is the identity."""
    byte = encode_note_byte(fret, string)
    back_fret, back_string = decode_note_byte(byte)
    assert back_fret == fret
    assert back_string == string


def test_note_byte_bit_layout():
    """Strings occupy bits 0-2, frets bits 3-5 -- exactly as the game reads them."""
    assert encode_note_byte("0", "1") == 0b000001
    assert encode_note_byte("0", "2") == 0b000010
    assert encode_note_byte("0", "3") == 0b000100
    assert encode_note_byte("1", "1") == 0b001001
    assert encode_note_byte("2", "1") == 0b010001
    assert encode_note_byte("3", "1") == 0b100001
    assert encode_note_byte("123", "123") == 0b111111


def test_empty_string_rejected():
    with pytest.raises(SongCodeError):
        encode_note_byte("1", "")


_TICKS = st.integers(min_value=0, max_value=3839)
_FRETS = st.sampled_from(["0", "1", "2", "3", "12", "13", "23", "123"])
_STRINGS = st.sampled_from(["1", "2", "3"])


@settings(max_examples=120, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.lists(st.tuples(_TICKS, _FRETS, _STRINGS), min_size=1, max_size=40, unique_by=lambda t: t[0])
)
def test_encode_decode_preserves_events(items):
    """Property: decode(encode(song)) preserves every supported event."""
    instrument = default_instrument()
    events = [ShawzinEvent(t, f, s) for t, f, s in items]
    song = ShawzinSong("chrom", events)
    code = encode(song, instrument)
    back = decode(code, instrument)
    offset = song.events[0].tick
    assert len(back.events) == len(song.events)
    for original, decoded in zip(song.events, back.events):
        assert decoded.tick == original.tick - offset
        assert decoded.fret == original.fret
        assert decoded.string == original.string


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.tuples(_TICKS, _FRETS, _STRINGS), min_size=1, max_size=30, unique_by=lambda t: t[0]))
def test_encoded_code_always_has_valid_length(items):
    """Property: every emitted code is 3n+1 characters of the alphabet."""
    events = [ShawzinEvent(t, f, s) for t, f, s in items]
    code = encode(ShawzinSong("maj", events), default_instrument())
    assert len(code) % 3 == 1
    assert all(c in ALPHABET for c in code)


def test_multi_string_events_merge_into_one_input(instrument):
    """Three strings on one fret at one tick is a single strum, not three events."""
    song = ShawzinSong("maj", [
        ShawzinEvent(0, "1", "1"),
        ShawzinEvent(0, "1", "2"),
        ShawzinEvent(0, "1", "3"),
    ])
    code = encode(song, instrument)
    assert len(code) == 4  # scale char + one note triple
    back = decode(code, instrument)
    assert len(back.events) == 1
    assert back.events[0].string == "123"


def test_decode_rejects_bad_length(instrument):
    with pytest.raises(SongCodeError):
        decode("1BAAC", instrument)


def test_decode_rejects_bad_scale(instrument):
    with pytest.raises(SongCodeError):
        decode("ZBAA", instrument)


def test_decode_rejects_bad_character(instrument):
    with pytest.raises(SongCodeError):
        decode("1B*A", instrument)


def test_decode_ignores_whitespace(instrument):
    assert decode("1BAA CAI", instrument).events[1].tick == 8


def test_decode_zero_string_note_is_ignored(instrument):
    """Note byte 0 has no strings; the game ignores it, so must we."""
    song = decode("1AAABAI", instrument)
    assert len(song.events) == 1
    assert song.events[0].tick == 8


def test_alt_note_round_trip(instrument):
    """Duviri alt notes use the 'N//' marker after a normal triple."""
    event = ShawzinEvent(0, "1", "1", alt_fret="2", alt_string="3")
    code = encode(ShawzinSong("chrom", [event]), instrument)
    assert code.endswith("//")
    back = decode(code, instrument)
    assert back.events[0].alt_fret == "2"
    assert back.events[0].alt_string == "3"
    assert back.events[0].has_alt


def test_validate_rejects_two_frets_at_one_tick(instrument):
    """The hard instrument constraint: one fret position per instant."""
    events = [ShawzinEvent(0, "1", "1"), ShawzinEvent(0, "2", "2")]
    with pytest.raises(SongCodeError, match="fret position"):
        validate_events(events, instrument)


def test_validate_rejects_duplicate_string_at_one_tick(instrument):
    events = [ShawzinEvent(0, "1", "1"), ShawzinEvent(0, "1", "1")]
    with pytest.raises(SongCodeError, match="same string"):
        validate_events(events, instrument)


def test_validate_rejects_over_time_limit(instrument):
    limit = instrument.format.max_ticks
    with pytest.raises(SongCodeError, match="4 minute"):
        validate_events([ShawzinEvent(limit + 1, "0", "1")], instrument)


def test_validate_rejects_over_note_limit(instrument):
    limit = instrument.format.max_notes
    events = [ShawzinEvent(i, "0", "1") for i in range(limit + 5)]
    with pytest.raises(SongCodeError, match="limit"):
        validate_events(events, instrument)


def test_monophonic_shawzin_rejects_chords():
    """The Corbu is monophonic; two strings at once is not playable on it."""
    mono = default_instrument().with_variant("corbu")
    assert mono.max_simultaneous_strings == 1
    with pytest.raises(SongCodeError, match="at once"):
        validate_events([ShawzinEvent(0, "1", "12")], mono)


def test_chord_fret_expands_to_chord_pitches(instrument):
    """A combined fret plays a real chord, not a single note."""
    song = ShawzinSong("maj", [ShawzinEvent(0, "12", "1")])
    pairs = events_to_midi_notes(song, instrument)
    assert len(pairs) == 3
    scale = instrument.scale("maj")
    chord = scale.chord_at("12-1")
    assert chord is not None
    assert sorted(m for _, m in pairs) == sorted(chord.midi)


def test_encode_zero_bases_the_song(instrument):
    """Codes always start at tick 0, matching what the game writes."""
    song = ShawzinSong("maj", [ShawzinEvent(100, "0", "1"), ShawzinEvent(108, "0", "2")])
    back = decode(encode(song, instrument), instrument)
    assert back.events[0].tick == 0
    assert back.events[1].tick == 8


def test_empty_song_encodes_to_empty_string(instrument):
    assert encode(ShawzinSong("maj", []), instrument) == ""

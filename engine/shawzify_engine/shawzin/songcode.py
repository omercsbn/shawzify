"""Warframe Shawzin song code encoding and decoding.

Format (verified against three independent sources -- see
``docs/research/shawzin-format.md``)::

    <scale><note><note>...            total length is always 3n + 1

    scale : one character, the 1-based index into the scale order ("1".."9")
    note  : three base64 characters
              [0] note byte  : bits 0-2 = strings 1/2/3, bits 3-5 = frets 1/2/3
              [1] measure    : tick // 64
              [2] measureTick: tick %  64

    tick  : 1/16 second since the start of the song

    alphabet: ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/
              (standard base64 order; note digits come *after* letters)

A note may carry a Duviri "alt" by appending three more characters
``<noteByte>//``; the ``//`` marker is unambiguous because it would otherwise
encode tick 4095, beyond the game's 4-minute cap.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import InstrumentConstraintError, SongCodeError
from .instrument import ShawzinInstrument, default_instrument

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_INDEX = {c: i for i, c in enumerate(ALPHABET)}

STRING_BITS = {"1": 0x01, "2": 0x02, "3": 0x04}
FRET_BITS = {"1": 0x08, "2": 0x10, "3": 0x20}
ALT_SUFFIX = "//"


def b64_to_int(char: str) -> int:
    try:
        return _INDEX[char]
    except KeyError as exc:
        raise SongCodeError(
            "The song code contains a character that is not part of the format.",
            technical="Invalid character: " + repr(char),
        ) from exc


def int_to_b64(value: int) -> str:
    if not 0 <= value <= 63:
        raise SongCodeError(
            "A value in this arrangement is outside what the song code can hold.",
            technical="Value out of base64 range: " + str(value),
        )
    return ALPHABET[value]


def encode_note_byte(fret: str, string: str) -> int:
    """Pack a fret state and one or more strings into the note byte."""
    value = 0
    for ch in string:
        if ch not in STRING_BITS:
            raise SongCodeError(
                "Invalid string in arrangement.", technical="Bad string: " + repr(string)
            )
        value |= STRING_BITS[ch]
    if value == 0:
        raise SongCodeError(
            "A note in this arrangement has no string to pluck.",
            technical="Empty string spec for fret " + repr(fret),
        )
    for ch in fret:
        if ch == "0":
            continue
        if ch not in FRET_BITS:
            raise SongCodeError(
                "Invalid fret in arrangement.", technical="Bad fret: " + repr(fret)
            )
        value |= FRET_BITS[ch]
    return value


def decode_note_byte(value: int) -> tuple[str, str]:
    """Unpack the note byte into ``(fret, string)`` with canonical ordering."""
    strings = "".join(k for k in ("1", "2", "3") if value & STRING_BITS[k])
    frets = "".join(k for k in ("1", "2", "3") if value & FRET_BITS[k])
    return (frets or "0", strings)


@dataclass(frozen=True, slots=True)
class ShawzinEvent:
    """One encodable song-code event: a fret state, strings, and a tick."""

    tick: int
    fret: str
    string: str
    alt_fret: str | None = None
    alt_string: str | None = None

    @property
    def position(self) -> str:
        return self.fret + "-" + self.string

    @property
    def is_chord_fret(self) -> bool:
        """True when a combined fret state is held (a chord or slap position)."""
        return len(self.fret) > 1

    @property
    def has_alt(self) -> bool:
        return self.alt_fret is not None and (
            self.alt_fret != self.fret or self.alt_string != self.string
        )

    def seconds(self, ticks_per_second: int = 16) -> float:
        return self.tick / float(ticks_per_second)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "tick": self.tick,
            "fret": self.fret,
            "string": self.string,
            "position": self.position,
        }
        if self.has_alt:
            d["altFret"] = self.alt_fret
            d["altString"] = self.alt_string
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ShawzinEvent:
        return ShawzinEvent(
            tick=int(d["tick"]),
            fret=str(d["fret"]),
            string=str(d["string"]),
            alt_fret=d.get("altFret"),
            alt_string=d.get("altString"),
        )


@dataclass
class ShawzinSong:
    """A decoded song: a scale plus time-ordered events."""

    scale_id: str
    events: list[ShawzinEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.events = sorted(self.events, key=lambda e: (e.tick, e.fret, e.string))

    @property
    def note_count(self) -> int:
        """Number of individual string plucks (a 3-string strum counts as 3)."""
        return sum(len(e.string) for e in self.events)

    @property
    def end_tick(self) -> int:
        return max((e.tick for e in self.events), default=0)

    def duration_seconds(self, ticks_per_second: int = 16) -> float:
        return self.end_tick / float(ticks_per_second)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scaleId": self.scale_id,
            "events": [e.to_dict() for e in self.events],
            "noteCount": self.note_count,
            "endTick": self.end_tick,
        }


def _merge_same_tick_and_fret(events: Sequence[ShawzinEvent]) -> list[ShawzinEvent]:
    """Combine events sharing a tick and fret into one multi-string event.

    This is what makes a strum a single game input instead of three.
    """
    merged: list[ShawzinEvent] = []
    buckets: dict[tuple[int, str], list[ShawzinEvent]] = {}
    order: list[tuple[int, str]] = []
    for ev in events:
        key = (ev.tick, ev.fret)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(ev)
    for key in sorted(order):
        group = buckets[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        # An alt cannot be represented on a multi-string event; keep those split.
        with_alt = [e for e in group if e.has_alt]
        plain = [e for e in group if not e.has_alt]
        if plain:
            strings = "".join(sorted({ch for e in plain for ch in e.string}))
            merged.append(ShawzinEvent(tick=key[0], fret=key[1], string=strings))
        merged.extend(with_alt)
    return sorted(merged, key=lambda e: (e.tick, e.fret, e.string))


def encode(
    song: ShawzinSong,
    instrument: ShawzinInstrument | None = None,
    *,
    zero_base: bool = True,
    validate: bool = True,
) -> str:
    """Encode a :class:`ShawzinSong` into an importable song code.

    ``zero_base`` shifts the song so the first event lands on tick 0, matching
    what the game produces. Set it to False to preserve an intentional lead-in.
    """
    inst = instrument or default_instrument()
    scale = inst.scale(song.scale_id)
    if not song.events:
        return ""
    events = _merge_same_tick_and_fret(song.events)
    offset = events[0].tick if zero_base else 0
    if validate:
        validate_events(events, inst, offset=offset)
    parts = [scale.code]
    for ev in events:
        tick = ev.tick - offset
        measure, measure_tick = divmod(tick, 64)
        parts.append(
            int_to_b64(encode_note_byte(ev.fret, ev.string))
            + int_to_b64(measure)
            + int_to_b64(measure_tick)
        )
        if ev.has_alt:
            parts.append(
                int_to_b64(encode_note_byte(ev.alt_fret or ev.fret, ev.alt_string or ev.string))
                + ALT_SUFFIX
            )
    return "".join(parts)


def validate_events(
    events: Sequence[ShawzinEvent],
    instrument: ShawzinInstrument | None = None,
    *,
    offset: int = 0,
    check_limits: bool = True,
) -> None:
    """Raise if anything violates the format or the instrument's constraints.

    ``check_limits`` covers the song's *length* and *note count*. Those are a
    packaging concern rather than an arrangement failure -- an over-long
    arrangement is perfectly valid music that needs splitting into parts -- so
    the arranger checks everything except the limits, and only encoding a single
    code enforces them.
    """
    inst = instrument or default_instrument()
    fmt = inst.format
    total = sum(len(e.string) for e in events)
    if check_limits and total > fmt.max_notes:
        raise SongCodeError(
            "This arrangement has " + str(total) + " notes, more than the Shawzin's limit of "
            + str(fmt.max_notes) + ".",
            hint="Use Auto Split to break it into parts.",
        )
    by_tick: dict[int, list[ShawzinEvent]] = {}
    last_tick = -1
    for ev in events:
        tick = ev.tick - offset
        if tick < 0:
            raise SongCodeError(
                "An arranged note lands before the start of the song.",
                technical="Negative tick after offset: " + str(tick),
            )
        if check_limits and tick > fmt.max_ticks:
            raise SongCodeError(
                "This arrangement is longer than the Shawzin's 4 minute limit.",
                hint="Use Auto Split to break it into parts.",
                technical="Tick " + str(tick) + " exceeds " + str(fmt.max_ticks),
            )
        if tick < last_tick:
            raise SongCodeError(
                "Arranged notes are out of order.", technical="Unsorted tick " + str(tick)
            )
        last_tick = tick
        if not ev.string:
            raise SongCodeError("A note has no string.", technical=repr(ev))
        by_tick.setdefault(tick, []).append(ev)
    for tick, group in by_tick.items():
        frets = {e.fret for e in group}
        if len(frets) > 1:
            raise SongCodeError(
                "Two notes at the same moment need different fret positions, "
                "which the Shawzin cannot do.",
                technical="Tick " + str(tick) + " has fret states " + repr(sorted(frets)),
            )
        strings = [ch for e in group for ch in e.string]
        if len(strings) != len(set(strings)):
            raise SongCodeError(
                "The same string is plucked twice at the same moment.",
                technical="Tick " + str(tick) + " strings " + repr(strings),
            )
        if len(strings) > inst.max_simultaneous_strings:
            raise SongCodeError(
                "The " + inst.variant.name + " can only sound "
                + str(inst.max_simultaneous_strings) + " note(s) at once.",
                technical="Tick " + str(tick) + " has " + str(len(strings)) + " strings",
            )


def decode(code: str, instrument: ShawzinInstrument | None = None) -> ShawzinSong:
    """Decode a song code. Multi-string events are preserved, not split."""
    inst = instrument or default_instrument()
    if code is None:
        raise SongCodeError("No song code was given.")
    cleaned = "".join(code.split())
    if not cleaned:
        raise SongCodeError("No song code was given.")
    if len(cleaned) % 3 != 1:
        raise SongCodeError(
            "That song code is the wrong length to be valid.",
            technical="Length " + str(len(cleaned)) + " is not 3n+1",
        )
    scale_char = cleaned[0]
    try:
        scale = inst.scale_by_code(scale_char)
    except (KeyError, InstrumentConstraintError) as exc:
        # A scale the instrument does not have is an instrument problem in
        # general, but inside a song code it is a song-code problem, and that
        # is what the caller is trying to read.
        raise SongCodeError(
            "That song code uses a scale SHAWZIFY does not know (" + repr(scale_char) + ").",
            technical=str(exc),
        ) from exc

    events: list[ShawzinEvent] = []
    i = 1
    n = len(cleaned)
    while i + 3 <= n:
        chunk = cleaned[i : i + 3]
        alt_fret = alt_string = None
        # Peek at the following triple: "N//" marks an alt for the note just read.
        if i + 6 <= n and cleaned[i + 4 : i + 6] == ALT_SUFFIX:
            alt_fret, alt_string = decode_note_byte(b64_to_int(cleaned[i + 3]))
            consumed = 6
        else:
            consumed = 3
        note_byte = b64_to_int(chunk[0])
        fret, string = decode_note_byte(note_byte)
        if not string:
            # The game itself ignores a note code with no strings; so do we.
            i += consumed
            continue
        tick = b64_to_int(chunk[1]) * 64 + b64_to_int(chunk[2])
        events.append(
            ShawzinEvent(
                tick=tick,
                fret=fret,
                string=string,
                alt_fret=alt_fret,
                alt_string=alt_string,
            )
        )
        i += consumed
    if i != n:
        raise SongCodeError(
            "That song code ends with an incomplete note.",
            technical="Trailing characters at index " + str(i),
        )
    return ShawzinSong(scale_id=scale.id, events=events)


def events_to_midi_notes(
    song: ShawzinSong, instrument: ShawzinInstrument | None = None
) -> list[tuple[float, int]]:
    """Expand a decoded song to ``(seconds, midi)`` pairs, chords included.

    Used to preview or re-import a song code as real notes.
    """
    inst = instrument or default_instrument()
    scale = inst.scale(song.scale_id)
    tps = inst.format.ticks_per_second
    out: list[tuple[float, int]] = []
    for ev in song.events:
        seconds = ev.tick / float(tps)
        for ch in ev.string:
            position = ev.fret + "-" + ch
            if ev.is_chord_fret:
                chord = scale.chord_at(position)
                if chord is not None:
                    out.extend((seconds, m) for m in chord.midi)
                continue
            note = scale.note_at(position)
            if note is not None:
                out.append((seconds, note.midi))
    return sorted(out)


def describe(code: str, instrument: ShawzinInstrument | None = None) -> dict[str, Any]:
    """Human-facing summary of a song code, for the CLI ``decode`` command."""
    inst = instrument or default_instrument()
    song = decode(code, inst)
    scale = inst.scale(song.scale_id)
    pairs = events_to_midi_notes(song, inst)
    from ..music.pitch import note_name

    return {
        "scaleId": scale.id,
        "scaleName": scale.name,
        "scaleCode": scale.code,
        "eventCount": len(song.events),
        "noteCount": song.note_count,
        "chordEvents": sum(1 for e in song.events if e.is_chord_fret),
        "altEvents": sum(1 for e in song.events if e.has_alt),
        "durationSeconds": round(song.duration_seconds(inst.format.ticks_per_second), 3),
        "endTick": song.end_tick,
        "withinNoteLimit": song.note_count <= inst.format.max_notes,
        "withinChatLinkLimit": song.note_count <= inst.format.chat_link_max_notes,
        "soundingNotes": [
            {"seconds": round(s, 4), "midi": m, "name": note_name(m)} for s, m in pairs
        ],
        "events": song.to_dict()["events"],
    }


def iter_codes(codes: Iterable[str]) -> list[ShawzinSong]:
    return [decode(c) for c in codes]

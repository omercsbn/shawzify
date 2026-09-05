"""The one authoritative Shawzin instrument model.

Everything about the instrument -- scales, note pitches, chord voicings, format
limits -- comes from ``data/shawzin_instrument.json``, which was derived from the
sources documented in ``docs/research/shawzin-format.md``. No mapping table is
hard-coded anywhere else in the engine.

Physical model (this is what makes the Shawzin interesting to arrange for):

* 3 strings, played with the 1/2/3 keys.
* 3 fret keys which combine, giving 8 fret states: ``0 1 2 3 12 23 13 123``.
* A *single* fret state (0/1/2/3) plus a string plays one scale note, so a scale
  exposes exactly 12 single notes.
* A *combined* fret state (12/23/13/123) plus a string plays a fixed 3-note
  chord (or, on the Tiamat, a slap version of a note).
* The fret is a hand position, so all notes sounding at the same instant must
  share one fret state. That is the hard polyphony constraint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..common.errors import InstrumentConstraintError
from ..music.pitch import note_name, pitch_class

DATA_PATH = Path(__file__).with_name("data") / "shawzin_instrument.json"

SINGLE_FRETS = ("0", "1", "2", "3")
CHORD_FRETS = ("12", "23", "13", "123")
STRINGS = ("1", "2", "3")


@dataclass(frozen=True, slots=True)
class ShawzinNote:
    """One playable single-note position."""

    fret: str
    string: str
    midi: int

    @property
    def position(self) -> str:
        return self.fret + "-" + self.string

    @property
    def name(self) -> str:
        return note_name(self.midi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fret": self.fret,
            "string": self.string,
            "position": self.position,
            "midi": self.midi,
            "name": self.name,
        }


@dataclass(frozen=True, slots=True)
class ShawzinChord:
    """One playable chord position (a combined fret state plus a string)."""

    fret: str
    string: str
    name: str
    midi: tuple[int, ...]

    @property
    def position(self) -> str:
        return self.fret + "-" + self.string

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset(pitch_class(m) for m in self.midi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fret": self.fret,
            "string": self.string,
            "position": self.position,
            "name": self.name,
            "midi": list(self.midi),
        }


@dataclass(frozen=True)
class ShawzinScale:
    """A selectable in-game scale: 12 single notes plus up to 12 chords."""

    id: str
    code: str
    index: int
    name: str
    chord_type: str
    root_pitch_class: int
    notes: tuple[ShawzinNote, ...]
    chords: tuple[ShawzinChord, ...]
    alt_names: tuple[dict[str, Any], ...] = ()

    @property
    def lowest_midi(self) -> int:
        return min(n.midi for n in self.notes)

    @property
    def highest_midi(self) -> int:
        return max(n.midi for n in self.notes)

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset(pitch_class(n.midi) for n in self.notes)

    @property
    def intervals(self) -> tuple[int, ...]:
        """Scale-degree intervals above the scale root, ascending."""
        root = self.root_pitch_class
        return tuple(sorted({(pitch_class(n.midi) - root) % 12 for n in self.notes}))

    @property
    def playable_midi(self) -> tuple[int, ...]:
        return tuple(sorted({n.midi for n in self.notes}))

    def notes_for_midi(self, midi: int) -> tuple[ShawzinNote, ...]:
        return tuple(n for n in self.notes if n.midi == midi)

    def note_at(self, position: str) -> ShawzinNote | None:
        for n in self.notes:
            if n.position == position:
                return n
        return None

    def chord_at(self, position: str) -> ShawzinChord | None:
        for c in self.chords:
            if c.position == position:
                return c
        return None

    def contains_pitch_class(self, midi: int) -> bool:
        return pitch_class(midi) in self.pitch_classes

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "index": self.index,
            "name": self.name,
            "chordType": self.chord_type,
            "rootPitchClass": self.root_pitch_class,
            "intervals": list(self.intervals),
            "lowestMidi": self.lowest_midi,
            "highestMidi": self.highest_midi,
            "pitchClasses": sorted(self.pitch_classes),
            "notes": [n.to_dict() for n in self.notes],
            "chords": [c.to_dict() for c in self.chords],
            "altNames": list(self.alt_names),
        }


@dataclass(frozen=True)
class SongCodeFormat:
    """Hard limits of the in-game song code format."""

    base64_alphabet: str
    ticks_per_second: int
    max_song_seconds: int
    max_ticks: int
    encodable_max_ticks: int
    max_notes: int
    chat_link_max_notes: int
    default_lead_in_ticks: int
    alt_note_suffix: str
    string_bits: dict[str, int]
    fret_bits: dict[str, int]

    def seconds_to_ticks(self, seconds: float) -> int:
        return int(round(float(seconds) * self.ticks_per_second))

    def ticks_to_seconds(self, ticks: int) -> float:
        return float(ticks) / self.ticks_per_second

    @property
    def tick_seconds(self) -> float:
        return 1.0 / self.ticks_per_second

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticksPerSecond": self.ticks_per_second,
            "maxSongSeconds": self.max_song_seconds,
            "maxTicks": self.max_ticks,
            "encodableMaxTicks": self.encodable_max_ticks,
            "maxNotes": self.max_notes,
            "chatLinkMaxNotes": self.chat_link_max_notes,
            "defaultLeadInTicks": self.default_lead_in_ticks,
            "tickSeconds": self.tick_seconds,
        }


@dataclass(frozen=True)
class ShawzinVariant:
    """One purchasable Shawzin. Same notes, different timbre and polyphony."""

    id: str
    name: str
    polyphony: str  # polyphonic | monophonic | duophonic
    clef: str
    tuning_cents: int
    note_length_seconds: float
    supports_alt_notes: bool
    chord_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "polyphony": self.polyphony,
            "clef": self.clef,
            "tuningCents": self.tuning_cents,
            "noteLengthSeconds": self.note_length_seconds,
            "supportsAltNotes": self.supports_alt_notes,
            "chordType": self.chord_type,
        }


class ShawzinInstrument:
    """Loaded instrument definition. Construct via :func:`load_instrument`."""

    def __init__(self, data: dict[str, Any], variant_id: str = "dax") -> None:
        self._data = data
        self.base_midi: int = int(data["baseMidi"])
        self.variant_id = variant_id
        fmt = data["format"]
        self.format = SongCodeFormat(
            base64_alphabet=fmt["base64Alphabet"],
            ticks_per_second=int(fmt["ticksPerSecond"]),
            max_song_seconds=int(fmt["maxSongSeconds"]),
            max_ticks=int(fmt["maxTicks"]),
            encodable_max_ticks=int(fmt["encodableMaxTicks"]),
            max_notes=int(fmt["maxNotes"]),
            chat_link_max_notes=int(fmt["chatLinkMaxNotes"]),
            default_lead_in_ticks=int(fmt["defaultLeadInTicks"]),
            alt_note_suffix=fmt["altNoteSuffix"],
            string_bits={k: int(v) for k, v in fmt["stringBits"].items()},
            fret_bits={k: int(v) for k, v in fmt["fretBits"].items()},
        )
        variant_data = data["shawzins"].get(variant_id) or data["shawzins"]["dax"]
        self.variant = ShawzinVariant(
            id=variant_data["id"],
            name=variant_data["name"],
            polyphony=variant_data["polyphony"],
            clef=variant_data["clef"],
            tuning_cents=int(variant_data["tuningCents"]),
            note_length_seconds=float(variant_data["noteLengthSeconds"]),
            supports_alt_notes=bool(variant_data["supportsAltNotes"]),
            chord_type=variant_data["chordType"],
        )
        self.slap_map: dict[str, str] = dict(data["slapMap"])
        chord_table = variant_data.get("chords", {})
        self._scales: dict[str, ShawzinScale] = {}
        for scale_id in data["scaleOrder"]:
            raw = data["scales"][scale_id]
            notes = tuple(
                ShawzinNote(fret=pos.split("-")[0], string=pos.split("-")[1], midi=int(midi))
                for pos, midi in raw["notes"].items()
            )
            chords: list[ShawzinChord] = []
            scale_chords = chord_table.get(scale_id)
            if scale_chords:
                for pos, c in scale_chords.items():
                    chords.append(
                        ShawzinChord(
                            fret=pos.split("-")[0],
                            string=pos.split("-")[1],
                            name=c["name"],
                            midi=tuple(int(m) for m in c["midi"]),
                        )
                    )
            elif self.variant.chord_type == "slap":
                # Tiamat: a combined fret makes the mapped note sound slapped,
                # same pitch, different timbre.
                by_pos = {n.position: n for n in notes}
                for chord_pos, note_pos in self.slap_map.items():
                    src = by_pos.get(note_pos)
                    if src is None:
                        continue
                    chords.append(
                        ShawzinChord(
                            fret=chord_pos.split("-")[0],
                            string=chord_pos.split("-")[1],
                            name=note_name(src.midi) + " (slap)",
                            midi=(src.midi,),
                        )
                    )
            self._scales[scale_id] = ShawzinScale(
                id=raw["id"],
                code=raw["code"],
                index=int(raw["index"]),
                name=raw["name"],
                chord_type=raw.get("chordType") or self.variant.chord_type,
                root_pitch_class=int(raw["rootPitchClass"]),
                notes=tuple(sorted(notes, key=lambda n: (n.fret, n.string))),
                chords=tuple(sorted(chords, key=lambda c: (c.fret, c.string))),
                alt_names=tuple(raw.get("altNames", [])),
            )

    # -- scales ---------------------------------------------------------

    @property
    def scale_ids(self) -> tuple[str, ...]:
        return tuple(self._data["scaleOrder"])

    @property
    def scales(self) -> tuple[ShawzinScale, ...]:
        return tuple(self._scales[s] for s in self.scale_ids)

    def scale(self, scale_id: str) -> ShawzinScale:
        try:
            return self._scales[scale_id]
        except KeyError as exc:
            # This reaches users directly: `--scale klingon` used to surface as
            # KeyError with a traceback rather than the list of real scales.
            raise InstrumentConstraintError(
                "The Shawzin has no scale called '" + str(scale_id) + "'.",
                hint="Available scales: " + ", ".join(self.scale_ids) + ".",
            ) from exc

    def scale_by_code(self, code: str) -> ShawzinScale:
        for s in self._scales.values():
            if s.code == str(code):
                return s
        raise InstrumentConstraintError(
            "No Shawzin scale uses the code '" + str(code) + "'.",
            hint="A song code's first character selects the scale.",
        )

    # -- variants -------------------------------------------------------

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(self._data["shawzins"].keys())

    def with_variant(self, variant_id: str) -> ShawzinInstrument:
        return ShawzinInstrument(self._data, variant_id)

    def variants(self) -> list[ShawzinVariant]:
        out = []
        for vid in self.variant_ids:
            v = self._data["shawzins"][vid]
            out.append(
                ShawzinVariant(
                    id=v["id"],
                    name=v["name"],
                    polyphony=v["polyphony"],
                    clef=v["clef"],
                    tuning_cents=int(v["tuningCents"]),
                    note_length_seconds=float(v["noteLengthSeconds"]),
                    supports_alt_notes=bool(v["supportsAltNotes"]),
                    chord_type=v["chordType"],
                )
            )
        return out

    # -- constraints ----------------------------------------------------

    @property
    def max_simultaneous_strings(self) -> int:
        """How many strings may sound at one instant on this variant."""
        return {"polyphonic": 3, "duophonic": 2, "monophonic": 1}[self.variant.polyphony]

    @property
    def overall_range(self) -> tuple[int, int]:
        lo = min(s.lowest_midi for s in self.scales)
        hi = max(s.highest_midi for s in self.scales)
        return (lo, hi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseMidi": self.base_midi,
            "variant": self.variant.to_dict(),
            "format": self.format.to_dict(),
            "maxSimultaneousStrings": self.max_simultaneous_strings,
            "overallRange": list(self.overall_range),
            "scales": [s.to_dict() for s in self.scales],
        }


@lru_cache(maxsize=8)
def _load_data(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=32)
def load_instrument(variant_id: str = "dax", data_path: str | None = None) -> ShawzinInstrument:
    """Load the instrument model. Cached; the data file is read once."""
    return ShawzinInstrument(_load_data(data_path or str(DATA_PATH)), variant_id)


def default_instrument() -> ShawzinInstrument:
    return load_instrument()

"""Which Shawzin should you play this on?

The eleven Shawzins are not skins. They differ in ways that change what a song
sounds like and, in two cases, what is even playable:

* **Polyphony.** Dax, Nelumbo, Aristei, Kira, Lonesome and Courtly are
  polyphonic -- three strings can ring together. Void's Song is duophonic.
  Corbu, Tiamat, Narmer and Lizzie are monophonic: each new note cuts the
  previous one off, so a strummed chord becomes a fast arpeggio whether you
  wanted one or not.
* **Note length.** Dax rings for 2 seconds, Corbu and Tiamat for 10, Void's
  Song for 22, Lizzie for 28. A sustaining instrument turns a sparse ballad
  into something lush and turns a fast run into mud.
* **Chords.** Most Shawzins play a three-note chord on a combined fret. The
  Tiamat plays a slap-bass version of the note instead, so chord positions are
  a timbre change rather than harmony.
* **Register.** The Tiamat is written in bass clef and reads as a bass guitar.
* **Tuning.** The Nelumbo sits 25 cents sharp of the others.

So the recommendation is a real musical judgement about the arrangement in
hand, not a preference list. Every score comes with the reasons behind it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..music.events import NoteEvent, group_by_onset
from .instrument import ShawzinInstrument, ShawzinVariant, load_instrument
from .songcode import ShawzinSong

#: Timbre notes for the UI. Sourced from the WARFRAME Wiki's variant list,
#: which names the real-world instrument each Shawzin imitates.
TIMBRES: dict[str, str] = {
    "dax": "Shamisen - bright, percussive, short decay",
    "nelumbo": "Acoustic guitar - warm and even, tuned 25 cents sharp",
    "corbu": "Electric guitar with overdrive - sustained and gritty",
    "tiamat": "Bass guitar - low register, slap instead of chords",
    "aristei": "Harp - soft attack, delicate",
    "narmer": "Electric guitar with distortion - heavy and sustained",
    "kira": "Synth guitar - clean and modern",
    "void": "Acapella voices - very long sustain, choral",
    "lonesome": "Bell - clear and ringing",
    "courtly": "Sitar - buzzing, ornamented",
    "lizzie": "Electric guitar - the longest sustain of any Shawzin",
}


#: Per-variant leanings, derived from the real instrument each one imitates.
#: These are preferences rather than constraints, so they move the score much
#: less than polyphony or sustain do -- but they are what separates six
#: otherwise identical two-second Shawzins.
_CHARACTER: dict[str, dict[str, Any]] = {
    "dax": {
        "density": 0.9, "register": 0.0, "chords": 0.2,
        "blurb": "A shamisen's percussive attack keeps a busy line crisp.",
    },
    "nelumbo": {
        "density": 0.2, "register": 0.0, "chords": 0.7,
        "blurb": "Acoustic guitar sits naturally under strummed harmony.",
    },
    "kira": {
        "density": 0.6, "register": 0.6, "chords": 0.2,
        "blurb": "A synth guitar carries a bright, high melody cleanly.",
    },
    "aristei": {
        "density": -0.4, "register": 0.7, "chords": 0.8,
        "blurb": "A harp is at its best on spread chords and arpeggios.",
    },
    "lonesome": {
        "density": -0.9, "register": 0.9, "chords": -0.2,
        "blurb": "Bells suit a sparse, high, deliberate line.",
    },
    "courtly": {
        "density": 0.7, "register": 0.3, "chords": 0.0,
        "blurb": "A sitar's buzz flatters ornamented, fast-moving melodies.",
    },
    "corbu": {
        "density": -0.3, "register": 0.1, "chords": -0.3,
        "blurb": "Overdriven guitar suits sustained, deliberate lines.",
    },
    "narmer": {
        "density": -0.4, "register": 0.0, "chords": -0.3,
        "blurb": "Distortion carries slow, heavy material.",
    },
    "void": {
        "density": -0.9, "register": 0.4, "chords": 0.5,
        "blurb": "Choral voices suit slow, sustained, chordal writing.",
    },
    "lizzie": {
        "density": -0.9, "register": 0.0, "chords": -0.2,
        "blurb": "The longest sustain of any Shawzin, for very slow material.",
    },
    "tiamat": {
        "density": -0.2, "register": -1.0, "chords": -0.5,
        "blurb": "A bass guitar for low, riff-driven material.",
    },
}


@dataclass
class ShawzinSuggestion:
    variant_id: str
    name: str
    score: float
    polyphony: str
    timbre: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: What this variant would cost, in notes lost to its own limits.
    notes_lost: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "variantId": self.variant_id,
            "name": self.name,
            "score": round(self.score * 100.0, 1),
            "polyphony": self.polyphony,
            "timbre": self.timbre,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "notesLost": self.notes_lost,
        }


@dataclass
class MusicProfile:
    """What the music needs, measured rather than guessed."""

    notes_per_second: float
    peak_notes_per_second: float
    mean_polyphony: float
    max_polyphony: float
    chord_fraction: float
    #: Mean gap between consecutive onsets -- how much room a note has to ring.
    mean_gap_seconds: float
    median_pitch: int
    low_fraction: float
    sustain_fraction: float
    note_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "notesPerSecond": round(self.notes_per_second, 2),
            "peakNotesPerSecond": round(self.peak_notes_per_second, 2),
            "meanPolyphony": round(self.mean_polyphony, 2),
            "maxPolyphony": round(self.max_polyphony, 2),
            "chordFraction": round(self.chord_fraction, 3),
            "meanGapSeconds": round(self.mean_gap_seconds, 3),
            "medianPitch": self.median_pitch,
            "lowFraction": round(self.low_fraction, 3),
            "sustainFraction": round(self.sustain_fraction, 3),
            "noteCount": self.note_count,
        }


def profile_music(events: Sequence[NoteEvent], *, duration: float | None = None) -> MusicProfile:
    """Measure the properties that decide which instrument suits the music."""
    ordered = sorted(events, key=lambda e: (e.start_seconds, e.pitch_midi))
    if not ordered:
        return MusicProfile(0, 0, 0, 0, 0, 1.0, 60, 0.0, 0.0, 0)

    total = duration or max(e.end_seconds for e in ordered)
    total = max(total, 1e-6)
    groups = group_by_onset(ordered, 0.03)
    sizes = [len(g) for g in groups]
    onsets = [g[0].start_seconds for g in groups]
    gaps = [b - a for a, b in zip(onsets, onsets[1:])] or [total]

    # Peak density over a one-second window.
    peak = 0
    j = 0
    starts = [e.start_seconds for e in ordered]
    for i in range(len(starts)):
        while starts[i] - starts[j] > 1.0:
            j += 1
        peak = max(peak, i - j + 1)

    pitches = sorted(e.pitch_midi for e in ordered)
    median_pitch = pitches[len(pitches) // 2]
    mean_gap = sum(gaps) / len(gaps)
    # A note "sustains" when it lasts longer than the gap to the next onset.
    sustaining = sum(1 for e in ordered if e.duration_seconds > mean_gap * 1.2)

    return MusicProfile(
        notes_per_second=len(ordered) / total,
        peak_notes_per_second=float(peak),
        mean_polyphony=sum(sizes) / len(sizes),
        max_polyphony=float(max(sizes)),
        chord_fraction=sum(1 for s in sizes if s >= 2) / len(sizes),
        mean_gap_seconds=mean_gap,
        median_pitch=median_pitch,
        low_fraction=sum(1 for p in pitches if p < 55) / len(pitches),
        sustain_fraction=sustaining / len(ordered),
        note_count=len(ordered),
    )


def profile_arrangement(song: ShawzinSong, ticks_per_second: int = 16) -> MusicProfile:
    """The same measurements, taken from a finished arrangement."""
    if not song.events:
        return MusicProfile(0, 0, 0, 0, 0, 1.0, 60, 0.0, 0.0, 0)
    total = max(song.duration_seconds(ticks_per_second), 1e-6)
    sizes = [len(e.string) for e in song.events]
    ticks = [e.tick for e in song.events]
    gaps = [(b - a) / ticks_per_second for a, b in zip(ticks, ticks[1:])] or [total]
    peak = 0
    j = 0
    for i in range(len(ticks)):
        while (ticks[i] - ticks[j]) / ticks_per_second > 1.0:
            j += 1
        peak = max(peak, sum(sizes[j : i + 1]))
    return MusicProfile(
        notes_per_second=song.note_count / total,
        peak_notes_per_second=float(peak),
        mean_polyphony=sum(sizes) / len(sizes),
        max_polyphony=float(max(sizes)),
        chord_fraction=sum(1 for e in song.events if e.is_chord_fret or len(e.string) > 1)
        / len(song.events),
        mean_gap_seconds=sum(gaps) / len(gaps),
        median_pitch=60,
        low_fraction=0.0,
        sustain_fraction=0.0,
        note_count=song.note_count,
    )


def _polyphony_capacity(variant: ShawzinVariant) -> int:
    return {"polyphonic": 3, "duophonic": 2, "monophonic": 1}[variant.polyphony]


def recommend_shawzin(
    profile: MusicProfile,
    *,
    song: ShawzinSong | None = None,
    instrument: ShawzinInstrument | None = None,
    prefer_variant: str | None = None,
    top_n: int = 11,
) -> list[ShawzinSuggestion]:
    """Rank the Shawzins for this music, best first, with reasons."""
    base = instrument or load_instrument("dax")
    suggestions: list[ShawzinSuggestion] = []

    for variant in base.variants():
        reasons: list[str] = []
        warnings: list[str] = []
        capacity = _polyphony_capacity(variant)
        score = 0.5

        # -- polyphony: the only dimension that changes what is playable ----
        needed = profile.max_polyphony
        if profile.chord_fraction > 0.12:
            if capacity >= 3:
                score += 0.20
                reasons.append(
                    "Plays all three strings together, so the chords in this "
                    "arrangement actually sound as chords."
                )
            elif capacity == 2:
                score += 0.06
                reasons.append("Two notes can ring together.")
                warnings.append("Three-note chords will lose their lowest voice.")
            else:
                score -= 0.22
                warnings.append(
                    "Monophonic: every chord becomes a fast arpeggio, because each "
                    "new note cuts off the last."
                )
        elif needed <= 1.05:
            # Nothing is lost to a monophonic instrument on a single line.
            score += 0.08
            if capacity == 1:
                reasons.append("The arrangement is a single line, so nothing is lost here.")

        # -- sustain against tempo ------------------------------------------
        # Every Shawzin rings for at least two seconds, so comparing note length
        # against the note gap in absolute terms rates them all the same. What
        # separates them is distance from an *ideal* length for this music:
        # about four notes' worth of ring.
        length = variant.note_length_seconds
        gap = max(profile.mean_gap_seconds, 1e-3)
        ideal = max(1.6, min(14.0, gap * 4.0))
        octaves_off = abs(math.log2(length / ideal))
        score += 0.30 * (max(0.0, 1.0 - octaves_off / 3.2) - 0.5)

        if octaves_off < 0.7:
            reasons.append(
                "Its " + _seconds(length) + " ring suits notes landing every "
                + _seconds(gap) + "."
            )
        elif length > ideal:
            if octaves_off > 1.7:
                warnings.append(
                    "Notes ring for " + _seconds(length) + " but land every "
                    + _seconds(gap) + ", so this will sound muddy."
                )
            else:
                reasons.append("Sustains longer than the music needs, for a lusher reading.")
        elif profile.notes_per_second >= 4.0:
            reasons.append("Short decay keeps a dense arrangement articulate.")
        else:
            reasons.append("Short decay leaves clear space between notes.")

        if profile.peak_notes_per_second >= 8 and length >= 8.0:
            score -= 0.10
            warnings.append("Dense passages plus long sustain means a lot of overlap.")

        # -- character -------------------------------------------------------
        # Each Shawzin imitates a real instrument, and real instruments suit
        # different material.
        character = _CHARACTER.get(variant.id, {})
        density_norm = min(1.0, profile.notes_per_second / 6.0)
        register_norm = max(0.0, min(1.0, (profile.median_pitch - 42) / 40.0))
        affinity = (
            character.get("density", 0.0) * (density_norm - 0.45)
            + character.get("register", 0.0) * (register_norm - 0.45)
            + character.get("chords", 0.0) * (profile.chord_fraction - 0.25)
        )
        score += 0.16 * max(-1.0, min(1.0, affinity * 1.8))
        blurb = character.get("blurb")
        if blurb and affinity > 0.05:
            reasons.append(blurb)

        # -- register --------------------------------------------------------
        if variant.clef == "bass":
            if profile.low_fraction > 0.45 or profile.median_pitch < 52:
                score += 0.16
                reasons.append("A bass instrument for music that lives in the low register.")
            else:
                score -= 0.14
                warnings.append("Bass register: this will sound an octave lower than written.")

        # -- chords vs slap ---------------------------------------------------
        if variant.chord_type == "slap" and profile.chord_fraction > 0.12:
            score -= 0.10
            warnings.append(
                "Combined frets slap the note rather than playing a chord, so the "
                "harmony in this arrangement will not sound."
            )

        # -- tuning -----------------------------------------------------------
        if variant.tuning_cents:
            warnings.append(
                "Tuned " + str(variant.tuning_cents) + " cents sharp, so it will clash "
                "if you play alongside anything else."
            )
            score -= 0.02

        if prefer_variant and variant.id == prefer_variant:
            score += 0.05
            reasons.append("Currently selected.")

        # -- what it would actually cost --------------------------------------
        notes_lost = 0
        if song is not None and capacity < 3:
            for event in song.events:
                notes_lost += max(0, len(event.string) - capacity)
            if notes_lost:
                warnings.append(
                    str(notes_lost) + " notes would not sound on this Shawzin."
                )

        if not reasons:
            reasons.append("A reasonable general-purpose choice for this arrangement.")

        suggestions.append(
            ShawzinSuggestion(
                variant_id=variant.id,
                name=variant.name,
                score=max(0.0, min(1.0, score)),
                polyphony=variant.polyphony,
                timbre=TIMBRES.get(variant.id, ""),
                reasons=reasons,
                warnings=warnings,
                notes_lost=notes_lost,
            )
        )

    suggestions.sort(key=lambda s: (-s.score, s.notes_lost, s.variant_id))
    return suggestions[:top_n]


def _seconds(value: float) -> str:
    if value >= 10:
        return str(int(round(value))) + "s"
    if value >= 1:
        return (f"{value:.1f}").rstrip("0").rstrip(".") + "s"
    return str(int(round(value * 1000))) + "ms"

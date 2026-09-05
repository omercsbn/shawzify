"""Pitch arithmetic. MIDI 60 == C4 throughout the engine."""

from __future__ import annotations

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

MIDDLE_C = 60
A4_MIDI = 69
A4_HZ = 440.0

#: Interval sets used for key estimation and for naming a detected key.
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)


def pitch_class(midi: int) -> int:
    return int(midi) % 12


def octave_of(midi: int) -> int:
    """Scientific pitch octave: MIDI 60 -> 4."""
    return int(midi) // 12 - 1


def note_name(midi: int, *, flats: bool = False) -> str:
    names = FLAT_NAMES if flats else SHARP_NAMES
    return names[pitch_class(midi)] + str(octave_of(midi))


def pitch_class_name(pc: int, *, flats: bool = False) -> str:
    names = FLAT_NAMES if flats else SHARP_NAMES
    return names[int(pc) % 12]


def midi_to_hz(midi: float) -> float:
    return A4_HZ * (2.0 ** ((float(midi) - A4_MIDI) / 12.0))


def hz_to_midi(hz: float) -> float:
    if hz <= 0:
        raise ValueError("Frequency must be positive")
    import math

    return 12.0 * math.log2(hz / A4_HZ) + A4_MIDI


def transpose(midi: int, semitones: int) -> int:
    return int(midi) + int(semitones)


def interval_class(a: int, b: int) -> int:
    """Smallest distance between two pitch classes, 0..6."""
    d = abs(pitch_class(a) - pitch_class(b)) % 12
    return min(d, 12 - d)


def same_pitch_class(a: int, b: int) -> bool:
    return pitch_class(a) == pitch_class(b)


def octave_equivalents(midi: int, low: int, high: int) -> list[int]:
    """Every pitch in ``[low, high]`` sharing ``midi``'s pitch class, low to high."""
    if high < low:
        return []
    pc = pitch_class(midi)
    start = low + ((pc - low) % 12)
    return list(range(start, high + 1, 12))


def parse_note_name(name: str) -> int:
    """Parse e.g. ``F#4``, ``Bb3``, ``C-1`` into a MIDI number."""
    text = name.strip().replace("♯", "#").replace("♭", "b")
    if not text:
        raise ValueError("Empty note name")
    letter = text[0].upper()
    if letter not in "ABCDEFG":
        raise ValueError("Invalid note name: " + name)
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    i = 1
    while i < len(text) and text[i] in "#b":
        base += 1 if text[i] == "#" else -1
        i += 1
    octave_text = text[i:]
    if not octave_text:
        raise ValueError("Note name needs an octave: " + name)
    try:
        octave = int(octave_text)
    except ValueError as exc:
        raise ValueError("Invalid octave in note name: " + name) from exc
    return (octave + 1) * 12 + base


def cents_between(a_midi: float, b_midi: float) -> float:
    return (float(b_midi) - float(a_midi)) * 100.0

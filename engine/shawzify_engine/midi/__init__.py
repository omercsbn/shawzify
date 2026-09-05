"""MIDI input and output."""

from .reader import MidiFileData, choose_melody_track, parse_midi
from .writer import write_midi

__all__ = ["MidiFileData", "parse_midi", "choose_melody_track", "write_midi"]

"""NoteEvent list -> MIDI file. Used for both source and arranged exports."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import mido

from ..common.safety import safe_output_path
from ..music.events import NoteEvent, sort_events

TICKS_PER_BEAT = 480


def write_midi(
    events: Sequence[NoteEvent],
    path: str | Path,
    *,
    bpm: float = 120.0,
    track_name: str = "SHAWZIFY",
    program: int = 105,  # GM 106 "Banjo": a plucked timbre close to the Shawzin
) -> Path:
    out = safe_output_path(path)
    ordered = sort_events(events)
    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name=track_name[:64], time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(max(1.0, bpm)), time=0))
    track.append(mido.Message("program_change", program=max(0, min(127, program)), time=0))

    seconds_per_tick = (60.0 / max(1.0, bpm)) / TICKS_PER_BEAT

    timeline: list[tuple[float, int, int, int]] = []  # seconds, order, note, velocity
    for e in ordered:
        vel = max(1, min(127, int(round(e.velocity * 127))))
        timeline.append((e.start_seconds, 1, e.pitch_midi, vel))
        timeline.append((e.end_seconds, 0, e.pitch_midi, 0))
    timeline.sort(key=lambda t: (t[0], t[1]))

    prev_tick = 0
    for seconds, is_on, note, vel in timeline:
        tick = int(round(seconds / seconds_per_tick))
        delta = max(0, tick - prev_tick)
        prev_tick = tick
        track.append(
            mido.Message(
                "note_on" if is_on else "note_off",
                note=max(0, min(127, note)),
                velocity=vel,
                time=delta,
            )
        )
    mid.save(str(out))
    return out

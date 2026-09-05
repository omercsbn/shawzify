"""MIDI file -> canonical NoteEvent list.

Handles tempo maps (including tempo changes), multiple tracks, note-off vs
zero-velocity note-on, and channel 10 percussion (excluded by default: drums
have no pitch to arrange).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mido

from ..common.errors import MidiParseError
from ..common.safety import sanitize_metadata_text
from ..music.events import NoteEvent, clamp_durations, sort_events

PERCUSSION_CHANNEL = 9  # zero-based channel 10


@dataclass
class MidiTrackInfo:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]
    programs: tuple[int, ...]
    pitch_range: tuple[int, int]
    mean_pitch: float
    is_percussion: bool
    duration: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "noteCount": self.note_count,
            "channels": list(self.channels),
            "programs": list(self.programs),
            "pitchRange": list(self.pitch_range),
            "meanPitch": round(self.mean_pitch, 2),
            "isPercussion": self.is_percussion,
            "durationSeconds": round(self.duration, 3),
        }


@dataclass
class MidiFileData:
    events: list[NoteEvent]
    tracks: list[MidiTrackInfo]
    tempo_bpm: float
    tempo_changes: list[tuple[float, float]]  # (seconds, bpm)
    time_signature: tuple[int, int]
    duration: float
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tempoBpm": round(self.tempo_bpm, 3),
            "tempoChanges": [[round(t, 4), round(b, 3)] for t, b in self.tempo_changes],
            "timeSignature": list(self.time_signature),
            "durationSeconds": round(self.duration, 3),
            "title": self.title,
            "tracks": [t.to_dict() for t in self.tracks],
            "noteCount": len(self.events),
        }


def _ticks_to_seconds_map(mid: mido.MidiFile) -> tuple[list[tuple[int, float, float]], list[tuple[float, float]]]:
    """Build a piecewise tick->seconds map from the merged tempo events.

    Returns ``(segments, tempo_changes)`` where each segment is
    ``(start_tick, start_seconds, seconds_per_tick)``.
    """
    ticks_per_beat = mid.ticks_per_beat or 480
    tempo_events: list[tuple[int, int]] = []
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                tempo_events.append((abs_tick, msg.tempo))
    tempo_events.sort()
    if not tempo_events or tempo_events[0][0] != 0:
        tempo_events.insert(0, (0, 500000))  # MIDI default: 120 BPM

    segments: list[tuple[int, float, float]] = []
    changes: list[tuple[float, float]] = []
    seconds = 0.0
    prev_tick = 0
    prev_spt = tempo_events[0][1] / 1_000_000.0 / ticks_per_beat
    for tick, tempo in tempo_events:
        if tick > prev_tick:
            seconds += (tick - prev_tick) * prev_spt
        spt = tempo / 1_000_000.0 / ticks_per_beat
        segments.append((tick, seconds, spt))
        changes.append((seconds, 60_000_000.0 / tempo))
        prev_tick = tick
        prev_spt = spt
    return segments, changes


def _tick_to_seconds(segments: Sequence[tuple[int, float, float]], tick: int) -> float:
    lo, hi = 0, len(segments) - 1
    while lo < hi:
        mid_i = (lo + hi + 1) // 2
        if segments[mid_i][0] <= tick:
            lo = mid_i
        else:
            hi = mid_i - 1
    start_tick, start_seconds, spt = segments[lo]
    return start_seconds + (tick - start_tick) * spt


def parse_midi(
    path: str | Path,
    *,
    include_percussion: bool = False,
    tracks: Sequence[int] | None = None,
) -> MidiFileData:
    """Read a MIDI file into canonical events."""
    try:
        mid = mido.MidiFile(str(path))
    except (OSError, ValueError, EOFError, IndexError) as exc:
        raise MidiParseError(cause=exc) from exc
    except Exception as exc:  # mido raises bare Exception for malformed data
        raise MidiParseError(cause=exc) from exc

    segments, tempo_changes = _ticks_to_seconds_map(mid)
    time_signature = (4, 4)
    title = sanitize_metadata_text(Path(path).stem)

    events: list[NoteEvent] = []
    infos: list[MidiTrackInfo] = []
    wanted = set(tracks) if tracks is not None else None

    for ti, track in enumerate(mid.tracks):
        abs_tick = 0
        open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
        track_name = ""
        channels: set[int] = set()
        programs: set[int] = set()
        track_events: list[NoteEvent] = []

        for msg in track:
            abs_tick += msg.time
            if msg.type == "track_name":
                track_name = sanitize_metadata_text(msg.name, max_length=80)
                continue
            if msg.type == "time_signature" and ti == 0:
                time_signature = (msg.numerator, msg.denominator)
                continue
            if msg.type == "program_change":
                programs.add(int(msg.program))
                continue
            if msg.type not in ("note_on", "note_off"):
                continue
            channel = int(getattr(msg, "channel", 0))
            channels.add(channel)
            key = (channel, int(msg.note))
            is_on = msg.type == "note_on" and msg.velocity > 0
            if is_on:
                open_notes.setdefault(key, []).append((abs_tick, int(msg.velocity)))
            else:
                pending = open_notes.get(key)
                if not pending:
                    continue
                start_tick, velocity = pending.pop(0)
                start = _tick_to_seconds(segments, start_tick)
                end = _tick_to_seconds(segments, abs_tick)
                track_events.append(
                    NoteEvent(
                        pitch_midi=int(msg.note),
                        start_seconds=start,
                        duration_seconds=max(0.01, end - start),
                        velocity=velocity / 127.0,
                        confidence=1.0,
                        source="midi:track" + str(ti) + (" " + track_name if track_name else ""),
                        voice=ti,
                    )
                )
        # Notes left hanging at end-of-track get a nominal length.
        for (_channel, note), pending in open_notes.items():
            for start_tick, velocity in pending:
                start = _tick_to_seconds(segments, start_tick)
                track_events.append(
                    NoteEvent(note, start, 0.25, velocity / 127.0, 1.0,
                              "midi:track" + str(ti), ti)
                )

        is_perc = PERCUSSION_CHANNEL in channels and len(channels) == 1
        pitches = [e.pitch_midi for e in track_events]
        infos.append(
            MidiTrackInfo(
                index=ti,
                name=track_name or ("Track " + str(ti)),
                note_count=len(track_events),
                channels=tuple(sorted(channels)),
                programs=tuple(sorted(programs)),
                pitch_range=(min(pitches), max(pitches)) if pitches else (0, 0),
                mean_pitch=sum(pitches) / len(pitches) if pitches else 0.0,
                is_percussion=is_perc,
                duration=max((e.end_seconds for e in track_events), default=0.0),
            )
        )
        if wanted is not None and ti not in wanted:
            continue
        if is_perc and not include_percussion:
            continue
        events.extend(track_events)

    if not events and any(i.note_count for i in infos):
        # Every note was filtered out (percussion-only file, or a track filter
        # that matched nothing) -- fall back to everything rather than fail.
        for ti, track_info in enumerate(infos):
            if track_info.note_count:
                events.extend(
                    e for e in _reparse_track(mid, segments, ti)
                )

    events = clamp_durations(sort_events(events))
    bpm = tempo_changes[0][1] if tempo_changes else 120.0
    duration = max((e.end_seconds for e in events), default=0.0)
    return MidiFileData(
        events=events,
        tracks=infos,
        tempo_bpm=bpm,
        tempo_changes=tempo_changes,
        time_signature=time_signature,
        duration=duration,
        title=title,
    )


def _reparse_track(
    mid: mido.MidiFile, segments: Sequence[tuple[int, float, float]], ti: int
) -> list[NoteEvent]:
    track = mid.tracks[ti]
    abs_tick = 0
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    out: list[NoteEvent] = []
    for msg in track:
        abs_tick += msg.time
        if msg.type not in ("note_on", "note_off"):
            continue
        channel = int(getattr(msg, "channel", 0))
        key = (channel, int(msg.note))
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes.setdefault(key, []).append((abs_tick, int(msg.velocity)))
        else:
            pending = open_notes.get(key)
            if not pending:
                continue
            start_tick, velocity = pending.pop(0)
            start = _tick_to_seconds(segments, start_tick)
            end = _tick_to_seconds(segments, abs_tick)
            out.append(
                NoteEvent(int(msg.note), start, max(0.01, end - start), velocity / 127.0,
                          1.0, "midi:track" + str(ti), ti)
            )
    return out


def choose_melody_track(data: MidiFileData) -> int | None:
    """Heuristic AUTO melody-track pick.

    Favours a track that is mostly monophonic, sits in a singable register, has
    a decent share of the notes, and moves (a sustained pad is not a melody).
    """
    scored: list[tuple[float, int]] = []
    total_notes = sum(t.note_count for t in data.tracks) or 1
    by_track: dict[int, list[NoteEvent]] = {}
    for e in data.events:
        by_track.setdefault(e.voice, []).append(e)

    for info in data.tracks:
        if info.is_percussion or info.note_count < 4:
            continue
        evs = by_track.get(info.index, [])
        if not evs:
            continue
        from ..music.events import NoteSequence

        seq = NoteSequence(evs)
        mono = 1.0 / max(1.0, seq.mean_polyphony())
        register = max(0.0, 1.0 - abs(info.mean_pitch - 71) / 30.0)  # around B4
        share = min(1.0, info.note_count / total_notes * 3.0)
        movement = 0.0
        pitches = [e.pitch_midi for e in evs]
        if len(pitches) > 1:
            steps = [abs(b - a) for a, b in zip(pitches, pitches[1:])]
            moving = sum(1 for s in steps if s > 0) / len(steps)
            movement = moving * max(0.0, 1.0 - (sum(steps) / len(steps)) / 12.0)
        name_bonus = 0.15 if any(
            k in info.name.lower() for k in ("melody", "lead", "vocal", "voice", "solo", "tune")
        ) else 0.0
        bass_penalty = 0.25 if "bass" in info.name.lower() or info.mean_pitch < 50 else 0.0
        score = 0.3 * mono + 0.25 * register + 0.2 * share + 0.25 * movement + name_bonus - bass_penalty
        scored.append((score, info.index))

    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]

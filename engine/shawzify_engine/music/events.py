"""The canonical note representation shared by every input path.

MIDI files, audio transcription, and microphone input all produce ``NoteEvent``
lists. Nothing downstream of this module knows where the notes came from.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from .pitch import note_name, pitch_class


@dataclass(frozen=True, slots=True)
class NoteEvent:
    """One musical note on an absolute seconds timeline."""

    pitch_midi: int
    start_seconds: float
    duration_seconds: float
    velocity: float = 0.8  # 0..1
    confidence: float = 1.0  # 0..1
    source: str = "unknown"  # e.g. "midi:track 2", "audio:vocals"
    voice: int = 0  # optional grouping (MIDI track / stem index)

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds

    @property
    def pitch_name(self) -> str:
        return note_name(self.pitch_midi)

    @property
    def pitch_class(self) -> int:
        return pitch_class(self.pitch_midi)

    def shifted(self, semitones: int) -> NoteEvent:
        return replace(self, pitch_midi=self.pitch_midi + int(semitones))

    def moved(self, seconds: float) -> NoteEvent:
        return replace(self, start_seconds=self.start_seconds + float(seconds))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pitchMidi": self.pitch_midi,
            "pitchName": self.pitch_name,
            "startSeconds": round(self.start_seconds, 6),
            "durationSeconds": round(self.duration_seconds, 6),
            "velocity": round(self.velocity, 4),
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "voice": self.voice,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> NoteEvent:
        return NoteEvent(
            pitch_midi=int(d["pitchMidi"]),
            start_seconds=float(d["startSeconds"]),
            duration_seconds=float(d.get("durationSeconds", 0.25)),
            velocity=float(d.get("velocity", 0.8)),
            confidence=float(d.get("confidence", 1.0)),
            source=str(d.get("source", "unknown")),
            voice=int(d.get("voice", 0)),
        )


@dataclass
class NoteSequence:
    """An ordered, immutable-ish bag of ``NoteEvent`` with useful statistics."""

    events: list[NoteEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.events = sort_events(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[NoteEvent]:
        return iter(self.events)

    def __getitem__(self, index: int) -> NoteEvent:
        return self.events[index]

    @property
    def duration(self) -> float:
        return max((e.end_seconds for e in self.events), default=0.0)

    @property
    def start(self) -> float:
        return min((e.start_seconds for e in self.events), default=0.0)

    @property
    def pitch_range(self) -> tuple[int, int]:
        if not self.events:
            return (0, 0)
        pitches = [e.pitch_midi for e in self.events]
        return (min(pitches), max(pitches))

    def notes_per_second(self) -> float:
        span = self.duration - self.start
        return len(self.events) / span if span > 1e-6 else 0.0

    def max_polyphony(self, tolerance: float = 0.03) -> int:
        """Largest number of notes whose onsets fall inside ``tolerance``."""
        best = 0
        i = 0
        events = self.events
        while i < len(events):
            j = i
            while j < len(events) and events[j].start_seconds - events[i].start_seconds <= tolerance:
                j += 1
            best = max(best, j - i)
            i += 1
        return best

    def mean_polyphony(self, tolerance: float = 0.03) -> float:
        groups = list(group_by_onset(self.events, tolerance))
        if not groups:
            return 0.0
        return sum(len(g) for g in groups) / len(groups)

    def transposed(self, semitones: int) -> NoteSequence:
        return NoteSequence([e.shifted(semitones) for e in self.events])

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    @staticmethod
    def from_list(items: Iterable[dict[str, Any]]) -> NoteSequence:
        return NoteSequence([NoteEvent.from_dict(d) for d in items])


def sort_events(events: Iterable[NoteEvent]) -> list[NoteEvent]:
    """Deterministic total order: time, then pitch, then source."""
    return sorted(events, key=lambda e: (e.start_seconds, e.pitch_midi, e.voice, e.source))


def group_by_onset(
    events: Iterable[NoteEvent], tolerance: float = 0.03
) -> list[list[NoteEvent]]:
    """Cluster events into simultaneity groups.

    A group is closed once a note starts more than ``tolerance`` after the
    group's first onset, which keeps a rolled chord together without swallowing
    the next beat.
    """
    ordered = sort_events(events)
    groups: list[list[NoteEvent]] = []
    current: list[NoteEvent] = []
    anchor = 0.0
    for ev in ordered:
        if not current:
            current = [ev]
            anchor = ev.start_seconds
            continue
        if ev.start_seconds - anchor <= tolerance:
            current.append(ev)
        else:
            groups.append(current)
            current = [ev]
            anchor = ev.start_seconds
    if current:
        groups.append(current)
    return groups


def merge_overlapping_same_pitch(
    events: Iterable[NoteEvent], gap: float = 0.01
) -> list[NoteEvent]:
    """Fuse duplicate/overlapping notes of identical pitch into single events.

    Polyphonic transcribers sometimes emit a held note as several fragments.
    """
    by_pitch: dict[int, list[NoteEvent]] = {}
    for ev in sort_events(events):
        by_pitch.setdefault(ev.pitch_midi, []).append(ev)
    merged: list[NoteEvent] = []
    for pitch, group in by_pitch.items():
        cur = group[0]
        for nxt in group[1:]:
            if nxt.start_seconds <= cur.end_seconds + gap:
                end = max(cur.end_seconds, nxt.end_seconds)
                cur = replace(
                    cur,
                    duration_seconds=end - cur.start_seconds,
                    velocity=max(cur.velocity, nxt.velocity),
                    confidence=max(cur.confidence, nxt.confidence),
                )
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
        del pitch
    return sort_events(merged)


def clamp_durations(
    events: Iterable[NoteEvent], minimum: float = 0.03, maximum: float = 8.0
) -> list[NoteEvent]:
    out = []
    for ev in events:
        d = min(max(ev.duration_seconds, minimum), maximum)
        out.append(replace(ev, duration_seconds=d) if d != ev.duration_seconds else ev)
    return sort_events(out)

"""Splitting an over-long arrangement into importable parts.

Nothing is ever silently truncated. When a song exceeds the 4-minute / 1000-note
limits, this finds cut points at musical boundaries -- phrase gaps first, then
bar lines, then the largest available rest -- and rebases each part to tick 0 so
every part imports and plays correctly on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .instrument import ShawzinInstrument, default_instrument
from .songcode import ShawzinEvent, ShawzinSong, encode


@dataclass
class SongPart:
    index: int
    song: ShawzinSong
    start_tick: int
    end_tick: int
    code: str

    @property
    def note_count(self) -> int:
        return self.song.note_count

    def to_dict(self, ticks_per_second: int = 16) -> dict[str, Any]:
        return {
            "index": self.index,
            "code": self.code,
            "noteCount": self.note_count,
            "eventCount": len(self.song.events),
            "startSeconds": round(self.start_tick / ticks_per_second, 3),
            "endSeconds": round(self.end_tick / ticks_per_second, 3),
            "durationSeconds": round((self.end_tick - self.start_tick) / ticks_per_second, 3),
        }


def needs_split(song: ShawzinSong, instrument: ShawzinInstrument | None = None) -> tuple[bool, list[str]]:
    """Whether the song exceeds a hard limit, and which ones."""
    inst = instrument or default_instrument()
    fmt = inst.format
    reasons: list[str] = []
    if song.events:
        span = song.end_tick - song.events[0].tick
        if span > fmt.max_ticks:
            reasons.append(
                "This arrangement is "
                + str(round(span / fmt.ticks_per_second / 60.0, 1))
                + " minutes long; the Shawzin limit is "
                + str(fmt.max_song_seconds // 60)
                + " minutes."
            )
    if song.note_count > fmt.max_notes:
        reasons.append(
            "This arrangement has "
            + str(song.note_count)
            + " notes; the Shawzin limit is "
            + str(fmt.max_notes)
            + "."
        )
    return (bool(reasons), reasons)


def _gap_scores(
    events: Sequence[ShawzinEvent], *, bpm: float | None, ticks_per_second: int
) -> list[tuple[int, float]]:
    """For each boundary between consecutive events, how good a cut it makes."""
    scores: list[tuple[int, float]] = []
    bar_ticks = None
    if bpm and bpm > 0:
        bar_ticks = (60.0 / bpm) * 4.0 * ticks_per_second
    for i in range(1, len(events)):
        gap = events[i].tick - events[i - 1].tick
        score = min(1.0, gap / (ticks_per_second * 1.5))  # a 1.5 s rest is ideal
        if bar_ticks and bar_ticks > 0:
            off = abs((events[i].tick / bar_ticks) - round(events[i].tick / bar_ticks))
            score += 0.35 * max(0.0, 1.0 - off * 6.0)
        scores.append((i, score))
    return scores


def split_arrangement(
    song: ShawzinSong,
    instrument: ShawzinInstrument | None = None,
    *,
    bpm: float | None = None,
    max_notes: int | None = None,
    max_ticks: int | None = None,
) -> list[SongPart]:
    """Split into as few parts as possible, cutting at the best musical seam.

    Each part is rebased so its first event lands at tick 0.
    """
    inst = instrument or default_instrument()
    fmt = inst.format
    note_limit = max_notes if max_notes is not None else fmt.max_notes
    tick_limit = max_ticks if max_ticks is not None else fmt.max_ticks
    events = list(song.events)
    if not events:
        return []

    scores = dict(_gap_scores(events, bpm=bpm, ticks_per_second=fmt.ticks_per_second))
    parts: list[SongPart] = []
    start = 0
    while start < len(events):
        base_tick = events[start].tick
        # Furthest index that still fits both limits.
        hard_end = start
        notes = 0
        for i in range(start, len(events)):
            notes += len(events[i].string)
            if notes > note_limit or events[i].tick - base_tick > tick_limit:
                break
            hard_end = i
        if hard_end < start:
            hard_end = start  # a single event always fits
        end = hard_end + 1

        if end < len(events):
            # Look back over the last 20% of the part for the best seam.
            window_start = max(start + 1, start + int((end - start) * 0.8))
            best_i, best_score = end, -1.0
            for i in range(window_start, end + 1):
                s = scores.get(i, 0.0)
                if s > best_score:
                    best_score, best_i = s, i
            if best_score > 0.15:
                end = best_i

        chunk = events[start:end]
        if not chunk:
            break
        offset = chunk[0].tick
        rebased = [
            ShawzinEvent(e.tick - offset, e.fret, e.string, e.alt_fret, e.alt_string)
            for e in chunk
        ]
        part_song = ShawzinSong(scale_id=song.scale_id, events=rebased)
        parts.append(
            SongPart(
                index=len(parts),
                song=part_song,
                start_tick=chunk[0].tick,
                end_tick=chunk[-1].tick,
                code=encode(part_song, inst, zero_base=False),
            )
        )
        start = end
    return parts

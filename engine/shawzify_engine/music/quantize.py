"""Rhythm quantization.

Grid choice is data-driven: AUTO scores each candidate subdivision by how well
the actual onsets line up with it, so a swung or triplet-heavy piece is not
forced onto a straight sixteenth grid.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import replace

from .events import NoteEvent, sort_events

#: Grid label -> subdivisions per beat.
GRIDS: dict[str, float] = {
    "1/1": 0.25,
    "1/2": 0.5,
    "1/4": 1.0,
    "1/8": 2.0,
    "1/8t": 3.0,
    "1/16": 4.0,
    "1/16t": 6.0,
    "1/32": 8.0,
}

GRID_ORDER = ("1/4", "1/8", "1/8t", "1/16", "1/16t", "1/32")


def grid_seconds(bpm: float, grid: str) -> float:
    """Seconds per grid step."""
    if grid not in GRIDS:
        raise ValueError("Unknown quantization grid: " + str(grid))
    beat = 60.0 / max(float(bpm), 1e-6)
    return beat / GRIDS[grid]


def grid_alignment_score(
    events: Sequence[NoteEvent], bpm: float, grid: str, origin: float = 0.0
) -> float:
    """Mean alignment of onsets to a grid, 1.0 = perfect, 0.0 = worst possible.

    Finer grids trivially fit better, so the caller applies a complexity
    penalty; this function reports raw fit only.
    """
    if not events:
        return 0.0
    step = grid_seconds(bpm, grid)
    if step <= 0:
        return 0.0
    total = 0.0
    for ev in events:
        offset = (ev.start_seconds - origin) / step
        err = abs(offset - round(offset))  # 0..0.5
        total += 1.0 - (err * 2.0)
    return total / len(events)


def estimate_grid_origin(events: Sequence[NoteEvent], bpm: float, grid: str) -> float:
    """Find the grid phase that best fits the onsets (circular mean)."""
    if not events:
        return 0.0
    step = grid_seconds(bpm, grid)
    sin_sum = 0.0
    cos_sum = 0.0
    for ev in events:
        angle = 2.0 * math.pi * ((ev.start_seconds % step) / step)
        sin_sum += math.sin(angle)
        cos_sum += math.cos(angle)
    mean_angle = math.atan2(sin_sum, cos_sum)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    return (mean_angle / (2.0 * math.pi)) * step


def choose_grid(
    events: Sequence[NoteEvent],
    bpm: float,
    candidates: Iterable[str] = GRID_ORDER,
    *,
    ticks_per_second: int | None = None,
    min_ticks_per_step: float = 1.5,
) -> tuple[str, float, float]:
    """Pick the coarsest grid that still explains the timing.

    Returns ``(grid, score, origin)``. Two things keep AUTO from always landing
    on 1/32: a small penalty per extra subdivision, and -- more importantly --
    a floor on the grid step. Quantizing finer than the Shawzin's own 1/16
    second tick cannot survive encoding, so those grids are not considered.
    """
    usable: list[str] = []
    floor = (min_ticks_per_step / ticks_per_second) if ticks_per_second else 0.0
    for grid in candidates:
        if floor > 0 and grid_seconds(bpm, grid) < floor:
            continue
        usable.append(grid)
    if not usable:
        usable = ["1/4"]

    # Distinct onset moments -- a grid that merges two of these has destroyed a
    # rhythm, however well the survivors line up.
    onsets = sorted({round(e.start_seconds, 4) for e in events})
    distinct = len(onsets) or 1

    best: tuple[str, float, float] = (usable[0], 0.0, 0.0)
    best_value = -1e9
    for grid in usable:
        origin = estimate_grid_origin(events, bpm, grid)
        raw = grid_alignment_score(events, bpm, grid, origin)
        step = grid_seconds(bpm, grid)
        slots = len({round((t - origin) / step) for t in onsets})
        keep = slots / distinct
        # log2 of subdivisions per beat: 1/4 -> 0, 1/8 -> 1, 1/16 -> 2 ...
        complexity = math.log2(max(GRIDS[grid], 1.0))
        value = 0.6 * raw + 0.4 * keep - 0.02 * complexity
        if value > best_value:
            best_value = value
            best = (grid, raw, origin)
    return best


def quantize_events(
    events: Sequence[NoteEvent],
    bpm: float,
    grid: str,
    *,
    strength: float = 1.0,
    origin: float | None = None,
    quantize_durations: bool = True,
    min_duration: float = 0.03,
) -> list[NoteEvent]:
    """Pull onsets toward the grid by ``strength`` (0 = off, 1 = snap fully)."""
    if not events or strength <= 0.0:
        return sort_events(events)
    step = grid_seconds(bpm, grid)
    if step <= 0:
        return sort_events(events)
    if origin is None:
        origin = estimate_grid_origin(events, bpm, grid)
    s = max(0.0, min(1.0, float(strength)))
    out: list[NoteEvent] = []
    for ev in events:
        rel = ev.start_seconds - origin
        snapped = round(rel / step) * step + origin
        new_start = ev.start_seconds + (snapped - ev.start_seconds) * s
        new_start = max(0.0, new_start)
        new_duration = ev.duration_seconds
        if quantize_durations:
            steps = max(1.0, round(ev.duration_seconds / step))
            target = steps * step
            new_duration = ev.duration_seconds + (target - ev.duration_seconds) * s
        out.append(
            replace(
                ev,
                start_seconds=new_start,
                duration_seconds=max(min_duration, new_duration),
            )
        )
    return sort_events(out)


def snap_to_ticks(
    events: Sequence[NoteEvent], ticks_per_second: int, *, min_gap_ticks: int = 0
) -> list[tuple[int, NoteEvent]]:
    """Map events onto the Shawzin's fixed 1/16 s tick grid.

    ``min_gap_ticks`` pushes a repeated note forward so two plucks of the same
    string do not collapse onto one tick.
    """
    ordered = sort_events(events)
    result: list[tuple[int, NoteEvent]] = []
    last_by_pitch: dict[int, int] = {}
    for ev in ordered:
        tick = int(round(ev.start_seconds * ticks_per_second))
        if min_gap_ticks > 0:
            prev = last_by_pitch.get(ev.pitch_midi)
            if prev is not None and tick - prev < min_gap_ticks:
                tick = prev + min_gap_ticks
        last_by_pitch[ev.pitch_midi] = tick
        result.append((max(0, tick), ev))
    result.sort(key=lambda pair: (pair[0], pair[1].pitch_midi))
    return result


def timing_error_seconds(
    original: Sequence[NoteEvent], quantized: Sequence[NoteEvent]
) -> tuple[float, float]:
    """``(mean, max)`` absolute onset shift between two aligned event lists."""
    if not original or len(original) != len(quantized):
        return (0.0, 0.0)
    errs = [abs(a.start_seconds - b.start_seconds) for a, b in zip(original, quantized)]
    return (sum(errs) / len(errs), max(errs))

"""Drift-free event scheduling.

``sleep(note.duration)`` accumulates every scheduling error, so after two
minutes a song is audibly behind. Instead every event carries an *absolute*
target time relative to a monotonic start, the scheduler sleeps until that
target, and the residual error of each event is measured and reported.

Sleeping is done in two parts: a coarse ``sleep`` down to a small margin, then
a short spin. On Windows the timer granularity is ~15 ms by default, which the
spin absorbs; the scheduler also asks for 1 ms granularity when it can.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScheduledEvent:
    """Something to do at ``at_seconds`` after playback starts."""

    at_seconds: float
    payload: Any


@dataclass
class SchedulerStats:
    count: int = 0
    mean_error: float = 0.0
    max_error: float = 0.0
    late_events: int = 0
    errors: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "meanErrorMs": round(self.mean_error * 1000.0, 3),
            "maxErrorMs": round(self.max_error * 1000.0, 3),
            "lateEvents": self.late_events,
        }


def _begin_high_resolution_timer() -> Callable[[], None]:
    """Ask Windows for 1 ms timer granularity; returns a restore callable."""
    try:
        import ctypes
        import sys

        if sys.platform != "win32":
            return lambda: None
        winmm = ctypes.WinDLL("winmm")
        if winmm.timeBeginPeriod(1) != 0:
            return lambda: None
        return lambda: winmm.timeEndPeriod(1)
    except Exception:  # noqa: BLE001
        return lambda: None


class EventScheduler:
    """Runs a sorted event list against a monotonic clock."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        spin_margin: float = 0.0015,
    ) -> None:
        self.clock = clock or time.perf_counter
        self._sleep = sleep or time.sleep
        self.spin_margin = spin_margin
        self.stats = SchedulerStats()

    def run(
        self,
        events: Sequence[ScheduledEvent],
        handler: Callable[[ScheduledEvent, float], None],
        *,
        offset_seconds: float = 0.0,
        should_stop: Callable[[], bool] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> SchedulerStats:
        """Fire each event as close to its target as the platform allows.

        ``offset_seconds`` shifts the whole schedule, which is how the latency
        calibration setting is applied.
        """
        ordered = sorted(events, key=lambda e: e.at_seconds)
        self.stats = SchedulerStats()
        if not ordered:
            return self.stats

        restore = _begin_high_resolution_timer()
        start = self.clock()
        try:
            for event in ordered:
                if should_stop is not None and should_stop():
                    break
                target = start + event.at_seconds + offset_seconds
                self._wait_until(target, should_stop)
                if should_stop is not None and should_stop():
                    break
                actual = self.clock()
                error = actual - target
                self.stats.count += 1
                self.stats.errors.append(error)
                if error > 0.002:
                    self.stats.late_events += 1
                try:
                    handler(event, actual - start)
                except Exception as exc:  # noqa: BLE001
                    if on_error is None:
                        raise
                    on_error(exc)
        finally:
            restore()

        if self.stats.errors:
            abs_errors = [abs(e) for e in self.stats.errors]
            self.stats.mean_error = sum(abs_errors) / len(abs_errors)
            self.stats.max_error = max(abs_errors)
        return self.stats

    def _wait_until(self, target: float, should_stop: Callable[[], bool] | None) -> None:
        while True:
            remaining = target - self.clock()
            if remaining <= 0:
                return
            if should_stop is not None and should_stop():
                return
            if remaining > self.spin_margin:
                # Leave the margin for the spin, and cap each sleep so a stop
                # request is noticed promptly.
                self._sleep(min(remaining - self.spin_margin, 0.05))
            else:
                # Busy-wait the last couple of milliseconds.
                while self.clock() < target:
                    if should_stop is not None and should_stop():
                        return


def build_schedule(
    items: Iterable[tuple[float, Any]], *, lead_in: float = 0.0
) -> list[ScheduledEvent]:
    return [ScheduledEvent(t + lead_in, payload) for t, payload in items]

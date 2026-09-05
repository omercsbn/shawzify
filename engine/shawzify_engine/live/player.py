"""Live Warframe playback.

Safety rules, enforced here rather than documented and hoped for:

* Warframe must be the *focused* window before the countdown starts.
* Focus is re-checked before every event; losing focus stops playback and
  releases every held key immediately.
* A stop request is honoured between any two events.
* Only ordinary user-space key simulation is used (see ``input_sink``). Nothing
  reads or writes the game's memory, hooks it, or touches anti-cheat.

Everything except the Windows-specific window lookup is testable with
``RecordingInputSink`` plus a stub focus checker.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import LivePlaybackError
from ..shawzin.instrument import ShawzinInstrument, default_instrument
from ..shawzin.songcode import ShawzinEvent, ShawzinSong
from .input_sink import InputSink, RecordingInputSink, select_sink
from .keymap import WarframeKeymap
from .scheduler import EventScheduler, ScheduledEvent, SchedulerStats

WARFRAME_WINDOW_TITLES = ("Warframe",)


@dataclass
class WindowInfo:
    found: bool
    focused: bool
    title: str | None = None
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"found": self.found, "focused": self.focused, "title": self.title, "pid": self.pid}


def find_warframe_window() -> WindowInfo:
    """Look for the Warframe window and whether it currently has focus."""
    if sys.platform != "win32":
        return WindowInfo(False, False)
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = None
        for title in WARFRAME_WINDOW_TITLES:
            handle = user32.FindWindowW(None, title)
            if handle:
                hwnd = handle
                break
        if not hwnd:
            return WindowInfo(False, False)
        foreground = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return WindowInfo(True, foreground == hwnd, buf.value, int(pid.value))
    except Exception:  # noqa: BLE001 - never let detection crash the app
        return WindowInfo(False, False)


@dataclass
class PlaybackStatus:
    state: str  # idle | countdown | playing | stopped | finished | error
    position_seconds: float = 0.0
    total_seconds: float = 0.0
    countdown: int | None = None
    current_position: str | None = None  # Shawzin fret-string
    current_notes: list[str] = field(default_factory=list)
    message: str | None = None
    stats: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "positionSeconds": round(self.position_seconds, 3),
            "totalSeconds": round(self.total_seconds, 3),
            "countdown": self.countdown,
            "currentPosition": self.current_position,
            "currentNotes": self.current_notes,
            "message": self.message,
            "stats": self.stats,
        }


StatusCallback = Callable[[PlaybackStatus], None]
FocusCheck = Callable[[], bool]
WindowCheck = Callable[[], WindowInfo]


class ShawzinLivePlayer:
    """Plays a Shawzin song into the focused Warframe window."""

    def __init__(
        self,
        *,
        sink: InputSink | None = None,
        keymap: WarframeKeymap | None = None,
        instrument: ShawzinInstrument | None = None,
        focus_check: FocusCheck | None = None,
        window_check: WindowCheck | None = None,
        scheduler: EventScheduler | None = None,
        require_focus: bool = True,
    ) -> None:
        self.sink = sink or select_sink()
        self.keymap = keymap or WarframeKeymap.load()
        self.instrument = instrument or default_instrument()
        self.window_check = window_check or find_warframe_window
        self.focus_check = focus_check or (lambda: self.window_check().focused)
        self.scheduler = scheduler or EventScheduler()
        self.require_focus = require_focus
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held_frets: list[str] = []
        self.last_stats: SchedulerStats | None = None

    # -- control --------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """Stop immediately and release every key. Safe to call at any time."""
        self._stop.set()
        self._release_frets()
        self.sink.release_all()

    def preflight(self) -> dict[str, Any]:
        """What the UI needs to decide whether PLAY IN WARFRAME can be offered."""
        window = self.window_check()
        problems = self.keymap.validate()
        return {
            "window": window.to_dict(),
            "sink": self.sink.id,
            "sinkAvailable": self.sink.available(),
            "keymapProblems": problems,
            "canPlay": (window.focused or not self.require_focus)
            and self.sink.available()
            and not problems,
        }

    # -- playback -------------------------------------------------------

    def play(
        self,
        song: ShawzinSong,
        *,
        status: StatusCallback | None = None,
        blocking: bool = True,
        countdown: bool = True,
    ) -> SchedulerStats | None:
        if self.playing:
            raise LivePlaybackError("A performance is already running.")
        if self.require_focus and not self.focus_check():
            raise LivePlaybackError(
                "Warframe needs to be the active window before playback can start.",
                hint="Alt-Tab to Warframe, equip the Shawzin emote, then press play.",
            )
        problems = self.keymap.validate()
        if problems:
            raise LivePlaybackError(
                "The Warframe key bindings need attention: " + problems[0],
                hint="Open Settings > Warframe Key Bindings.",
            )
        self._stop.clear()
        if blocking:
            return self._run(song, status, countdown)
        self._thread = threading.Thread(
            target=self._run, args=(song, status, countdown), daemon=True
        )
        self._thread.start()
        return None

    def _run(
        self, song: ShawzinSong, status: StatusCallback | None, countdown: bool
    ) -> SchedulerStats:
        tps = self.instrument.format.ticks_per_second
        scale = self.instrument.scale(song.scale_id)
        timing = self.keymap.timing

        def emit(s: PlaybackStatus) -> None:
            if status is not None:
                status(s)

        total = song.duration_seconds(tps)
        if countdown and timing.countdown_seconds > 0:
            steps = int(timing.countdown_seconds)
            for i in range(steps, 0, -1):
                if self._stop.is_set():
                    emit(PlaybackStatus("stopped", 0.0, total, message="Cancelled"))
                    return SchedulerStats()
                emit(PlaybackStatus("countdown", 0.0, total, countdown=i))
                time.sleep(1.0)
            emit(PlaybackStatus("countdown", 0.0, total, countdown=0, message="PLAY"))

        events = [
            ScheduledEvent(ev.tick / float(tps), ev)
            for ev in sorted(song.events, key=lambda e: e.tick)
        ]

        def should_stop() -> bool:
            if self._stop.is_set():
                return True
            if self.require_focus and not self.focus_check():
                self._stop.set()
                emit(
                    PlaybackStatus(
                        "stopped",
                        0.0,
                        total,
                        message="Playback stopped: Warframe is no longer the active window.",
                    )
                )
                return True
            return False

        def handle(event: ScheduledEvent, elapsed: float) -> None:
            ev: ShawzinEvent = event.payload
            names = []
            for ch in ev.string:
                position = ev.fret + "-" + ch
                if ev.is_chord_fret:
                    chord = scale.chord_at(position)
                    names.append(chord.name if chord else position)
                else:
                    note = scale.note_at(position)
                    names.append(note.name if note else position)
            self._play_event(ev)
            emit(
                PlaybackStatus(
                    "playing",
                    elapsed,
                    total,
                    current_position=ev.position,
                    current_notes=names,
                )
            )

        emit(PlaybackStatus("playing", 0.0, total))
        try:
            stats = self.scheduler.run(
                events,
                handle,
                offset_seconds=timing.playback_offset_ms / 1000.0,
                should_stop=should_stop,
            )
        finally:
            self._release_frets()
            self.sink.release_all()
        self.last_stats = stats
        state = "stopped" if self._stop.is_set() else "finished"
        emit(PlaybackStatus(state, total, total, stats=stats.to_dict()))
        return stats

    # -- key mechanics --------------------------------------------------

    def _release_frets(self) -> None:
        for key in reversed(self._held_frets):
            self.sink.key_up(key)
        self._held_frets = []

    def _play_event(self, ev: ShawzinEvent) -> None:
        """Set the fret state, then pluck the strings.

        Fret keys are *held*, exactly as a player holds them, and only changed
        when the next event needs a different position -- that avoids a
        release/press pair between every note of a run.
        """
        timing = self.keymap.timing
        wanted = self.keymap.fret_keys(ev.fret)
        if wanted != self._held_frets:
            self._release_frets()
            for key in wanted:
                self.sink.key_down(key)
            self._held_frets = list(wanted)
            if wanted:
                self.sink.sleep(timing.fret_to_string_ms / 1000.0)

        hold = timing.key_hold_ms / 1000.0
        gap = timing.inter_string_ms / 1000.0
        keys = [self.keymap.string_key(ch) for ch in ev.string]
        # Press all strings of a strum, then release them, so they sound together.
        for i, key in enumerate(keys):
            self.sink.key_down(key)
            if gap > 0 and i < len(keys) - 1:
                self.sink.sleep(gap)
        if hold > 0:
            self.sink.sleep(hold)
        for key in keys:
            self.sink.key_up(key)


def dry_run(
    song: ShawzinSong,
    *,
    instrument: ShawzinInstrument | None = None,
    keymap: WarframeKeymap | None = None,
) -> tuple[list[tuple[str, float]], SchedulerStats]:
    """Play a song into a recording sink with a virtual clock.

    Used by the tests and by the CLI's ``--dry-run`` to verify the key sequence
    and the scheduler's timing without Warframe running.
    """
    sink = RecordingInputSink(simulate_sleep=True)
    clock_state = {"t": 0.0}

    def clock() -> float:
        return clock_state["t"]

    def sleep(seconds: float) -> None:
        clock_state["t"] += max(0.0, seconds)

    sink._clock = clock  # virtual clock shared with the scheduler
    sink._virtual_time = 0.0

    class _VirtualSink(RecordingInputSink):
        def now(self) -> float:
            return clock_state["t"]

        def sleep(self, seconds: float) -> None:
            clock_state["t"] += max(0.0, seconds)

    vsink = _VirtualSink()
    scheduler = EventScheduler(clock=clock, sleep=sleep, spin_margin=0.0)
    player = ShawzinLivePlayer(
        sink=vsink,
        keymap=keymap or WarframeKeymap(),
        instrument=instrument or default_instrument(),
        focus_check=lambda: True,
        scheduler=scheduler,
        require_focus=False,
    )
    stats = player.play(song, blocking=True, countdown=False)
    return (vsink.presses(), stats or SchedulerStats())

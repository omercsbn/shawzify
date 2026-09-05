"""Where simulated key presses go.

Splitting this out is what makes live playback testable: the scheduler and the
whole note-to-key layer are exercised against ``RecordingInputSink`` with no
Warframe, no Windows API, and no real keyboard involved.

The Windows sink uses ordinary user-space ``SendInput``. It behaves exactly like
an external MIDI keyboard or a macro pad: no injection, no memory access, no
hooking of the game. If Warframe is not the focused window, nothing is sent.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KeyAction:
    key: str
    down: bool
    monotonic: float

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "down": self.down, "at": round(self.monotonic, 6)}


class InputSink(ABC):
    """Receives key-down / key-up requests."""

    id = "base"

    @abstractmethod
    def key_down(self, key: str) -> None:
        ...

    @abstractmethod
    def key_up(self, key: str) -> None:
        ...

    def tap(self, key: str, hold_seconds: float = 0.012) -> None:
        self.key_down(key)
        if hold_seconds > 0:
            self.sleep(hold_seconds)
        self.key_up(key)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def release_all(self) -> None:
        """Release anything still held. The default sink holds nothing."""
        return None

    def available(self) -> bool:
        return True


class RecordingInputSink(InputSink):
    """Records what would have been pressed. Used by the tests."""

    id = "recording"

    def __init__(self, *, clock=None, simulate_sleep: bool = False) -> None:
        self.actions: list[KeyAction] = []
        self.held: set[str] = set()
        self._clock = clock or time.perf_counter
        self._simulate_sleep = simulate_sleep
        self._virtual_time = 0.0

    def now(self) -> float:
        if self._simulate_sleep:
            return self._virtual_time
        return self._clock()

    def sleep(self, seconds: float) -> None:
        if self._simulate_sleep:
            self._virtual_time += max(0.0, seconds)
        else:
            super().sleep(seconds)

    def key_down(self, key: str) -> None:
        self.held.add(key)
        self.actions.append(KeyAction(key, True, self.now()))

    def key_up(self, key: str) -> None:
        self.held.discard(key)
        self.actions.append(KeyAction(key, False, self.now()))

    def release_all(self) -> None:
        for key in sorted(self.held):
            self.key_up(key)

    def presses(self) -> list[tuple[str, float]]:
        return [(a.key, a.monotonic) for a in self.actions if a.down]

    def to_dict(self) -> dict[str, Any]:
        return {"actions": [a.to_dict() for a in self.actions]}


#: Virtual-key codes for the keys the Shawzin uses by default.
VK_CODES: dict[str, int] = {
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39, "0": 0x30,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "space": 0x20, "tab": 0x09, "escape": 0x1B, "enter": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "n": 0x4E, "l": 0x4C, "m": 0x4D, "w": 0x57, "a": 0x41, "x": 0x58,
    "q": 0x51, "e": 0x45, "r": 0x52, "t": 0x54, "y": 0x59, "u": 0x55,
    "i": 0x49, "o": 0x4F, "p": 0x50, "s": 0x53, "d": 0x44, "f": 0x46,
    "g": 0x47, "h": 0x48, "j": 0x4A, "k": 0x4B, "z": 0x5A, "c": 0x43,
    "v": 0x56, "b": 0x42,
}


class WindowsInputSink(InputSink):
    """Real key presses via user32 SendInput. Windows only."""

    id = "windows"

    def __init__(self) -> None:
        self._ok = False
        self._user32 = None
        #: Keys we have pressed and not yet released, so a stop can release
        #: exactly those and nothing else.
        self._held: list[str] = []
        try:
            import ctypes
            import sys

            if sys.platform != "win32":
                return
            self._ctypes = ctypes
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._build_structs()
            self._ok = True
        except Exception:  # noqa: BLE001 - absence is reported, never raised
            self._ok = False

    def _build_structs(self) -> None:
        import ctypes
        from ctypes import wintypes

        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class _INPUTunion(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]

        self._KEYBDINPUT = KEYBDINPUT
        self._INPUT = INPUT
        self._INPUT_KEYBOARD = 1
        self._KEYEVENTF_KEYUP = 0x0002
        self._KEYEVENTF_SCANCODE = 0x0008
        self._KEYEVENTF_EXTENDEDKEY = 0x0001

    def available(self) -> bool:
        return self._ok

    def _send(self, key: str, up: bool) -> None:
        if not self._ok:
            return
        vk = VK_CODES.get(key.lower())
        if vk is None:
            return
        import ctypes

        # Scan codes are what games read; MapVirtualKey converts from the VK.
        scan = self._user32.MapVirtualKeyW(vk, 0)
        flags = self._KEYEVENTF_SCANCODE
        if up:
            flags |= self._KEYEVENTF_KEYUP
        if key.lower() in ("left", "right", "up", "down"):
            flags |= self._KEYEVENTF_EXTENDEDKEY
        ki = self._KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        inp = self._INPUT(type=self._INPUT_KEYBOARD)
        inp.union.ki = ki
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(self._INPUT))

    def key_down(self, key: str) -> None:
        self._send(key, up=False)
        if key not in self._held:
            self._held.append(key)

    def key_up(self, key: str) -> None:
        self._send(key, up=True)
        if key in self._held:
            self._held.remove(key)

    def release_all(self) -> None:
        """Release every key we are holding, newest first."""
        for key in reversed(list(self._held)):
            self._send(key, up=True)
        self._held.clear()


@dataclass
class NullInputSink(InputSink):
    """Accepts everything and does nothing. Used when live mode is disabled."""

    id: str = "null"
    count: int = field(default=0)

    def key_down(self, key: str) -> None:
        self.count += 1

    def key_up(self, key: str) -> None:
        self.count += 1


def select_sink(prefer_real: bool = True) -> InputSink:
    if prefer_real:
        sink = WindowsInputSink()
        if sink.available():
            return sink
    return NullInputSink()

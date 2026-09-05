"""Warframe key bindings.

Defaults come from the documented in-game controls, but nothing assumes the
user kept them: every binding is rebindable and stored locally, and the
calibration wizard writes into this structure.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..common.paths import app_dir

#: Documented PC defaults (WARFRAME Wiki, Shawzin > Controls).
DEFAULT_BINDINGS: dict[str, str] = {
    "string1": "1",
    "string2": "2",
    "string3": "3",
    "fret1": "left",   # Sky fret   (alternate default: n)
    "fret2": "down",   # Earth fret (alternate default: l)
    "fret3": "right",  # Water fret (alternate default: m)
    "whammy": "space",
    "scale": "tab",
    "emergencyStop": "escape",
}

ALTERNATE_FRET_BINDINGS: dict[str, str] = {"fret1": "n", "fret2": "l", "fret3": "m"}

BINDING_LABELS: dict[str, str] = {
    "string1": "1st String",
    "string2": "2nd String",
    "string3": "3rd String",
    "fret1": "Sky Fret",
    "fret2": "Earth Fret",
    "fret3": "Water Fret",
    "whammy": "Whammy",
    "scale": "Change Scale",
    "emergencyStop": "Emergency Stop",
}


@dataclass
class TimingSettings:
    """Latency calibration. Benchmarked, not guessed -- see docs/development.md."""

    #: Shifts the whole performance. Negative plays early.
    playback_offset_ms: float = 0.0
    #: Gap between pressing a fret and plucking a string.
    fret_to_string_ms: float = 12.0
    #: Gap between two strings of the same strum.
    inter_string_ms: float = 4.0
    #: How long a key is held down.
    key_hold_ms: float = 14.0
    #: How long before the first note the countdown ends.
    countdown_seconds: float = 3.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WarframeKeymap:
    bindings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BINDINGS))
    timing: TimingSettings = field(default_factory=TimingSettings)

    def key_for(self, action: str) -> str:
        return self.bindings.get(action, DEFAULT_BINDINGS.get(action, ""))

    def string_key(self, string: str) -> str:
        return self.key_for("string" + str(string))

    def fret_keys(self, fret: str) -> list[str]:
        """Keys to hold for a fret state. ``"0"`` means no fret held."""
        if fret == "0" or not fret:
            return []
        return [self.key_for("fret" + ch) for ch in fret if ch in ("1", "2", "3")]

    def validate(self) -> list[str]:
        """Report bindings that clash or are missing."""
        problems: list[str] = []
        seen: dict[str, str] = {}
        for action, key in self.bindings.items():
            if not key:
                problems.append(BINDING_LABELS.get(action, action) + " has no key assigned.")
                continue
            if key in seen and action != "emergencyStop" and seen[key] != "emergencyStop":
                problems.append(
                    BINDING_LABELS.get(action, action)
                    + " and "
                    + BINDING_LABELS.get(seen[key], seen[key])
                    + " are both bound to "
                    + key.upper()
                    + "."
                )
            seen[key] = action
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {"bindings": dict(self.bindings), "timing": self.timing.to_dict()}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> WarframeKeymap:
        bindings = dict(DEFAULT_BINDINGS)
        bindings.update({k: str(v) for k, v in (d.get("bindings") or {}).items()})
        t = d.get("timing") or {}
        timing = TimingSettings(
            playback_offset_ms=float(t.get("playback_offset_ms", t.get("playbackOffsetMs", 0.0))),
            fret_to_string_ms=float(t.get("fret_to_string_ms", t.get("fretToStringMs", 12.0))),
            inter_string_ms=float(t.get("inter_string_ms", t.get("interStringMs", 4.0))),
            key_hold_ms=float(t.get("key_hold_ms", t.get("keyHoldMs", 14.0))),
            countdown_seconds=float(t.get("countdown_seconds", t.get("countdownSeconds", 3.0))),
        )
        return WarframeKeymap(bindings, timing)

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else Path(app_dir()) / "keymap.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target

    @staticmethod
    def load(path: str | Path | None = None) -> WarframeKeymap:
        target = Path(path) if path else Path(app_dir()) / "keymap.json"
        if not target.exists():
            return WarframeKeymap()
        try:
            return WarframeKeymap.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return WarframeKeymap()

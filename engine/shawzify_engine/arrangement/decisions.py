"""Per-note arrangement decisions.

Every change the engine makes to a source note is recorded with a reason, so
the UI can answer "why is this note different?" without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..music.events import NoteEvent
from ..music.pitch import note_name


class Operation(str, Enum):
    KEEP = "keep"
    TRANSPOSE = "transpose"
    OCTAVE_FOLD = "octave_fold"
    QUANTIZE = "quantize"
    ARPEGGIATE = "arpeggiate"
    REMOVE = "remove"
    SIMPLIFY = "simplify"
    CHORD_SUBSTITUTE = "chord_substitute"


@dataclass
class ArrangementDecision:
    """One source note's fate."""

    source_index: int
    original: NoteEvent
    operations: list[Operation] = field(default_factory=list)
    output_midi: int | None = None
    output_seconds: float | None = None
    position: str | None = None  # Shawzin fret-string, e.g. "1-2"
    reason: str = ""
    cost: float = 0.0
    importance: float = 0.0

    @property
    def removed(self) -> bool:
        return Operation.REMOVE in self.operations

    @property
    def pitch_delta(self) -> int:
        if self.output_midi is None:
            return 0
        return self.output_midi - self.original.pitch_midi

    @property
    def timing_delta(self) -> float:
        if self.output_seconds is None:
            return 0.0
        return self.output_seconds - self.original.start_seconds

    def add(self, op: Operation) -> None:
        if op not in self.operations:
            self.operations.append(op)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceIndex": self.source_index,
            "operations": [o.value for o in self.operations],
            "original": {
                "midi": self.original.pitch_midi,
                "name": self.original.pitch_name,
                "seconds": round(self.original.start_seconds, 4),
            },
            "output": None
            if self.output_midi is None
            else {
                "midi": self.output_midi,
                "name": note_name(self.output_midi),
                "seconds": round(self.output_seconds or 0.0, 4),
                "position": self.position,
            },
            "pitchDelta": self.pitch_delta,
            "timingDelta": round(self.timing_delta, 4),
            "reason": self.reason,
            "cost": round(self.cost, 4),
            "importance": round(self.importance, 4),
            "removed": self.removed,
        }


REASONS = {
    Operation.KEEP: "Played as written.",
    Operation.TRANSPOSE: "Shifted with the whole song so it fits the chosen scale.",
    Operation.OCTAVE_FOLD: "Moved by an octave to fit the Shawzin's range.",
    Operation.QUANTIZE: "Nudged onto the rhythmic grid.",
    Operation.ARPEGGIATE: "Spread out because the Shawzin cannot play these notes together.",
    Operation.REMOVE: "Dropped: the passage was denser than the Shawzin can play.",
    Operation.SIMPLIFY: "Replaced by the nearest note the chosen scale can play.",
    Operation.CHORD_SUBSTITUTE: "Played as a Shawzin chord position.",
}


def describe_operations(ops: list[Operation]) -> str:
    if not ops:
        return REASONS[Operation.KEEP]
    return " ".join(REASONS[o] for o in ops if o in REASONS)

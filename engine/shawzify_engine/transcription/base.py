"""Transcriber interface and backend selection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..music.events import NoteEvent

ProgressFn = Callable[[float, str], None]


@dataclass
class TranscriptionResult:
    events: list[NoteEvent]
    backend: str
    polyphonic: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "polyphonic": self.polyphonic,
            "noteCount": len(self.events),
            "detail": self.detail,
        }


class Transcriber(ABC):
    """Audio -> NoteEvent. Implementations must be deterministic."""

    id: str = "base"
    name: str = "Transcriber"
    polyphonic: bool = False

    @abstractmethod
    def available(self) -> bool:
        """Whether this backend can run right now (model present, deps importable)."""

    @abstractmethod
    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        min_confidence: float = 0.3,
    ) -> TranscriptionResult:
        ...

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "polyphonic": self.polyphonic,
            "available": self.available(),
        }

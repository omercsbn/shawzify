"""Stem separation interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

ProgressFn = Callable[[float, str], None]

STEM_NAMES = ("vocals", "drums", "bass", "other")


@dataclass
class StemSet:
    """Separated stems as mono float32 arrays at a common sample rate."""

    sample_rate: int
    stems: dict[str, np.ndarray] = field(default_factory=dict)
    backend: str = "none"
    device: str = "cpu"
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def available_names(self) -> tuple[str, ...]:
        return tuple(self.stems.keys())

    def get(self, name: str) -> np.ndarray | None:
        return self.stems.get(name)

    def instrumental(self) -> np.ndarray | None:
        """Everything except vocals, summed."""
        parts = [v for k, v in self.stems.items() if k != "vocals"]
        if not parts:
            return None
        length = max(p.shape[-1] for p in parts)
        acc = np.zeros(length, dtype=np.float32)
        for p in parts:
            acc[: p.shape[-1]] += p
        return acc

    def melodic(self) -> np.ndarray | None:
        """Pitched content only: everything except drums."""
        parts = [v for k, v in self.stems.items() if k != "drums"]
        if not parts:
            return None
        length = max(p.shape[-1] for p in parts)
        acc = np.zeros(length, dtype=np.float32)
        for p in parts:
            acc[: p.shape[-1]] += p
        return acc

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "device": self.device,
            "stems": list(self.stems.keys()),
            "sampleRate": self.sample_rate,
            "detail": self.detail,
        }


class StemSeparator(ABC):
    id: str = "base"
    name: str = "Stem separator"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def separate(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
    ) -> StemSet:
        ...

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "available": self.available()}

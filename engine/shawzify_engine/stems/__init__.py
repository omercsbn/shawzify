"""Stem separation: interface, Demucs backend, and a pass-through."""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import STEM_NAMES, ProgressFn, StemSeparator, StemSet
from .demucs_separator import DemucsStemSeparator, cuda_available, gpu_info

__all__ = [
    "StemSeparator",
    "StemSet",
    "STEM_NAMES",
    "DemucsStemSeparator",
    "NoOpStemSeparator",
    "select_separator",
    "cuda_available",
    "gpu_info",
]


class NoOpStemSeparator(StemSeparator):
    """Pass-through: reports the full mix as a single 'other' stem.

    This is the honest fallback when Demucs is unavailable -- the pipeline keeps
    working on the full mix rather than pretending stems exist.
    """

    id = "none"
    name = "No separation (full mix)"

    def available(self) -> bool:
        return True

    def separate(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        content_hash: str | None = None,
    ) -> StemSet:
        if samples.ndim > 1:
            samples = samples.mean(axis=0)
        if progress:
            progress(1.0, "Using the full mix")
        return StemSet(
            sample_rate=sample_rate,
            stems={"other": np.asarray(samples, dtype=np.float32)},
            backend=self.id,
            device="cpu",
            detail={"passthrough": True},
        )


def select_separator(enabled: bool = True, *, device: str = "auto") -> StemSeparator:
    if enabled:
        demucs = DemucsStemSeparator(device=device)
        if demucs.available():
            return demucs
    return NoOpStemSeparator()


def describe_separators() -> list[dict[str, Any]]:
    return [DemucsStemSeparator().describe(), NoOpStemSeparator().describe()]

"""Progress reporting and cooperative cancellation.

Stages report real fractions of real work. There is deliberately no
"fake progress" helper anywhere in this file.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .errors import CancelledError

#: Ordered pipeline stages, with the share of a full run each typically takes.
#: Used to turn per-stage progress into a single overall fraction.
STAGE_WEIGHTS: dict[str, float] = {
    "decode": 0.08,
    "waveform": 0.02,
    "stems": 0.45,
    "analyze": 0.08,
    "transcribe": 0.25,
    "arrange": 0.08,
    "encode": 0.04,
}

STAGE_LABELS: dict[str, str] = {
    "decode": "Loading audio",
    "waveform": "Drawing waveform",
    "stems": "Separating stems",
    "analyze": "Detecting rhythm and key",
    "transcribe": "Transcribing notes",
    "arrange": "Optimizing arrangement",
    "encode": "Encoding performance",
}

ProgressCallback = Callable[["ProgressEvent"], None]


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    label: str
    stage_fraction: float
    overall_fraction: float
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "label": self.label,
            "stageFraction": round(self.stage_fraction, 4),
            "overallFraction": round(self.overall_fraction, 4),
            "message": self.message,
        }


class CancellationToken:
    """Thread-safe cancel flag checked at stage boundaries and inside loops."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError()


class ProgressReporter:
    """Maps per-stage fractions onto a weighted overall fraction.

    ``skip`` marks a stage as not running so its weight is redistributed --
    that keeps the overall bar honest when, say, stem separation is disabled.
    """

    def __init__(
        self,
        callback: ProgressCallback | None = None,
        *,
        stages: list[str] | None = None,
        token: CancellationToken | None = None,
    ) -> None:
        self._callback = callback
        self.token = token or CancellationToken()
        self._stages = list(stages or STAGE_WEIGHTS.keys())
        self._active = {s: STAGE_WEIGHTS.get(s, 0.1) for s in self._stages}
        self._done: dict[str, float] = {}

    def _total_weight(self) -> float:
        return sum(self._active.values()) or 1.0

    def skip(self, stage: str) -> None:
        self._active.pop(stage, None)
        self._done.pop(stage, None)

    def _overall(self, stage: str, fraction: float) -> float:
        total = self._total_weight()
        # The reported stage contributes via ``fraction`` only; counting it in
        # ``completed`` as well would make the bar jump forward then back.
        completed = sum(self._active.get(s, 0.0) for s in self._done if s != stage)
        current = self._active.get(stage, 0.0) * max(0.0, min(1.0, fraction))
        return max(0.0, min(1.0, (completed + current) / total))

    def start(self, stage: str, message: str | None = None) -> None:
        self.token.raise_if_cancelled()
        self.update(stage, 0.0, message)

    def update(self, stage: str, fraction: float, message: str | None = None) -> None:
        self.token.raise_if_cancelled()
        if self._callback is None:
            return
        self._callback(
            ProgressEvent(
                stage=stage,
                label=STAGE_LABELS.get(stage, stage.title()),
                stage_fraction=max(0.0, min(1.0, fraction)),
                overall_fraction=self._overall(stage, fraction),
                message=message,
            )
        )

    def finish(self, stage: str, message: str | None = None) -> None:
        self._done[stage] = 1.0
        self.update(stage, 1.0, message)

    def sub(self, stage: str) -> Callable[..., None]:
        """A ``(fraction, message)`` callable bound to one stage."""

        def _report(fraction: float, message: str | None = None) -> None:
            self.update(stage, fraction, message)

        return _report

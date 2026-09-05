"""Audio transcription backends and selection."""

from __future__ import annotations

from typing import Any

from .base import Transcriber, TranscriptionResult
from .basic_pitch_transcriber import BasicPitchTranscriber
from .cqt_transcriber import CqtTranscriber
from .pyin_transcriber import PyinTranscriber

__all__ = [
    "Transcriber",
    "TranscriptionResult",
    "BasicPitchTranscriber",
    "CqtTranscriber",
    "PyinTranscriber",
    "available_transcribers",
    "select_transcriber",
]


def available_transcribers() -> list[Transcriber]:
    """All backends, best first."""
    return [BasicPitchTranscriber(), CqtTranscriber(), PyinTranscriber()]


def select_transcriber(
    preference: str = "auto", *, polyphonic: bool = True
) -> Transcriber:
    """Pick a backend.

    ``auto`` takes the best available; an explicit id is honoured when that
    backend can actually run, and otherwise falls back rather than failing.
    """
    all_backends = available_transcribers()
    by_id = {t.id: t for t in all_backends}
    if preference not in ("auto", "", None):
        chosen = by_id.get(preference)
        if chosen is not None and chosen.available():
            return chosen
    for backend in all_backends:
        if not backend.available():
            continue
        if not polyphonic and backend.polyphonic and by_id["pyin"].available():
            return by_id["pyin"]
        return backend
    return CqtTranscriber()


def describe_backends() -> list[dict[str, Any]]:
    return [t.describe() for t in available_transcribers()]

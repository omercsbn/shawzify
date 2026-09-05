"""Spotify Basic Pitch backend.

Preferred when installed: a trained polyphonic model beats the built-in
estimator by a wide margin on real mixes. The model ships inside the package,
so there is nothing to download at runtime.
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
from pathlib import Path

import numpy as np

from ..common.errors import TranscriptionError
from ..music.events import NoteEvent, clamp_durations
from .base import ProgressFn, Transcriber, TranscriptionResult


def _model_path() -> tuple[object, str] | None:
    """Locate a usable Basic Pitch model, preferring ONNX (no TF dependency)."""
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    try:
        from basic_pitch import FilenameSuffix, build_icassp_2022_model_path

        for suffix, label in (
            (FilenameSuffix.onnx, "onnx"),
            (FilenameSuffix.tf, "tf"),
            (FilenameSuffix.tflite, "tflite"),
        ):
            try:
                path = build_icassp_2022_model_path(suffix)
            except Exception:  # noqa: BLE001
                continue
            if path is not None and Path(str(path)).exists():
                return (path, label)
    except Exception:  # noqa: BLE001
        pass
    from basic_pitch import ICASSP_2022_MODEL_PATH

    return (ICASSP_2022_MODEL_PATH, "default")


class BasicPitchTranscriber(Transcriber):
    id = "basic_pitch"
    name = "Basic Pitch (polyphonic)"
    polyphonic = True

    def __init__(self, *, onset_threshold: float = 0.5, frame_threshold: float = 0.3) -> None:
        self.onset_threshold = onset_threshold
        self.frame_threshold = frame_threshold
        self._resolved: tuple[object, str] | None = None

    def available(self) -> bool:
        try:
            import basic_pitch.inference  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        if self._resolved is None:
            self._resolved = _model_path()
        return self._resolved is not None

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        min_confidence: float = 0.3,
    ) -> TranscriptionResult:
        if not self.available():
            raise TranscriptionError(
                "Basic Pitch is not installed.",
                hint="Run scripts/setup.ps1, or SHAWZIFY will use the built-in transcriber.",
            )
        from basic_pitch.inference import predict

        if samples.ndim > 1:
            samples = samples.mean(axis=0)
        samples = np.asarray(samples, dtype=np.float32)
        peak = float(np.max(np.abs(samples)) or 1.0)
        samples = samples / peak

        if progress:
            progress(0.1, "Running Basic Pitch")

        # predict() takes a path; write a temporary wav rather than reaching into
        # the library's private audio loading.
        import soundfile as sf

        model, label = self._resolved  # type: ignore[misc]
        tmp = Path(tempfile.mkdtemp(prefix="shawzify-bp-")) / "input.wav"
        try:
            sf.write(str(tmp), samples, sample_rate, subtype="PCM_16")
            # predict() prints "Predicting MIDI for ..." to stdout. That would
            # corrupt the CLI's --json output and the sidecar's protocol stream,
            # so send it to stderr where it belongs.
            with contextlib.redirect_stdout(sys.stderr):
                _model_out, _midi, note_events = predict(
                    str(tmp),
                    model_or_model_path=model,
                    onset_threshold=self.onset_threshold,
                    frame_threshold=self.frame_threshold,
                    minimum_note_length=58.0,
                    multiple_pitch_bends=False,
                    melodia_trick=True,
                )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(cause=exc) from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
                tmp.parent.rmdir()
            except OSError:
                pass

        if progress:
            progress(0.9, "Collecting notes")
        events: list[NoteEvent] = []
        for item in note_events:
            start, end, pitch, amplitude = item[0], item[1], item[2], item[3]
            confidence = float(min(1.0, max(0.0, amplitude)))
            if confidence < min_confidence:
                continue
            events.append(
                NoteEvent(
                    pitch_midi=int(pitch),
                    start_seconds=float(start),
                    duration_seconds=float(max(0.03, end - start)),
                    velocity=float(min(1.0, 0.3 + confidence * 0.9)),
                    confidence=confidence,
                    source="audio:basic_pitch",
                )
            )
        events = clamp_durations(events)
        if progress:
            progress(1.0, "Transcribed " + str(len(events)) + " notes")
        return TranscriptionResult(
            events,
            self.id,
            True,
            {
                "model": label,
                "onsetThreshold": self.onset_threshold,
                "frameThreshold": self.frame_threshold,
            },
        )

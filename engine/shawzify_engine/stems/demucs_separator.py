"""Demucs (htdemucs) stem separation, GPU when available.

CUDA is used if torch reports a device; any CUDA failure retries on CPU rather
than surfacing a driver error to the user. Results are cached by audio content
hash plus model version, so changing arrangement settings never re-separates.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..common.cache import Cache, hash_payload, make_key
from ..common.errors import StemSeparationError
from ..common.logging import get_logger
from ..common.paths import model_dir
from ..version import STEMS_VERSION
from .base import STEM_NAMES, ProgressFn, StemSeparator, StemSet

DEFAULT_MODEL = "htdemucs"


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def gpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {"cuda": False, "device": None, "torch": None}
    try:
        import torch

        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["cuda"] = True
            info["device"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            info["memoryTotalMb"] = int(props.total_memory // (1024 * 1024))
    except Exception:  # noqa: BLE001
        pass
    return info


class DemucsStemSeparator(StemSeparator):
    id = "demucs"
    name = "Demucs (htdemucs)"

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        device: str = "auto",
        segment: float | None = None,
        cache: Cache | None = None,
    ) -> None:
        self.model_name = model_name
        self.device_preference = device
        self.segment = segment
        self.cache = cache or Cache()
        self._model = None
        self._model_device: str | None = None

    def available(self) -> bool:
        try:
            import demucs.apply  # noqa: F401
            import demucs.pretrained  # noqa: F401
            import torch  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def resolve_device(self) -> str:
        if self.device_preference == "cpu":
            return "cpu"
        if self.device_preference == "cuda":
            return "cuda" if cuda_available() else "cpu"
        return "cuda" if cuda_available() else "cpu"

    def _load(self, device: str):
        if self._model is not None and self._model_device == device:
            return self._model
        import os

        import torch
        from demucs.pretrained import get_model

        # Keep weights inside the app's model directory rather than ~/.cache.
        os.environ.setdefault("TORCH_HOME", model_dir())
        try:
            model = get_model(self.model_name)
        except Exception as exc:  # noqa: BLE001
            raise StemSeparationError(
                "The stem separation model could not be loaded.",
                hint="Check your connection: the model downloads once, then works offline.",
                cause=exc,
            ) from exc
        model.to(torch.device(device))
        model.eval()
        self._model = model
        self._model_device = device
        return model

    def separate(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        progress: ProgressFn | None = None,
        content_hash: str | None = None,
    ) -> StemSet:
        if not self.available():
            raise StemSeparationError(
                "Demucs is not installed.",
                hint="SHAWZIFY will use the full mix instead.",
            )
        log = get_logger("stems")

        settings = hash_payload(
            {"model": self.model_name, "version": STEMS_VERSION, "sr": sample_rate}
        )
        cache_key = make_key(content_hash or "", settings) if content_hash else None
        if cache_key:
            cached = self.cache.get_dir("stems", cache_key)
            if cached is not None:
                stems: dict[str, np.ndarray] = {}
                for name in STEM_NAMES:
                    f = cached / (name + ".npy")
                    if f.exists():
                        stems[name] = np.load(f)
                if stems:
                    log.event("stems.cache_hit", key=cache_key)
                    return StemSet(sample_rate, stems, self.id, "cache", {"cached": True})

        device = self.resolve_device()
        try:
            result = self._run(samples, sample_rate, device, progress)
        except Exception as exc:  # noqa: BLE001
            if device == "cuda":
                log.warn("stems.cuda_failed", error=str(exc))
                if progress:
                    progress(0.05, "GPU processing failed, switching to CPU")
                try:
                    result = self._run(samples, sample_rate, "cpu", progress)
                except Exception as cpu_exc:  # noqa: BLE001
                    raise StemSeparationError(cause=cpu_exc) from cpu_exc
            else:
                raise StemSeparationError(cause=exc) from exc

        if cache_key:
            target = self.cache.begin_dir("stems", cache_key)
            for name, data in result.stems.items():
                np.save(target / (name + ".npy"), data.astype(np.float32))
            self.cache.commit_dir("stems", cache_key)
        return result

    def _run(
        self, samples: np.ndarray, sample_rate: int, device: str, progress: ProgressFn | None
    ) -> StemSet:
        import torch
        from demucs.apply import apply_model

        model = self._load(device)
        model_sr = int(getattr(model, "samplerate", 44100))
        channels = int(getattr(model, "audio_channels", 2))

        data = np.asarray(samples, dtype=np.float32)
        if data.ndim == 1:
            data = data[None, :]
        if data.shape[0] == 1 and channels == 2:
            data = np.repeat(data, 2, axis=0)
        elif data.shape[0] == 2 and channels == 1:
            data = data.mean(axis=0, keepdims=True)

        if sample_rate != model_sr:
            from ..audio.decode import resample

            data = resample(data, sample_rate, model_sr)

        if progress:
            progress(0.1, "Separating stems on " + device.upper())

        tensor = torch.from_numpy(data)[None]
        with torch.no_grad():
            out = apply_model(
                model,
                tensor.to(torch.device(device)),
                device=torch.device(device),
                split=True,
                overlap=0.25,
                progress=False,
                segment=self.segment,
            )
        out = out.squeeze(0).cpu().numpy()
        names = list(getattr(model, "sources", STEM_NAMES))
        stems: dict[str, np.ndarray] = {}
        for i, name in enumerate(names):
            if i >= out.shape[0]:
                break
            stems[name] = out[i].mean(axis=0).astype(np.float32)
        if progress:
            progress(1.0, "Stems ready")
        return StemSet(
            sample_rate=model_sr,
            stems=stems,
            backend=self.id,
            device=device,
            detail={"model": self.model_name, "sources": names},
        )

"""Local structured logging + stage timing.

Everything is written to a rotating JSONL file under the user's app data
directory. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .paths import log_dir

_LOCK = threading.Lock()
_MAX_BYTES = 4 * 1024 * 1024


@dataclass
class StageTiming:
    stage: str
    duration_s: float
    success: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "durationSeconds": round(self.duration_s, 4),
            "success": self.success,
            "detail": self.detail,
        }


class StructuredLogger:
    """Append-only JSONL logger. One instance per process is plenty."""

    def __init__(self, component: str = "engine", path: str | None = None) -> None:
        self.component = component
        self._path = path
        self.timings: list[StageTiming] = []
        self.echo = os.environ.get("SHAWZIFY_LOG_ECHO", "") == "1"

    @property
    def path(self) -> str:
        if self._path is None:
            self._path = os.path.join(log_dir(), "shawzify.jsonl")
        return self._path

    def _write(self, record: dict[str, Any]) -> None:
        record.setdefault("timestamp", time.time())
        record.setdefault("iso", time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()))
        record.setdefault("component", self.component)
        line = json.dumps(record, default=str)
        if self.echo:
            print(line, file=sys.stderr, flush=True)
        try:
            with _LOCK:
                p = self.path
                if os.path.exists(p) and os.path.getsize(p) > _MAX_BYTES:
                    backup = p + ".1"
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.replace(p, backup)
                with open(p, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            # Logging must never take the app down.
            pass

    def event(self, operation: str, **fields: Any) -> None:
        self._write({"level": "info", "operation": operation, **fields})

    def warn(self, operation: str, **fields: Any) -> None:
        self._write({"level": "warn", "operation": operation, **fields})

    def error(self, operation: str, exc: BaseException | None = None, **fields: Any) -> None:
        tb = None
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        self._write({"level": "error", "operation": operation, "error": str(exc) if exc else None,
                     "traceback": tb, **fields})

    @contextmanager
    def stage(self, name: str, **fields: Any) -> Iterator[dict[str, Any]]:
        """Time a pipeline stage. Extra detail can be added to the yielded dict."""
        detail: dict[str, Any] = {}
        started = time.perf_counter()
        ok = True
        try:
            yield detail
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            ok = False
            self.error(name, exc, **fields)
            raise
        finally:
            elapsed = time.perf_counter() - started
            timing = StageTiming(name, elapsed, ok, {**fields, **detail})
            self.timings.append(timing)
            self._write({
                "level": "info",
                "operation": name,
                "duration": round(elapsed, 4),
                "success": ok,
                **fields,
                **detail,
            })

    def timings_dict(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.timings]

    def reset_timings(self) -> None:
        self.timings = []


_default: StructuredLogger | None = None


def get_logger(component: str = "engine") -> StructuredLogger:
    global _default
    if _default is None:
        _default = StructuredLogger(component)
    return _default

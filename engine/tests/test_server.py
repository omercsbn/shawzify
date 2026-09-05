"""The sidecar JSON-RPC protocol, driven as a real subprocess.

These run the engine exactly as the desktop shell does -- a child process with
piped stdin and stdout -- because the failures that matter here (a library
printing to stdout, a library probing stdin during a threaded import) only
appear in that configuration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TIMEOUT = 180.0


class EngineProcess:
    """A live engine sidecar with a background reader, as Rust drives it."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self.proc = subprocess.Popen(
            [PYTHON, "-u", "-m", "shawzify_engine.server"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        self.results: dict[int, dict] = {}
        self.events: list[dict] = []
        self._lock = threading.Condition()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        while True:
            raw = self.proc.stdout.readline()
            if not raw:
                break
            try:
                message = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                # A stray non-JSON line means something polluted the protocol
                # channel; record it so a test can fail loudly.
                with self._lock:
                    self.events.append({"pollution": raw.decode("utf-8", "replace")})
                    self._lock.notify_all()
                continue
            with self._lock:
                if message.get("type") == "event":
                    self.events.append(message)
                else:
                    self.results[int(message.get("id", 0))] = message
                self._lock.notify_all()

    def send(self, request_id: int, method: str, params: dict | None = None) -> None:
        assert self.proc.stdin is not None
        line = json.dumps({"id": request_id, "method": method, "params": params or {}})
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def wait(self, request_id: int, timeout: float = TIMEOUT) -> dict:
        deadline = time.time() + timeout
        with self._lock:
            while request_id not in self.results:
                remaining = deadline - time.time()
                if remaining <= 0:
                    stderr = b""
                    if self.proc.stderr is not None and self.proc.poll() is not None:
                        stderr = self.proc.stderr.read()
                    raise AssertionError(
                        "engine did not answer request "
                        + str(request_id)
                        + " (exit="
                        + str(self.proc.poll())
                        + ") "
                        + stderr.decode("utf-8", "replace")[-1500:]
                    )
                self._lock.wait(min(0.25, remaining))
            return self.results.pop(request_id)

    def call(self, request_id: int, method: str, params: dict | None = None) -> dict:
        self.send(request_id, method, params)
        return self.wait(request_id)

    def progress_for(self, request_id: int) -> list[dict]:
        with self._lock:
            return [
                e for e in self.events
                if e.get("id") == request_id and e.get("event") == "progress"
            ]

    def pollution(self) -> list[str]:
        with self._lock:
            return [e["pollution"] for e in self.events if "pollution" in e]

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.send(0, "shutdown")
                self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - teardown must not fail a test
            pass
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass


@pytest.fixture(scope="module")
def engine_process():
    proc = EngineProcess()
    yield proc
    proc.close()


@pytest.fixture(scope="module")
def demo_midi(tmp_path_factory) -> Path:
    from shawzify_engine.demo import BPM, demo_events
    from shawzify_engine.midi.writer import write_midi

    path = tmp_path_factory.mktemp("server") / "demo.mid"
    return write_midi(demo_events(), path, bpm=BPM)


def test_ping(engine_process):
    result = engine_process.call(1, "ping")
    assert result["result"]["ok"] is True
    assert "arrangement" in result["result"]["versions"]


def test_unknown_method_is_an_error_not_a_crash(engine_process):
    result = engine_process.call(2, "does_not_exist")
    assert result["error"]["code"] == "unknown_method"
    # The engine must still be answering afterwards.
    assert engine_process.call(3, "ping")["result"]["ok"] is True


def test_environment_answers_from_a_worker_thread(engine_process):
    """Regression: heavy imports in a worker used to deadlock against stdin."""
    result = engine_process.call(4, "environment")
    payload = result["result"]
    assert payload["ffmpeg"]["available"] is True
    assert isinstance(payload["transcribers"], list)


def test_instrument_exposes_all_scales(engine_process):
    payload = engine_process.call(5, "instrument")["result"]
    assert len(payload["scales"]) == 9
    assert len(payload["variants"]) == 11
    assert payload["format"]["ticksPerSecond"] == 16


def test_analyze_then_arrange(engine_process, demo_midi):
    analysis = engine_process.call(
        10, "analyze", {"path": str(demo_midi), "useStems": False}
    )["result"]
    assert analysis["noteCount"] > 50
    source_id = analysis["sourceId"]

    arranged = engine_process.call(
        11, "arrange", {"sourceId": source_id, "options": {"mode": "balanced"}}
    )["result"]
    assert arranged["code"]
    assert arranged["report"]["compatibilityAfter"]["overall"] > 60
    assert arranged["liveEvents"]
    assert arranged["tab"].startswith("Scale:")


def test_rearranging_reuses_the_loaded_source(engine_process, demo_midi):
    source_id = engine_process.call(
        20, "analyze", {"path": str(demo_midi), "useStems": False}
    )["result"]["sourceId"]

    melody = engine_process.call(
        21, "arrange", {"sourceId": source_id, "options": {"mode": "melody"}}
    )["result"]
    chordal = engine_process.call(
        22, "arrange", {"sourceId": source_id, "options": {"mode": "chordal"}}
    )["result"]
    assert melody["code"] != chordal["code"]
    assert chordal["report"]["metrics"]["outputNotes"] >= melody["report"]["metrics"]["outputNotes"]


def test_arrange_reports_progress(engine_process, demo_midi):
    source_id = engine_process.call(
        30, "analyze", {"path": str(demo_midi), "useStems": False}
    )["result"]["sourceId"]
    engine_process.call(31, "arrange", {"sourceId": source_id, "options": {}})
    events = engine_process.progress_for(31)
    assert events, "no progress events were emitted"
    fractions = [e["payload"]["overallFraction"] for e in events]
    assert all(0.0 <= f <= 1.0 for f in fractions)


def test_arranging_an_unknown_source_is_a_clean_error(engine_process):
    result = engine_process.call(40, "arrange", {"sourceId": "nope", "options": {}})
    assert "error" in result
    assert "no longer loaded" in result["error"]["message"]


def test_bad_path_is_reported_without_a_traceback_in_the_message(engine_process):
    result = engine_process.call(41, "analyze", {"path": "definitely_missing.mp3"})
    assert result["error"]["code"] == "unsafe_path"
    assert "Traceback" not in result["error"]["message"]


def test_decode_matches_the_golden_fixture(engine_process):
    payload = engine_process.call(50, "decode", {"code": "1BAACAIEAQJAYKAgMAo"})["result"]
    assert payload["scaleName"] == "Pentatonic Minor"
    assert [n["name"] for n in payload["soundingNotes"]] == [
        "C3", "D#3", "F3", "G3", "A#3", "C4"
    ]


def test_diagnostics_redacts_paths(engine_process):
    payload = engine_process.call(60, "diagnostics")["result"]
    assert "logPath" in payload
    home = str(Path.home())
    for key in ("logPath", "logDir", "modelDir"):
        assert home.lower() not in str(payload[key]).lower(), key + " leaked the home path"


def test_export_and_preview(engine_process, demo_midi, tmp_path):
    source_id = engine_process.call(
        70, "analyze", {"path": str(demo_midi), "useStems": False}
    )["result"]["sourceId"]
    engine_process.call(71, "arrange", {"sourceId": source_id, "options": {}})

    target = tmp_path / "out.shawzin.txt"
    exported = engine_process.call(
        72, "export", {"sourceId": source_id, "kind": "code", "path": str(target)}
    )["result"]
    assert Path(exported["path"]).exists()
    assert Path(exported["path"]).read_text(encoding="utf-8").strip()

    preview = engine_process.call(73, "preview", {"sourceId": source_id})["result"]
    assert Path(preview["path"]).exists()
    assert preview["durationSeconds"] > 1.0


def test_protocol_channel_is_never_polluted(engine_process, demo_midi):
    """A library printing to stdout would corrupt the JSON stream."""
    engine_process.call(80, "analyze", {"path": str(demo_midi), "useStems": False})
    assert engine_process.pollution() == []


def test_shutdown_exits_cleanly(demo_midi):
    proc = EngineProcess()
    try:
        assert proc.call(1, "ping")["result"]["ok"] is True
        proc.send(0, "shutdown")
        assert proc.proc.wait(timeout=20) == 0
    finally:
        proc.close()

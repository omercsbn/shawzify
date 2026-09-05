"""Newline-delimited JSON-RPC over stdin/stdout, for the desktop sidecar.

Deliberately not an HTTP server: there is no socket, so there is no port for
anything outside this machine to reach and no auth surface to get wrong. The
desktop shell owns the process; when it exits, this exits.

Protocol
--------
Request   {"id": 7, "method": "analyze", "params": {...}}
Result    {"id": 7, "type": "result", "result": {...}}
Failure   {"id": 7, "type": "result", "error": {"code", "message", "hint", "technical"}}
Event     {"id": 7, "type": "event", "event": "progress", "payload": {...}}

Long calls run on a worker thread so progress events can be written while the
work is happening, and so ``cancel`` is answerable mid-operation.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .arrangement.arranger import Arrangement
from .arrangement.options import ArrangementOptions
from .common.cache import Cache
from .common.errors import ShawzifyError
from .common.logging import get_logger
from .common.progress import CancellationToken, ProgressEvent, ProgressReporter
from .pipeline import SourceMaterial, arrange_source, environment_report, load_source
from .version import version_dict

_WRITE_LOCK = threading.Lock()

#: The real protocol channel, taken away from ``sys.stdin``/``sys.stdout`` by
#: :func:`claim_channels` so that no library can touch it.
_CHANNEL_IN: io.RawIOBase | None = None
_CHANNEL_OUT: io.RawIOBase | None = None


def claim_channels():
    """Take exclusive ownership of stdin/stdout, then hide them from Python.

    Two real hazards make this necessary rather than merely tidy:

    * Libraries in the audio stack print progress to stdout (Basic Pitch writes
      "Predicting MIDI for ..."), which would land in the middle of a JSON
      response and corrupt the protocol.
    * Some of them probe ``sys.stdin.isatty()`` at import time. ``TextIOWrapper``
      serialises its methods, so that call blocks on the lock held by the main
      thread's in-flight ``readline()`` -- a deadlock that hangs the engine on
      the first heavy import.

    So: duplicate the real descriptors for our own use, then point fd 1 at
    stderr and fd 0 at the null device. After this, anything a library prints
    becomes a log line and anything it reads is immediately EOF.
    """
    global _CHANNEL_IN, _CHANNEL_OUT
    if _CHANNEL_IN is not None and _CHANNEL_OUT is not None:
        return _CHANNEL_IN, _CHANNEL_OUT
    try:
        real_in = os.fdopen(os.dup(0), "rb", buffering=0)
        real_out = os.fdopen(os.dup(1), "wb", buffering=0)
    except OSError:
        # No real descriptors (e.g. under a test harness): use the streams.
        return sys.stdin.buffer, sys.stdout.buffer

    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(devnull, 0)
        os.dup2(2, 1)
    finally:
        os.close(devnull)
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr

    _CHANNEL_IN, _CHANNEL_OUT = real_in, real_out
    return real_in, real_out


def _emit(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, default=str) + "\n"
    channel = _CHANNEL_OUT
    with _WRITE_LOCK:
        if channel is None:
            sys.__stdout__.write(line)
            sys.__stdout__.flush()
        else:
            channel.write(line.encode("utf-8"))
            channel.flush()


class Session:
    """Holds loaded sources and arrangements between calls.

    This is what makes retuning an arrangement instant: the expensive stages
    (decode, stems, transcription) stay in memory keyed by source id, and only
    ``arrange`` re-runs.
    """

    def __init__(self) -> None:
        self.sources: dict[str, SourceMaterial] = {}
        self.arrangements: dict[str, Arrangement] = {}
        self.tokens: dict[int, CancellationToken] = {}
        self.cache = Cache()
        self.log = get_logger("server")

    def token_for(self, request_id: int) -> CancellationToken:
        token = CancellationToken()
        self.tokens[request_id] = token
        return token

    def release(self, request_id: int) -> None:
        self.tokens.pop(request_id, None)


SESSION = Session()


def _reporter(request_id: int) -> ProgressReporter:
    def send(event: ProgressEvent) -> None:
        _emit({
            "id": request_id,
            "type": "event",
            "event": "progress",
            "payload": event.to_dict(),
        })

    return ProgressReporter(send, token=SESSION.token_for(request_id))


# -- methods -------------------------------------------------------------


def m_ping(_params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    return {"ok": True, "versions": version_dict()}


def m_environment(_params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    return environment_report()


def m_instrument(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    from .shawzin.instrument import load_instrument

    instrument = load_instrument(params.get("variant", "dax"))
    data = instrument.to_dict()
    data["variants"] = [v.to_dict() for v in instrument.variants()]
    return data


def m_analyze(params: dict[str, Any], request_id: int) -> dict[str, Any]:
    options = ArrangementOptions.from_dict(params.get("options") or {})
    reporter = _reporter(request_id)
    source = load_source(
        params["path"],
        options,
        progress=reporter,
        cache=SESSION.cache,
        use_stems=bool(params.get("useStems", True)),
        transcriber_preference=params.get("transcriber", "auto"),
        max_seconds=params.get("maxSeconds"),
        device=params.get("device", "auto"),
    )
    source_id = source.content_hash[:16] + ":" + source.kind
    SESSION.sources[source_id] = source
    payload = source.to_dict(include_events=bool(params.get("includeEvents", True)))
    payload["sourceId"] = source_id
    return payload


def m_arrange(params: dict[str, Any], request_id: int) -> dict[str, Any]:
    source_id = params["sourceId"]
    source = SESSION.sources.get(source_id)
    if source is None:
        raise ShawzifyError(
            "That track is no longer loaded.",
            hint="Drop the file in again to re-analyse it.",
        )
    options = ArrangementOptions.from_dict(params.get("options") or {})
    reporter = _reporter(request_id)
    arrangement = arrange_source(source, options, progress=reporter)
    SESSION.arrangements[source_id] = arrangement

    payload = arrangement.to_dict(include_decisions=bool(params.get("includeDecisions", True)))
    payload["sourceId"] = source_id
    payload["outputNotes"] = [n.to_dict() for n in arrangement.output_notes()]
    payload["liveEvents"] = [
        {
            "at": ev.tick / arrangement.instrument.format.ticks_per_second,
            "fret": ev.fret,
            "string": ev.string,
        }
        for ev in arrangement.song.events
    ]

    from .shawzin.split import needs_split, split_arrangement
    from .shawzin.tab import render_tab

    over, reasons = needs_split(arrangement.song, arrangement.instrument)
    if over:
        parts = split_arrangement(arrangement.song, arrangement.instrument, bpm=source.bpm)
        payload["parts"] = [
            p.to_dict(arrangement.instrument.format.ticks_per_second) for p in parts
        ]
        payload["splitReasons"] = reasons
        # A single code would exceed the game's limits, so lead with part one.
        payload["code"] = parts[0].code if parts else ""
        arrangement.report.parts = len(parts)
        payload["report"] = arrangement.report.to_dict()
    else:
        payload["parts"] = []
        payload["splitReasons"] = []
        payload["code"] = arrangement.to_code()
    payload["tab"] = render_tab(arrangement.song, arrangement.instrument, max_rows=400)

    # The UI wants these next to the arrangement, and both are cheap once the
    # arrangement exists.
    from .shawzin.recommend import profile_music, recommend_shawzin

    profile = profile_music(source.events, duration=source.duration)
    payload["musicProfile"] = profile.to_dict()
    payload["shawzinSuggestions"] = [
        s.to_dict()
        for s in recommend_shawzin(
            profile,
            song=arrangement.song,
            instrument=arrangement.instrument,
            prefer_variant=options.shawzin_variant,
            top_n=5,
        )
    ]
    return payload


def m_sources(_params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Which input routes are usable right now, and why not when they are not."""
    from .sources import SourceResolver

    return {"providers": SourceResolver().describe()}


def m_identify(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Metadata for a link, without downloading anything."""
    from .sources import SourceResolver

    return SourceResolver(SESSION.cache).preview(params["target"]).to_dict()


def m_search(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Free-text search across whichever providers are configured."""
    from .sources import SourceResolver

    resolver = SourceResolver(SESSION.cache)
    found = resolver.search(params["query"], limit=int(params.get("limit", 6)))
    return {"results": [c.to_dict() for c in found]}


def m_fetch(params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Download a link to local audio, then analyse it like any other file."""
    from .sources import SourceResolver

    reporter = _reporter(request_id)
    resolver = SourceResolver(SESSION.cache)
    reporter.skip("stems")

    def report(fraction: float, message: str = "") -> None:
        reporter.update("decode", fraction, message)

    resolved = resolver.fetch(
        params["target"],
        progress=report,
        candidate_index=int(params.get("candidateIndex", 0)),
    )
    reporter.finish("decode", "Fetched " + resolved.reference.display)

    payload: dict[str, Any] = {"source": resolved.to_dict()}
    if params.get("analyze", True) and resolved.path is not None:
        analysis = m_analyze(
            {**params, "path": str(resolved.path), "requestId": request_id}, request_id
        )
        # The provider knows the real title; a cache filename does not.
        analysis["title"] = resolved.reference.display or analysis.get("title")
        analysis["track"] = resolved.reference.to_dict()
        analysis["matchConfidence"] = resolved.match_confidence
        analysis["matchReason"] = resolved.match_reason
        analysis["warnings"] = list(analysis.get("warnings") or []) + resolved.warnings
        source = SESSION.sources.get(analysis["sourceId"])
        if source is not None:
            source.title = analysis["title"]
            source.warnings = analysis["warnings"]
        payload.update(analysis)
    return payload


def m_recommend_shawzin(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Rank the eleven Shawzins for the arrangement currently loaded."""
    from .shawzin.recommend import profile_music, recommend_shawzin

    source_id = params.get("sourceId")
    source = SESSION.sources.get(source_id or "")
    arrangement = SESSION.arrangements.get(source_id or "")
    if source is None:
        raise ShawzifyError("There is nothing loaded to recommend a Shawzin for.")
    profile = profile_music(source.events, duration=source.duration)
    suggestions = recommend_shawzin(
        profile,
        song=arrangement.song if arrangement else None,
        instrument=arrangement.instrument if arrangement else None,
        prefer_variant=params.get("current"),
        top_n=int(params.get("limit", 11)),
    )
    return {
        "profile": profile.to_dict(),
        "suggestions": [s.to_dict() for s in suggestions],
    }


def m_structure(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Sections, repeats and the hook for the loaded track."""
    from .music.structure import analyze_structure, best_window, melodic_hook

    source = SESSION.sources.get(params.get("sourceId") or "")
    if source is None:
        raise ShawzifyError("There is nothing loaded to analyse.")
    structure = analyze_structure(source.events, bpm=source.bpm, duration=source.duration)
    limit = float(params.get("windowSeconds", 240.0))
    window = best_window(structure, window_seconds=limit, total_seconds=source.duration)
    return {
        "structure": structure.to_dict(),
        "bestWindow": {"startSeconds": round(window[0], 2), "endSeconds": round(window[1], 2)},
        "hookNotes": [n.to_dict() for n in melodic_hook(source.events, structure)],
    }


def m_spotify_credentials(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Read or store the user's own Spotify app credentials."""
    from .sources.spotify import SpotifyCredentials, SpotifyProvider

    if params.get("save") is not None:
        data = params["save"] or {}
        credentials = SpotifyCredentials(
            client_id=str(data.get("clientId", "")).strip(),
            client_secret=str(data.get("clientSecret", "")).strip(),
        )
        credentials.save()
    else:
        credentials = SpotifyCredentials.load()
    provider = SpotifyProvider(credentials)
    usable, reason = provider.available()
    return {
        "configured": credentials.configured,
        "clientId": credentials.client_id,
        "available": usable,
        "detail": reason,
        # The secret is never sent back to the UI.
        "hasSecret": bool(credentials.client_secret),
    }


def m_decode(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    from .shawzin.instrument import load_instrument
    from .shawzin.songcode import describe

    return describe(params["code"], load_instrument(params.get("variant", "dax")))


def m_preview(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """Render a preview WAV and return its path, for the frontend to play."""
    import soundfile as sf

    from .common.paths import cache_dir
    from .music.events import NoteEvent
    from .preview.synth import render_preview

    events = [NoteEvent.from_dict(e) for e in params.get("events") or []]
    if not events:
        source_id = params.get("sourceId")
        arrangement = SESSION.arrangements.get(source_id or "")
        if arrangement is None:
            raise ShawzifyError("There is nothing to preview yet.")
        events = arrangement.output_notes()
    sample_rate = int(params.get("sampleRate", 44100))
    audio = render_preview(events, sample_rate=sample_rate)
    name = "preview-" + str(abs(hash((params.get("sourceId"), len(events))))) + ".wav"
    path = Path(cache_dir()) / "preview" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate, subtype="PCM_16")
    return {
        "path": str(path),
        "durationSeconds": len(audio) / sample_rate,
        "sampleRate": sample_rate,
    }


def m_export(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    from .common.safety import safe_output_path
    from .midi.writer import write_midi
    from .preview.synth import write_preview_wav
    from .project import build_project, remember_project, save_project

    source_id = params["sourceId"]
    kind = params["kind"]
    target = safe_output_path(params["path"])
    source = SESSION.sources.get(source_id)
    arrangement = SESSION.arrangements.get(source_id)
    if source is None or arrangement is None:
        raise ShawzifyError("There is nothing to export yet.")

    if kind == "code":
        target.write_text(arrangement.to_code() + "\n", encoding="utf-8")
    elif kind == "midi":
        write_midi(arrangement.output_notes(), target, bpm=source.bpm,
                   track_name="SHAWZIFY arrangement")
    elif kind == "sourceMidi":
        write_midi(source.events, target, bpm=source.bpm, track_name="SHAWZIFY source")
    elif kind == "preview":
        write_preview_wav(arrangement.output_notes(), target)
    elif kind == "analysis":
        target.write_text(
            json.dumps(
                {
                    "source": source.to_dict(include_events=True),
                    "arrangement": arrangement.to_dict(),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    elif kind == "project":
        project = build_project(source, arrangement)
        target = save_project(project, target)
        remember_project(
            title=project.title,
            path=str(target),
            compatibility=arrangement.report.compatibility_after.overall * 100.0,
            source_path=source.path,
            kind=source.kind,
        )
    else:
        raise ShawzifyError("SHAWZIFY does not know how to export '" + str(kind) + "'.")
    return {"path": str(target), "kind": kind}


def m_open_project(params: dict[str, Any], request_id: int) -> dict[str, Any]:
    from .arrangement.arranger import arrange_for_shawzin
    from .project import load_project
    from .shawzin.instrument import load_instrument

    project = load_project(params["path"])
    options = project.arrangement_options()
    instrument = load_instrument(options.shawzin_variant)
    events = project.events()
    arrangement = arrange_for_shawzin(
        events, instrument, options, bpm=project.bpm, key=project.key_estimate()
    )
    source = SourceMaterial(
        kind=project.source_kind,
        path=project.source_path,
        title=project.title,
        duration=project.duration,
        events=events,
        key=project.key_estimate(),
        bpm=project.bpm,
        bpm_confidence=project.bpm_confidence,
        content_hash=project.content_hash,
        transcription_backend="project",
        stem_used="project",
    )
    source_id = (project.content_hash or "project")[:16] + ":" + project.source_kind
    SESSION.sources[source_id] = source
    SESSION.arrangements[source_id] = arrangement
    return {
        "sourceId": source_id,
        "project": project.to_dict(),
        "source": source.to_dict(),
        "reproducible": project.is_reproducible(),
        "code": arrangement.to_code(),
    }


def m_recents(_params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    from .project import load_recents

    return {"recents": load_recents()}


def m_keymap(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    from .live.keymap import BINDING_LABELS, DEFAULT_BINDINGS, WarframeKeymap

    if params.get("save"):
        keymap = WarframeKeymap.from_dict(params["save"])
        keymap.save()
    else:
        keymap = WarframeKeymap.load()
    return {
        "keymap": keymap.to_dict(),
        "labels": BINDING_LABELS,
        "defaults": DEFAULT_BINDINGS,
        "problems": keymap.validate(),
    }


def m_diagnostics(_params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    """The Copy Debug Info payload. Paths are redacted, file contents never included."""
    import platform

    from .common.logging import get_logger
    from .common.paths import log_dir, model_dir, redact

    report = environment_report()
    log = get_logger()
    return {
        "app": version_dict(),
        "os": platform.platform(),
        "python": report["python"],
        "ffmpeg": report["ffmpeg"],
        "gpu": report["gpu"],
        "transcribers": report["transcribers"],
        "separators": report["separators"],
        "cacheBytes": report["cacheBytes"],
        "logPath": redact(log.path),
        "logDir": redact(log_dir()),
        "modelDir": redact(model_dir()),
        "stageTimings": log.timings_dict(),
        "loadedSources": len(SESSION.sources),
    }


def m_cancel(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    target = int(params.get("requestId", 0))
    token = SESSION.tokens.get(target)
    if token is not None:
        token.cancel()
        return {"cancelled": True, "requestId": target}
    return {"cancelled": False, "requestId": target}


def m_clear_cache(params: dict[str, Any], _request_id: int) -> dict[str, Any]:
    SESSION.cache.clear(params.get("namespace"))
    return {"cacheBytes": SESSION.cache.size_bytes()}


METHODS: dict[str, Callable[[dict[str, Any], int], dict[str, Any]]] = {
    "ping": m_ping,
    "environment": m_environment,
    "instrument": m_instrument,
    "analyze": m_analyze,
    "arrange": m_arrange,
    "sources": m_sources,
    "identify": m_identify,
    "search": m_search,
    "fetch": m_fetch,
    "recommendShawzin": m_recommend_shawzin,
    "structure": m_structure,
    "spotifyCredentials": m_spotify_credentials,
    "decode": m_decode,
    "preview": m_preview,
    "export": m_export,
    "openProject": m_open_project,
    "recents": m_recents,
    "keymap": m_keymap,
    "diagnostics": m_diagnostics,
    "cancel": m_cancel,
    "clearCache": m_clear_cache,
}

#: Methods answered inline; everything else runs on a worker thread so that
#: progress events and ``cancel`` keep flowing during long work.
FAST_METHODS = {"ping", "cancel", "recents", "instrument", "keymap", "sources"}


def _handle(request: dict[str, Any]) -> None:
    request_id = int(request.get("id", 0))
    method = str(request.get("method", ""))
    params = request.get("params") or {}
    handler = METHODS.get(method)
    if handler is None:
        _emit({
            "id": request_id,
            "type": "result",
            "error": {
                "code": "unknown_method",
                "message": "The audio engine does not support '" + method + "'.",
                "hint": None,
                "technical": None,
            },
        })
        return
    try:
        result = handler(params, request_id)
        _emit({"id": request_id, "type": "result", "result": result})
    except ShawzifyError as exc:
        SESSION.log.error(method, exc, requestId=request_id)
        _emit({"id": request_id, "type": "result", "error": exc.to_dict()})
    except Exception as exc:  # noqa: BLE001 - never let one call kill the engine
        SESSION.log.error(method, exc, requestId=request_id)
        _emit({
            "id": request_id,
            "type": "result",
            "error": {
                "code": "internal_error",
                "message": "SHAWZIFY hit an unexpected problem while running '"
                + method
                + "'.",
                "hint": "The details below help diagnose it; nothing was sent anywhere.",
                "technical": traceback.format_exc(),
            },
        })
    finally:
        SESSION.release(request_id)


def serve(stdin=None, stdout=None) -> int:
    """Read requests until the input closes or a shutdown is requested.

    ``stdin``/``stdout`` are test seams; in production both come from
    :func:`claim_channels`.
    """
    global _emit  # noqa: PLW0603 - test seam

    if stdin is None and stdout is None:
        source, _sink = claim_channels()
    else:
        source = stdin if stdin is not None else sys.stdin
        if stdout is not None:

            def _emit_to(payload: dict[str, Any]) -> None:
                stdout.write(json.dumps(payload, default=str) + "\n")
                stdout.flush()

            _emit = _emit_to  # type: ignore[assignment]

    SESSION.log.event("server.start", versions=version_dict())
    workers: list[threading.Thread] = []
    while True:
        # readline() rather than iterating the file: iteration uses read-ahead
        # buffering, which would stall until a whole buffer's worth of requests
        # arrived instead of answering each one as it comes in.
        raw = source.readline()
        if not raw:
            break
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if request.get("method") == "shutdown":
            break
        if request.get("method") in FAST_METHODS:
            _handle(request)
            continue
        worker = threading.Thread(target=_handle, args=(request,), daemon=True)
        worker.start()
        workers.append(worker)
        workers = [w for w in workers if w.is_alive()]
    SESSION.log.event("server.stop")
    return 0


def main() -> int:
    try:
        return serve()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

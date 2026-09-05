"""The top-level conversion pipeline.

Stages are cached independently and keyed by what they actually depend on, so
changing an arrangement setting re-runs only the arrangement -- never stem
separation or transcription. That is what makes the arrangement controls feel
instant once a track has been analysed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .arrangement.arranger import Arrangement, arrange_for_shawzin
from .arrangement.options import ArrangementOptions, StemSource
from .audio.analysis import TrackAnalysis, analyze_audio_buffer
from .audio.decode import AudioMetadata, load_audio
from .audio.ffmpeg import find_ffmpeg
from .audio.waveform import WaveformPeaks, compute_peaks
from .common.cache import Cache, hash_file, hash_payload, make_key
from .common.errors import StemSeparationError, TranscriptionError
from .common.logging import get_logger
from .common.progress import ProgressReporter
from .common.safety import classify_input, resolve_input_path
from .midi.reader import MidiFileData, choose_melody_track, parse_midi
from .music.events import NoteEvent
from .music.key import KeyEstimate, estimate_key
from .shawzin.instrument import load_instrument
from .stems import StemSet, select_separator
from .transcription import select_transcriber
from .version import ANALYSIS_VERSION, TRANSCRIPTION_VERSION, version_dict

ANALYSIS_SAMPLE_RATE = 44100


@dataclass
class SourceMaterial:
    """Everything derived from the input, before any arrangement decisions."""

    kind: str  # "audio" | "midi"
    path: str
    title: str
    duration: float
    events: list[NoteEvent] = field(default_factory=list)
    metadata: AudioMetadata | None = None
    analysis: TrackAnalysis | None = None
    waveform: WaveformPeaks | None = None
    midi: MidiFileData | None = None
    key: KeyEstimate | None = None
    bpm: float = 120.0
    bpm_confidence: float = 0.0
    stems: StemSet | None = None
    transcription_backend: str = ""
    stem_used: str = ""
    content_hash: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "title": self.title,
            "durationSeconds": round(self.duration, 3),
            "noteCount": len(self.events),
            "bpm": round(self.bpm, 2),
            "bpmConfidence": round(self.bpm_confidence, 3),
            "key": self.key.to_dict() if self.key else None,
            "transcriptionBackend": self.transcription_backend,
            "stemUsed": self.stem_used,
            "contentHash": self.content_hash[:16],
            "warnings": self.warnings,
        }
        if self.metadata:
            d["audio"] = self.metadata.to_dict()
        if self.analysis:
            d["analysis"] = self.analysis.to_dict()
        if self.waveform:
            d["waveform"] = self.waveform.to_dict()
        if self.midi:
            d["midi"] = self.midi.to_dict()
        if include_events:
            d["events"] = [e.to_dict() for e in self.events]
        return d


def _pick_stem(
    stems: StemSet, preference: StemSource, analysis: TrackAnalysis | None
) -> tuple[np.ndarray | None, str]:
    """Choose which stem to transcribe. AUTO picks by measured content."""
    if preference is StemSource.FULL_MIX:
        return (None, "full")
    if preference in (StemSource.VOCALS, StemSource.BASS, StemSource.DRUMS, StemSource.OTHER):
        got = stems.get(preference.value)
        if got is not None:
            return (got, preference.value)
        return (None, "full")
    if preference is StemSource.INSTRUMENTAL:
        return (stems.instrumental(), "instrumental")

    # AUTO: prefer the vocal when there is a substantial one (that is almost
    # always the melody a listener would hum); otherwise use the pitched mix.
    vocals = stems.get("vocals")
    melodic = stems.melodic()
    if vocals is not None and melodic is not None:
        v_energy = float(np.sqrt(np.mean(np.square(vocals, dtype=np.float64))))
        m_energy = float(np.sqrt(np.mean(np.square(melodic, dtype=np.float64)))) or 1e-9
        if v_energy / m_energy > 0.28:
            return (vocals, "vocals")
    if melodic is not None:
        return (melodic, "melodic")
    return (None, "full")


def load_source(
    path: str | Path,
    options: ArrangementOptions | None = None,
    *,
    progress: ProgressReporter | None = None,
    cache: Cache | None = None,
    use_stems: bool = True,
    transcriber_preference: str = "auto",
    max_seconds: float | None = None,
    device: str = "auto",
) -> SourceMaterial:
    """Decode/transcribe an input into canonical note events plus analysis."""
    opts = options or ArrangementOptions()
    log = get_logger("pipeline")
    log.reset_timings()
    cache = cache or Cache()
    reporter = progress or ProgressReporter()

    resolved = resolve_input_path(path)
    kind = classify_input(resolved)
    content_hash = hash_file(resolved)

    if kind == "midi":
        for stage in ("decode", "waveform", "stems", "analyze"):
            reporter.skip(stage)
        reporter.start("transcribe", "Reading MIDI")
        with log.stage("midi.parse") as detail:
            data = parse_midi(resolved)
            detail["notes"] = len(data.events)
        events = data.events
        warnings: list[str] = []
        if not events:
            warnings.append("This MIDI file contains no pitched notes.")
        melody_track = choose_melody_track(data)
        if melody_track is not None and len(data.tracks) > 1:
            warnings.append(
                "AUTO selected track " + str(melody_track) + " ("
                + data.tracks[melody_track].name + ") as the likely melody."
            )
        reporter.finish("transcribe", "Read " + str(len(events)) + " notes")
        key = estimate_key(events) if events else None
        return SourceMaterial(
            kind="midi",
            path=str(resolved),
            title=data.title,
            duration=data.duration,
            events=events,
            midi=data,
            key=key,
            bpm=data.tempo_bpm,
            bpm_confidence=1.0,  # a MIDI file states its tempo
            transcription_backend="midi",
            stem_used="n/a",
            content_hash=content_hash,
            warnings=warnings,
        )

    # -- audio ----------------------------------------------------------
    warnings = []
    ff = find_ffmpeg()
    reporter.start("decode", "Loading audio")
    with log.stage("audio.decode") as detail:
        buffer = load_audio(resolved, sample_rate=ANALYSIS_SAMPLE_RATE, mono=True,
                            max_seconds=max_seconds)
        detail["duration"] = round(buffer.duration, 2)
        detail["ffmpeg"] = ff.source
    reporter.finish("decode")

    reporter.start("waveform", "Drawing waveform")
    with log.stage("audio.waveform"):
        peaks = compute_peaks(buffer.mono(), buffer.sample_rate, buckets=1600)
    reporter.finish("waveform")

    mono = buffer.mono()

    # Stems
    stems: StemSet | None = None
    separator = select_separator(use_stems, device=device)
    if separator.id == "none":
        reporter.skip("stems")
        if use_stems:
            warnings.append(
                "Stem separation is unavailable, so SHAWZIFY is transcribing the full mix."
            )
    else:
        reporter.start("stems", "Separating stems")
        try:
            with log.stage("audio.stems") as detail:
                stems = separator.separate(
                    mono,
                    buffer.sample_rate,
                    progress=lambda f, m="": reporter.update("stems", f, m),
                    content_hash=content_hash,
                )
                detail["backend"] = stems.backend
                detail["device"] = stems.device
            reporter.finish("stems")
        except StemSeparationError as exc:
            log.warn("stems.failed", error=exc.message)
            warnings.append(exc.message + " SHAWZIFY is using the full mix.")
            reporter.skip("stems")
            stems = None

    reporter.start("analyze", "Detecting rhythm and key")
    analysis_key = make_key(content_hash, hash_payload({"v": ANALYSIS_VERSION}))
    cached_analysis = cache.get_json("analysis", analysis_key)
    if cached_analysis:
        analysis = TrackAnalysis(
            duration=cached_analysis["durationSeconds"],
            tempo_bpm=cached_analysis["tempoBpm"],
            tempo_confidence=cached_analysis["tempoConfidence"],
            key=cached_analysis["key"],
            mode=cached_analysis["mode"],
            key_confidence=cached_analysis["keyConfidence"],
            time_signature_estimate=cached_analysis["timeSignatureEstimate"],
            energy=cached_analysis["energy"],
            onset_density=cached_analysis["onsetDensity"],
            pitch_range=tuple(cached_analysis["pitchRange"]),
            polyphony_estimate=cached_analysis["polyphonyEstimate"],
            tonic_pitch_class=cached_analysis["tonicPitchClass"],
            backend=cached_analysis["backend"],
        )
    else:
        with log.stage("audio.analyze") as detail:
            analysis = analyze_audio_buffer(mono, buffer.sample_rate)
            detail["bpm"] = round(analysis.tempo_bpm, 2)
            detail["key"] = analysis.key + " " + analysis.mode
        cache.put_json("analysis", analysis_key, analysis.to_dict())
    reporter.finish("analyze")

    # Transcription
    source_samples = mono
    source_rate = buffer.sample_rate
    stem_used = "full"
    if stems is not None:
        picked, stem_used = _pick_stem(stems, opts.stem_source, analysis)
        if picked is not None:
            source_samples = picked
            source_rate = stems.sample_rate

    polyphonic = analysis.polyphony_estimate > 1.8 or stem_used not in ("vocals",)
    transcriber = select_transcriber(transcriber_preference, polyphonic=polyphonic)
    transcribe_key = make_key(
        content_hash,
        hash_payload(
            {
                "v": TRANSCRIPTION_VERSION,
                "backend": transcriber.id,
                "stem": stem_used,
                "sr": source_rate,
            }
        ),
    )
    cached_notes = cache.get_json("transcription", transcribe_key)
    reporter.start("transcribe", "Transcribing notes with " + transcriber.name)
    if cached_notes:
        events = [NoteEvent.from_dict(d) for d in cached_notes["events"]]
        backend_id = cached_notes.get("backend", transcriber.id)
        log.event("transcription.cache_hit", backend=backend_id, notes=len(events))
    else:
        try:
            with log.stage("audio.transcribe") as detail:
                result = transcriber.transcribe(
                    source_samples,
                    source_rate,
                    progress=lambda f, m="": reporter.update("transcribe", f, m),
                )
                detail["backend"] = result.backend
                detail["notes"] = len(result.events)
            events = result.events
            backend_id = result.backend
        except TranscriptionError as exc:
            log.warn("transcription.failed", error=exc.message)
            fallback = select_transcriber("cqt", polyphonic=True)
            warnings.append(exc.message + " SHAWZIFY fell back to the built-in transcriber.")
            result = fallback.transcribe(source_samples, source_rate)
            events = result.events
            backend_id = result.backend
        cache.put_json(
            "transcription",
            transcribe_key,
            {"backend": backend_id, "events": [e.to_dict() for e in events]},
        )
    reporter.finish("transcribe", "Found " + str(len(events)) + " notes")

    if not events:
        warnings.append(
            "No notes could be transcribed from this audio. It may be percussion-only, "
            "very quiet, or heavily processed."
        )

    key = estimate_key(events) if events else None
    if key is None or key.confidence < 0.25:
        # Fall back to the spectral key estimate when the note-based one is weak.
        key = KeyEstimate(
            analysis.tonic_pitch_class, analysis.mode, analysis.key_confidence, 0.0
        )

    return SourceMaterial(
        kind="audio",
        path=str(resolved),
        title=buffer.metadata.title or resolved.stem,
        duration=buffer.duration,
        events=events,
        metadata=buffer.metadata,
        analysis=analysis,
        waveform=peaks,
        key=key,
        bpm=analysis.tempo_bpm,
        bpm_confidence=analysis.tempo_confidence,
        stems=stems,
        transcription_backend=backend_id,
        stem_used=stem_used,
        content_hash=content_hash,
        warnings=warnings,
    )


def arrange_source(
    source: SourceMaterial,
    options: ArrangementOptions | None = None,
    *,
    progress: ProgressReporter | None = None,
) -> Arrangement:
    """Arrange already-loaded material. Cheap enough to re-run interactively."""
    opts = options or ArrangementOptions()
    log = get_logger("pipeline")
    reporter = progress or ProgressReporter()
    instrument = load_instrument(opts.shawzin_variant)

    reporter.start("arrange", "Optimizing arrangement")
    with log.stage("arrange") as detail:
        arrangement = arrange_for_shawzin(
            source.events,
            instrument,
            opts,
            bpm=source.bpm,
            bpm_confidence=source.bpm_confidence,
            key=source.key,
            progress=lambda f, m="": reporter.update("arrange", f, m),
        )
        detail["scale"] = arrangement.report.scale_name
        detail["transpose"] = arrangement.report.transpose
        detail["notes"] = arrangement.song.note_count
    reporter.finish("arrange")

    reporter.start("encode", "Encoding performance")
    with log.stage("encode") as detail:
        # An over-long arrangement has no single valid code; splitting produces
        # importable parts, so this is not a failure.
        if arrangement.over_limits:
            detail["overLimits"] = True
            detail["codeLength"] = 0
        else:
            detail["codeLength"] = len(arrangement.to_code())
    reporter.finish("encode")

    arrangement.report.stage_timings = log.timings_dict()
    arrangement.report.warnings = list(source.warnings) + list(arrangement.report.warnings)
    arrangement.report.engine_versions = version_dict()
    return arrangement


def convert(
    path: str | Path,
    options: ArrangementOptions | None = None,
    *,
    progress: ProgressReporter | None = None,
    use_stems: bool = True,
    transcriber_preference: str = "auto",
    max_seconds: float | None = None,
    device: str = "auto",
) -> tuple[SourceMaterial, Arrangement]:
    """Full one-shot conversion: file in, arrangement out."""
    reporter = progress or ProgressReporter()
    source = load_source(
        path,
        options,
        progress=reporter,
        use_stems=use_stems,
        transcriber_preference=transcriber_preference,
        max_seconds=max_seconds,
        device=device,
    )
    arrangement = arrange_source(source, options, progress=reporter)
    return (source, arrangement)


def environment_report() -> dict[str, Any]:
    """First-run diagnostics: what is installed and usable right now."""
    import platform
    import sys

    from .audio.analysis import librosa_available
    from .stems import describe_separators, gpu_info
    from .transcription import describe_backends

    ff = find_ffmpeg()
    gpu = gpu_info()
    return {
        "app": version_dict(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": ff.to_dict(),
        "librosa": librosa_available(),
        "gpu": gpu,
        "transcribers": describe_backends(),
        "separators": describe_separators(),
        "cacheBytes": Cache().size_bytes(),
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

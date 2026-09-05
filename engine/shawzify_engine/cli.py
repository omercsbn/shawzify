"""SHAWZIFY command line.

    shawzify analyze song.mp3
    shawzify convert song.mp3 --mode melody --scale auto --transpose auto
    shawzify convert input.mid -o out.txt
    shawzify convert "https://youtube.com/watch?v=..." --focus hook
    shawzify convert "https://open.spotify.com/track/..."
    shawzify fetch "https://youtu.be/..." -o song.m4a
    shawzify shawzins song.mp3
    shawzify structure song.mp3
    shawzify decode 1BAACAIEAQJAYKAgMAo
    shawzify encode project.shawzify
    shawzify web
    shawzify doctor
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .arrangement.options import AUTO, ArrangementMode, ArrangementOptions, Focus, StemSource
from .common.console import use_utf8
from .common.errors import ShawzifyError
from .common.progress import ProgressEvent, ProgressReporter
from .version import APP_VERSION


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def _banner() -> str:
    return "\nSHAWZIFY " + APP_VERSION + "\n"


class _Printer:
    def __init__(self, quiet: bool = False, as_json: bool = False) -> None:
        self.quiet = quiet or as_json
        self.as_json = as_json
        self._last_stage = ""

    def line(self, text: str = "") -> None:
        if not self.quiet:
            print(text)

    def field(self, label: str, value: Any) -> None:
        if not self.quiet:
            print("{:<24} {}".format(label + ":", value))

    def progress(self, event: ProgressEvent) -> None:
        if self.quiet:
            return
        if event.stage != self._last_stage:
            self._last_stage = event.stage
            print(f"  [{event.overall_fraction * 100:>3.0f}%] {event.label}")
        elif event.message and event.stage_fraction >= 1.0:
            print(f"         {event.message}")


def _resolve_input(args: argparse.Namespace, printer: _Printer) -> str:
    """Turn whatever was given into a local file path, fetching if needed."""
    from .sources import SourceResolver, looks_like_url

    target = args.input
    if not looks_like_url(target):
        return target

    resolver = SourceResolver()
    printer.line("Fetching " + target)
    last = {"stage": ""}

    def report(fraction: float, message: str = "") -> None:
        if message and message != last["stage"]:
            last["stage"] = message
            printer.line(f"  [{fraction * 100:>3.0f}%] {message}")

    resolved = resolver.fetch(
        target,
        progress=None if printer.quiet else report,
        candidate_index=getattr(args, "candidate", 0),
    )
    if resolved.path is None:
        raise ShawzifyError("No audio could be fetched for that link.")
    printer.field("Track", resolved.reference.display)
    if resolved.match_confidence < 0.999:
        printer.field(
            "Match", f"{resolved.match_confidence:.0%} - {resolved.match_reason}"
        )
    for warning in resolved.warnings:
        printer.line("  ! " + warning)
    printer.line()
    return str(resolved.path)


def _options_from_args(args: argparse.Namespace) -> ArrangementOptions:
    def auto_or(value: str, cast: Any = None) -> Any:
        if value is None or str(value).lower() == "auto":
            return AUTO
        return cast(value) if cast else value

    quant = "auto" if args.quantize is None else args.quantize
    focus = getattr(args, "focus", "auto")
    return ArrangementOptions(
        mode=ArrangementMode(args.mode),
        scale=auto_or(args.scale),
        transpose=auto_or(args.transpose, int),
        quantization=AUTO if quant == "auto" else quant,
        quantization_strength=args.quantize_strength,
        complexity=args.complexity,
        preserve_melody=not args.no_preserve_melody,
        arpeggiate_chords=AUTO if args.arpeggiate is None else args.arpeggiate,
        max_density=auto_or(args.max_density, float),
        shawzin_variant=args.shawzin,
        stem_source=StemSource(args.stem),
        focus=AUTO if focus in (None, "auto") else Focus(focus),
        use_structure=not getattr(args, "no_structure", False),
    )


# -- commands ------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace) -> int:
    from .pipeline import load_source

    printer = _Printer(args.quiet, args.json)
    reporter = ProgressReporter(printer.progress)
    source = load_source(
        _resolve_input(args, printer),
        _options_from_args(args),
        progress=reporter,
        use_stems=not args.no_stems,
        transcriber_preference=args.transcriber,
        max_seconds=args.max_seconds,
        device=args.device,
    )
    if args.json:
        print(json.dumps(source.to_dict(include_events=args.events), indent=2))
        return 0

    printer.line(_banner())
    printer.field("Input", Path(source.path).name)
    printer.field("Duration", _fmt_time(source.duration))
    printer.field("Tempo", f"{source.bpm:.1f} BPM  (confidence {source.bpm_confidence:.0%})")
    if source.key:
        printer.field("Detected Key", f"{source.key.name}  (confidence {source.key.confidence:.0%})")
    if source.analysis:
        printer.field("Onset Density", f"{source.analysis.onset_density:.2f} /s")
        printer.field("Polyphony", f"{source.analysis.polyphony_estimate:.1f} voices")
        printer.field("Analysis Backend", source.analysis.backend)
    printer.field("Transcription", source.transcription_backend)
    printer.field("Stem Used", source.stem_used)
    printer.field("Notes", f"{len(source.events):,}")
    if source.events:
        lo, hi = min(e.pitch_midi for e in source.events), max(e.pitch_midi for e in source.events)
        from .music.pitch import note_name

        printer.field("Pitch Range", note_name(lo) + " - " + note_name(hi))
    if source.events:
        # The structural picture is the part that says whether a listener would
        # recognise the result, so it belongs in the analysis, not behind a flag.
        from .music.structure import analyze_structure
        from .shawzin.recommend import profile_music, recommend_shawzin

        structure = analyze_structure(source.events, bpm=source.bpm, duration=source.duration)
        if len(structure.segments) > 1:
            printer.line()
            printer.field("Sections", str(len(structure.segments)))
            hook = structure.hook
            if hook:
                printer.field(
                    "Hook",
                    _fmt_time(hook.start_seconds)
                    + " - "
                    + _fmt_time(hook.end_seconds)
                    + "  (" + hook.role + ", "
                    + f"{hook.recognizability:.0%}" + " recognisable)",
                )
            roles = ", ".join(
                s.role + " " + _fmt_time(s.start_seconds) for s in structure.segments[:8]
            )
            printer.line("  " + roles + ("  ..." if len(structure.segments) > 8 else ""))

        profile = profile_music(source.events, duration=source.duration)
        best = recommend_shawzin(profile, top_n=1)
        if best:
            printer.line()
            printer.field("Best Shawzin", best[0].name + "  (" + best[0].timbre + ")")
            printer.line("  " + best[0].reasons[0])

    for w in source.warnings:
        printer.line("  ! " + w)
    printer.line()
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    from .arrangement.report import CompatibilityBreakdown
    from .pipeline import arrange_source, load_source
    from .project import build_project, remember_project, save_project
    from .shawzin.split import needs_split, split_arrangement
    from .shawzin.tab import render_tab

    printer = _Printer(args.quiet, args.json)
    reporter = ProgressReporter(printer.progress)
    options = _options_from_args(args)

    source = load_source(
        _resolve_input(args, printer),
        options,
        progress=reporter,
        use_stems=not args.no_stems,
        transcriber_preference=args.transcriber,
        max_seconds=args.max_seconds,
        device=args.device,
    )
    arrangement = arrange_source(source, options, progress=reporter)
    report = arrangement.report

    # Check the limits before encoding: an over-long arrangement is valid music
    # that needs splitting, not an error.
    parts = []
    over, reasons = needs_split(arrangement.song, arrangement.instrument)
    if over:
        parts = split_arrangement(arrangement.song, arrangement.instrument, bpm=source.bpm)
        report.parts = len(parts)
        report.warnings.extend(reasons)
        report.warnings.append(
            "The arrangement was split into " + str(len(parts)) + " Shawzin parts."
        )
        code = parts[0].code if parts else ""
    else:
        code = arrangement.to_code()

    # -- outputs --------------------------------------------------------
    stem = Path(source.path).stem
    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd()
    written: list[str] = []

    if not args.no_write:
        code_path = Path(args.output) if args.output else out_dir / (stem + ".shawzin.txt")
        code_path.parent.mkdir(parents=True, exist_ok=True)
        body = code if not parts else "\n\n".join(
            "Part " + str(p.index + 1) + "\n" + p.code for p in parts
        )
        code_path.write_text(body + "\n", encoding="utf-8")
        written.append(str(code_path))

    if args.export_midi:
        from .midi.writer import write_midi

        p = out_dir / (stem + ".arranged.mid")
        write_midi(arrangement.output_notes(), p, bpm=source.bpm, track_name="SHAWZIFY arrangement")
        written.append(str(p))
        p2 = out_dir / (stem + ".source.mid")
        write_midi(source.events, p2, bpm=source.bpm, track_name="SHAWZIFY source")
        written.append(str(p2))

    if args.export_preview:
        from .preview.synth import write_preview_wav

        p = out_dir / (stem + ".preview.wav")
        write_preview_wav(arrangement.output_notes(), p)
        written.append(str(p))

    if args.export_analysis:
        p = out_dir / (stem + ".analysis.json")
        p.write_text(
            json.dumps(
                {
                    "source": source.to_dict(include_events=True),
                    "arrangement": arrangement.to_dict(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written.append(str(p))

    if args.save_project:
        project = build_project(source, arrangement)
        p = save_project(project, args.save_project)
        remember_project(
            title=project.title,
            path=str(p),
            compatibility=report.compatibility_after.overall * 100.0,
            source_path=source.path,
            kind=source.kind,
        )
        written.append(str(p))

    if args.dry_run_live:
        from .live.player import dry_run

        presses, stats = dry_run(arrangement.song, instrument=arrangement.instrument)
        printer.line(f"\nLive dry run: {len(presses)} key presses")
        printer.line(f"  mean timing error {stats.mean_error * 1000:.3f} ms, max {stats.max_error * 1000:.3f} ms")

    if args.json:
        print(json.dumps({
            "source": source.to_dict(),
            "report": report.to_dict(),
            "code": code,
            "parts": [p.to_dict() for p in parts],
            "written": written,
            "resolved": arrangement.resolved.to_dict(),
        }, indent=2))
        return 0

    # -- human output ---------------------------------------------------
    printer.line(_banner())
    printer.field("Input", Path(source.path).name)
    printer.field("Duration", _fmt_time(source.duration))
    printer.field("Tempo", f"{source.bpm:.0f} BPM")
    if source.key:
        printer.field("Detected Key", source.key.name)
    printer.line()
    printer.field("Transcription", f"{len(source.events):,} notes ({source.transcription_backend})")
    printer.field("Recommended Scale", report.scale_name)
    printer.field("Transpose", f"{report.transpose:+d} semitones")
    printer.field("Mode", arrangement.resolved.mode.title())
    printer.field("Quantization", arrangement.resolved.quantization)
    if arrangement.resolved.focus_window:
        window = arrangement.resolved.focus_window
        printer.field(
            "Focus", "hook, " + _fmt_time(window[0]) + " - " + _fmt_time(window[1])
        )
    printer.line()
    before: CompatibilityBreakdown = report.compatibility_before
    after: CompatibilityBreakdown = report.compatibility_after
    printer.field("Compatibility", f"Original {before.overall * 100:.1f}%   Optimized {after.overall * 100:.1f}%")
    printer.line(f"  Pitch Coverage       {after.pitch_coverage * 100:>5.1f}%")
    printer.line(f"  Melody Preservation  {after.melody_preservation * 100:>5.1f}%")
    printer.line(f"  Rhythm Preservation  {after.rhythm_preservation * 100:>5.1f}%")
    printer.line(f"  Harmony Preservation {after.harmony_preservation * 100:>5.1f}%")
    printer.line()
    m = report.metrics
    printer.field("Result", f"{m.output_notes:,} of {m.source_notes:,} source notes played")
    printer.field("Song events", f"{len(arrangement.song.events):,} ({arrangement.song.note_count} plucks)")
    printer.field("Arrangement length", _fmt_time(report.duration_seconds))
    if report.parts > 1:
        printer.field("Parts", report.parts)

    if args.shawzin_advice:
        from .shawzin.recommend import profile_music, recommend_shawzin

        printer.line()
        printer.line("Recommended Shawzin")
        profile = profile_music(source.events, duration=source.duration)
        for suggestion in recommend_shawzin(
            profile, song=arrangement.song, instrument=arrangement.instrument, top_n=3
        ):
            d = suggestion.to_dict()
            printer.line("  {:>5.1f}  {:<22} {}".format(d["score"], d["name"], d["timbre"]))
            if d["reasons"]:
                printer.line("         " + d["reasons"][0])

    if args.tab:
        printer.line()
        printer.line(render_tab(arrangement.song, arrangement.instrument, max_rows=args.tab))

    if report.warnings:
        printer.line("\nWarnings")
        for w in report.warnings:
            printer.line("  - " + w)

    printer.line("\nShawzin code")
    if parts:
        for p in parts:
            printer.line(f"  Part {p.index + 1} ({p.note_count} notes)")
            printer.line("  " + p.code)
    else:
        printer.line("  " + code)

    if written:
        printer.line("\nOutput")
        for w in written:
            printer.line("  " + w)
    printer.line()
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download a link to local audio without arranging it."""
    import shutil

    from .sources import SourceResolver

    printer = _Printer(args.quiet, args.json)
    resolver = SourceResolver()
    resolved = resolver.fetch(
        args.target,
        progress=None if printer.quiet else (
            lambda f, m="": printer.line(f"  [{f * 100:>3.0f}%] {m}") if m else None
        ),
        candidate_index=args.candidate,
    )
    destination = resolved.path
    if args.output and resolved.path is not None:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved.path, destination)

    if args.json:
        payload = resolved.to_dict()
        payload["savedTo"] = str(destination) if destination else None
        print(json.dumps(payload, indent=2))
        return 0

    printer.line(_banner())
    printer.field("Track", resolved.reference.display)
    if resolved.reference.duration_seconds:
        printer.field("Duration", _fmt_time(resolved.reference.duration_seconds))
    printer.field("Source", resolved.kind)
    printer.field("Match", f"{resolved.match_confidence:.0%}")
    if resolved.match_reason:
        printer.line("  " + resolved.match_reason)
    printer.field("Audio", str(destination))
    for warning in resolved.warnings:
        printer.line("  ! " + warning)
    if resolved.alternatives and len(resolved.alternatives) > 1:
        printer.line()
        printer.line("Other candidates (--candidate N to pick one)")
        for i, candidate in enumerate(resolved.alternatives[:5]):
            printer.line(
                f"  {i}  {candidate.score:>5.0%}  {candidate.reference.display[:60]}"
            )
    printer.line()
    return 0


def cmd_shawzins(args: argparse.Namespace) -> int:
    """Recommend a Shawzin for a piece of music."""
    from .pipeline import arrange_source, load_source
    from .shawzin.recommend import profile_music, recommend_shawzin

    printer = _Printer(args.quiet, args.json)
    reporter = ProgressReporter(printer.progress)
    options = _options_from_args(args)
    source = load_source(
        _resolve_input(args, printer),
        options,
        progress=reporter,
        use_stems=not args.no_stems,
    )
    arrangement = arrange_source(source, options, progress=reporter)
    profile = profile_music(source.events, duration=source.duration)
    suggestions = recommend_shawzin(
        profile,
        song=arrangement.song,
        instrument=arrangement.instrument,
        top_n=args.limit,
    )

    if args.json:
        print(json.dumps(
            {"profile": profile.to_dict(), "suggestions": [x.to_dict() for x in suggestions]},
            indent=2,
        ))
        return 0

    printer.line(_banner())
    printer.field("Input", Path(source.path).name)
    printer.field("Notes", f"{len(source.events):,} at {profile.notes_per_second:.1f}/second")
    printer.field("Chords", f"{profile.chord_fraction:.0%} of moments")
    printer.field("Register", "median MIDI " + str(profile.median_pitch))
    printer.field("Note spacing", f"{profile.mean_gap_seconds:.2f}s average")
    printer.line()
    for i, suggestion in enumerate(suggestions):
        d = suggestion.to_dict()
        marker = "->" if i == 0 else "  "
        printer.line("{} {:>5.1f}  {}".format(marker, d["score"], d["name"]))
        printer.line("          {}".format(d["timbre"]))
        for reason in d["reasons"][:3]:
            printer.line("          + " + reason)
        for warning in d["warnings"][:3]:
            printer.line("          ! " + warning)
        printer.line()
    return 0


def cmd_structure(args: argparse.Namespace) -> int:
    """Show a song's sections and where its hook is."""
    from .music.structure import analyze_structure, best_window, melodic_hook
    from .pipeline import load_source

    printer = _Printer(args.quiet, args.json)
    reporter = ProgressReporter(printer.progress)
    source = load_source(
        _resolve_input(args, printer),
        _options_from_args(args),
        progress=reporter,
        use_stems=not args.no_stems,
    )
    structure = analyze_structure(source.events, bpm=source.bpm, duration=source.duration)
    window = best_window(
        structure, window_seconds=args.window, total_seconds=source.duration
    )
    hook_notes = melodic_hook(source.events, structure)

    if args.json:
        print(json.dumps({
            "structure": structure.to_dict(),
            "bestWindow": {"startSeconds": window[0], "endSeconds": window[1]},
            "hookNotes": [n.to_dict() for n in hook_notes],
        }, indent=2))
        return 0

    printer.line(_banner())
    printer.field("Input", Path(source.path).name)
    printer.field("Duration", _fmt_time(source.duration))
    printer.field("Tempo", f"{source.bpm:.0f} BPM")
    printer.line()
    printer.line("  start    end      role      repeats  recognisable")
    printer.line("  -------  -------  --------  -------  ------------")
    for segment in structure.segments:
        marker = "  <- hook" if segment.index == structure.hook_index else ""
        printer.line(
            "  {:>7}  {:>7}  {:<8}  {:>7}  {:>11.0%}{}".format(
                _fmt_time(segment.start_seconds),
                _fmt_time(segment.end_seconds),
                segment.role,
                "x" + str(segment.repetitions),
                segment.recognizability,
                marker,
            )
        )
    printer.line()
    printer.field(
        "Best " + str(int(args.window)) + "s window",
        _fmt_time(window[0]) + " - " + _fmt_time(window[1]),
    )
    if hook_notes:
        printer.field("Hook melody", " ".join(n.pitch_name for n in hook_notes[:16]))
    printer.line()
    printer.line("  Use --focus hook on convert to arrange just that window.")
    printer.line()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    """Run the browser interface, bound to localhost."""
    from .web import serve

    return serve(
        port=args.port,
        open_browser=not args.no_browser,
        rotate_token=args.new_token,
    )


def cmd_decode(args: argparse.Namespace) -> int:
    from .shawzin.instrument import load_instrument
    from .shawzin.songcode import decode, describe
    from .shawzin.tab import render_grid, render_tab

    instrument = load_instrument(args.shawzin)
    code = (args.code or "").strip()
    if not code:
        raise ShawzifyError(
            "No song code was given.",
            hint="Pass a code, or the path of a file containing one.",
        )
    if Path(code).exists():
        code = Path(code).read_text(encoding="utf-8").strip().splitlines()[-1].strip()
    info = describe(code, instrument)
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    printer = _Printer(args.quiet)
    printer.line(_banner())
    printer.field("Scale", info["scaleName"] + " (code " + info["scaleCode"] + ")")
    printer.field("Events", info["eventCount"])
    printer.field("Notes", info["noteCount"])
    printer.field("Chord events", info["chordEvents"])
    printer.field("Duration", _fmt_time(info["durationSeconds"]))
    printer.field("Within note limit", "yes" if info["withinNoteLimit"] else "no")
    printer.field("Chat-linkable", "yes" if info["withinChatLinkLimit"] else "no")
    printer.line()
    song = decode(code, instrument)
    printer.line(render_tab(song, instrument, max_rows=args.rows))
    printer.line()
    printer.line(render_grid(song, instrument))
    printer.line()
    return 0


def cmd_encode(args: argparse.Namespace) -> int:
    from .arrangement.arranger import arrange_for_shawzin
    from .project import load_project
    from .shawzin.instrument import load_instrument

    project = load_project(args.project)
    if project.song_code and not args.rearrange:
        print(project.song_code)
        return 0
    options = project.arrangement_options()
    instrument = load_instrument(options.shawzin_variant)
    arrangement = arrange_for_shawzin(
        project.events(), instrument, options, bpm=project.bpm, key=project.key_estimate()
    )
    print(arrangement.to_code())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .live.mic import microphone_available
    from .live.player import find_warframe_window
    from .pipeline import environment_report

    report = environment_report()
    mic_ok, mic_msg = microphone_available()
    window = find_warframe_window()
    report["microphone"] = {"available": mic_ok, "detail": mic_msg}
    report["warframe"] = window.to_dict()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    printer = _Printer(args.quiet)
    printer.line(_banner())
    ff = report["ffmpeg"]
    printer.field("FFmpeg", ("Installed (" + str(ff["source"]) + ")") if ff["available"] else "Not found")
    printer.field("Python Engine", "Ready " + str(report["python"]))
    gpu = report["gpu"]
    if gpu.get("cuda"):
        printer.field("CUDA", "Available - " + str(gpu.get("device")))
    else:
        printer.field("CUDA", "Not available (CPU mode)")
    printer.field("librosa", "Ready" if report["librosa"] else "Not installed")
    for t in report["transcribers"]:
        printer.field("Transcriber: " + t["name"], "Ready" if t["available"] else "Not installed")
    for s in report["separators"]:
        printer.field("Stems: " + s["name"], "Ready" if s["available"] else "Not installed")
    printer.field("Microphone", mic_msg if mic_ok else "Unavailable - " + mic_msg)
    printer.field("Warframe", "Running" if window.found else "Not running")
    printer.field("Cache size", "{:.1f} MB".format(report["cacheBytes"] / 1e6))
    printer.line()
    return 0


def cmd_scales(args: argparse.Namespace) -> int:
    from .music.pitch import note_name, pitch_class_name
    from .shawzin.instrument import load_instrument

    instrument = load_instrument(args.shawzin)
    if args.json:
        print(json.dumps(instrument.to_dict(), indent=2))
        return 0
    printer = _Printer(args.quiet)
    printer.line(_banner())
    printer.field("Shawzin", instrument.variant.name)
    printer.field("Polyphony", instrument.variant.polyphony)
    printer.field("Chord type", instrument.variant.chord_type)
    printer.line()
    printer.line("  code  scale                 range          pitch classes")
    printer.line("  ----  --------------------  -------------  ------------------------")
    for scale in instrument.scales:
        pcs = " ".join(pitch_class_name(p) for p in sorted(scale.pitch_classes))
        printer.line("  {:<4}  {:<20}  {:<13}  {}".format(
            scale.code, scale.name,
            note_name(scale.lowest_midi) + "-" + note_name(scale.highest_midi), pcs))
    printer.line()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Generate the bundled demo melody and convert it."""
    from .demo import write_demo_files

    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd()
    written = write_demo_files(out_dir)
    printer = _Printer(args.quiet)
    printer.line(_banner())
    printer.line("Demo material written:")
    for p in written:
        printer.line("  " + str(p))
    printer.line()
    return 0


# -- argument parsing ----------------------------------------------------


def _add_arrangement_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mode", default="balanced",
                   choices=[m.value for m in ArrangementMode],
                   help="arrangement mode (default: balanced)")
    p.add_argument("--scale", default="auto",
                   help="shawzin scale id or 'auto' (pmin pmaj chrom hex maj min hira phry yo)")
    p.add_argument("--transpose", default="auto", help="semitones or 'auto'")
    p.add_argument("--quantize", default=None,
                   help="off, auto, or a grid: 1/4 1/8 1/8t 1/16 1/16t 1/32")
    p.add_argument("--quantize-strength", type=float, default=0.85, help="0..1")
    p.add_argument("--complexity", type=float, default=0.55, help="0..1")
    p.add_argument("--max-density", default="auto", help="notes per second, or 'auto'")
    p.add_argument("--no-preserve-melody", action="store_true")
    p.add_argument("--arpeggiate", dest="arpeggiate", action="store_true", default=None)
    p.add_argument("--no-arpeggiate", dest="arpeggiate", action="store_false")
    p.add_argument("--shawzin", default="dax", help="shawzin variant id")
    p.add_argument("--stem", default="auto",
                   choices=[s.value for s in StemSource], help="which stem to transcribe")
    p.add_argument("--no-stems", action="store_true", help="skip stem separation")
    p.add_argument("--transcriber", default="auto",
                   choices=["auto", "basic_pitch", "cqt", "pyin"])
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--max-seconds", type=float, default=None,
                   help="only process the first N seconds")
    p.add_argument("--focus", default="auto", choices=["auto", "full", "hook"],
                   help="arrange the whole song, or just its most recognisable part")
    p.add_argument("--no-structure", action="store_true",
                   help="do not weight notes by how recognisable their section is")
    p.add_argument("--candidate", type=int, default=0,
                   help="when fetching a link, pick the Nth search result")


def build_parser() -> argparse.ArgumentParser:
    # Shared flags, accepted either before or after the subcommand -- a user
    # typing "shawzify convert x --quiet" should not get an argparse error.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-q", "--quiet", action="store_true")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    parser = argparse.ArgumentParser(
        prog="shawzify",
        description="Turn any song into a Warframe Shawzin performance.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version="SHAWZIFY " + APP_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", parents=[common],
                       help="analyse a file or link without arranging it")
    a.add_argument("input", help="a file, or a YouTube or Spotify link")
    a.add_argument("--events", action="store_true", help="include note events in --json")
    _add_arrangement_args(a)
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("convert", parents=[common],
                       help="convert audio, MIDI or a link into a Shawzin song code")
    c.add_argument("input", help="a file, or a YouTube or Spotify link")
    c.add_argument("-o", "--output", help="write the song code here")
    c.add_argument("--out-dir", help="directory for generated files")
    c.add_argument("--no-write", action="store_true", help="print only, write nothing")
    c.add_argument("--export-midi", action="store_true")
    c.add_argument("--export-preview", action="store_true", help="render a preview WAV")
    c.add_argument("--export-analysis", action="store_true")
    c.add_argument("--save-project", help="write a .shawzify project file")
    c.add_argument("--tab", type=int, nargs="?", const=40, default=0,
                   help="print the first N events as tab")
    c.add_argument("--dry-run-live", action="store_true",
                   help="simulate live playback and report timing accuracy")
    c.add_argument("--shawzin-advice", action="store_true",
                   help="also recommend which Shawzin to play it on")
    _add_arrangement_args(c)
    c.set_defaults(func=cmd_convert)

    f = sub.add_parser("fetch", parents=[common],
                       help="download a YouTube or Spotify link to local audio")
    f.add_argument("target", help="a YouTube or Spotify link")
    f.add_argument("-o", "--output", help="copy the audio here")
    f.add_argument("--candidate", type=int, default=0,
                   help="pick the Nth search result instead of the best one")
    f.set_defaults(func=cmd_fetch)

    sh = sub.add_parser("shawzins", parents=[common],
                        help="recommend which Shawzin to play a track on")
    sh.add_argument("input", help="a file, or a YouTube or Spotify link")
    sh.add_argument("--limit", type=int, default=5)
    _add_arrangement_args(sh)
    sh.set_defaults(func=cmd_shawzins)

    st = sub.add_parser("structure", parents=[common],
                        help="show a song's sections and where its hook is")
    st.add_argument("input", help="a file, or a YouTube or Spotify link")
    st.add_argument("--window", type=float, default=240.0,
                    help="length of the best-window search, in seconds")
    _add_arrangement_args(st)
    st.set_defaults(func=cmd_structure)

    w = sub.add_parser("web", parents=[common],
                       help="run the browser interface on localhost")
    w.add_argument("--port", type=int, default=8733)
    w.add_argument("--no-browser", action="store_true")
    w.add_argument(
        "--new-token",
        action="store_true",
        help="replace the saved access token, invalidating any open page",
    )
    w.set_defaults(func=cmd_web)

    d = sub.add_parser("decode", parents=[common], help="decode a Shawzin song code")
    d.add_argument("code", help="a song code, or a file containing one")
    d.add_argument("--shawzin", default="dax")
    d.add_argument("--rows", type=int, default=40)
    d.set_defaults(func=cmd_decode)

    e = sub.add_parser("encode", parents=[common], help="print the song code for a project file")
    e.add_argument("project")
    e.add_argument("--rearrange", action="store_true", help="re-run the arranger")
    e.set_defaults(func=cmd_encode)

    doc = sub.add_parser("doctor", parents=[common], help="check the local environment")
    doc.set_defaults(func=cmd_doctor)

    s = sub.add_parser("scales", parents=[common], help="list the Shawzin scales and their notes")
    s.add_argument("--shawzin", default="dax")
    s.set_defaults(func=cmd_scales)

    dm = sub.add_parser("demo", parents=[common], help="write the bundled demo melody and convert it")
    dm.add_argument("--out-dir")
    dm.set_defaults(func=cmd_demo)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Filenames and song titles are not ASCII, and a Windows console defaults
    # to a legacy code page that cannot encode them.
    use_utf8()

    parser = build_parser()
    args = parser.parse_args(argv)
    # ``parents`` gives each subparser its own defaults for the shared flags,
    # which would otherwise clear one the user typed before the subcommand.
    # These flags take no value, so scanning the raw tokens is unambiguous.
    tokens = list(argv if argv is not None else sys.argv[1:])
    args.quiet = bool(args.quiet or "-q" in tokens or "--quiet" in tokens)
    args.json = bool(args.json or "--json" in tokens)
    try:
        return int(args.func(args) or 0)
    except ShawzifyError as exc:
        print("\nSHAWZIFY: " + exc.message, file=sys.stderr)
        if exc.hint:
            print("  " + exc.hint, file=sys.stderr)
        if exc.technical and not args.quiet:
            print("\nTechnical details:\n" + exc.technical, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

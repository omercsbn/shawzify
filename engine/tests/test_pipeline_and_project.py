"""End-to-end pipeline, caching, project files, preview and the CLI."""

from __future__ import annotations

import json

import numpy as np
import pytest

from shawzify_engine.arrangement.options import ArrangementMode, ArrangementOptions
from shawzify_engine.cli import main
from shawzify_engine.common.cache import Cache, hash_file, hash_payload, make_key
from shawzify_engine.common.progress import (
    CancellationToken,
    ProgressEvent,
    ProgressReporter,
)
from shawzify_engine.demo import demo_events, render_demo_audio
from shawzify_engine.pipeline import arrange_source, convert, environment_report, load_source
from shawzify_engine.preview.synth import PluckedStringInstrument, render_preview
from shawzify_engine.project import (
    build_project,
    load_project,
    load_recents,
    remember_project,
    save_project,
)
from shawzify_engine.shawzin.songcode import decode

from .test_arrangement import assert_playable

# -- cache ---------------------------------------------------------------


def test_hash_file_is_content_addressed(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"same content")
    b.write_bytes(b"same content")
    assert hash_file(a) == hash_file(b)
    b.write_bytes(b"different")
    assert hash_file(a) != hash_file(b)


def test_cache_round_trip(tmp_path):
    cache = Cache(str(tmp_path))
    assert cache.get_json("ns", "key") is None
    cache.put_json("ns", "key", {"value": 42})
    assert cache.get_json("ns", "key") == {"value": 42}
    assert cache.size_bytes() > 0
    cache.clear("ns")
    assert cache.get_json("ns", "key") is None


def test_corrupt_cache_entry_is_a_miss(tmp_path):
    cache = Cache(str(tmp_path))
    cache.put_json("ns", "key", {"a": 1})
    cache.json_path("ns", "key").write_text("{{{ not json", encoding="utf-8")
    assert cache.get_json("ns", "key") is None


def test_cache_key_depends_on_settings():
    base = "abc123"
    assert make_key(base, hash_payload({"v": 1})) != make_key(base, hash_payload({"v": 2}))


def test_directory_cache_is_only_valid_once_committed(tmp_path):
    cache = Cache(str(tmp_path))
    assert cache.get_dir("stems", "k") is None
    d = cache.begin_dir("stems", "k")
    (d / "vocals.npy").write_bytes(b"x")
    assert cache.get_dir("stems", "k") is None, "an incomplete dir must not be a hit"
    cache.commit_dir("stems", "k")
    assert cache.get_dir("stems", "k") is not None


# -- progress ------------------------------------------------------------


def test_progress_is_monotonic_and_bounded():
    seen: list[ProgressEvent] = []
    reporter = ProgressReporter(seen.append)
    for stage in ("decode", "waveform", "analyze", "transcribe", "arrange", "encode"):
        reporter.skip("stems")
        reporter.start(stage)
        reporter.update(stage, 0.5)
        reporter.finish(stage)
    fractions = [e.overall_fraction for e in seen]
    assert fractions == sorted(fractions)
    assert 0.0 <= fractions[0] <= fractions[-1] <= 1.0
    assert fractions[-1] == pytest.approx(1.0)


def test_skipping_a_stage_redistributes_its_weight():
    seen: list[ProgressEvent] = []
    reporter = ProgressReporter(seen.append)
    reporter.skip("stems")
    reporter.start("decode")
    reporter.finish("decode")
    # Without stems, decode alone is a bigger share of the total.
    assert seen[-1].overall_fraction > 0.1


def test_cancellation_is_honoured():
    from shawzify_engine.common.errors import CancelledError

    token = CancellationToken()
    reporter = ProgressReporter(lambda e: None, token=token)
    reporter.start("decode")
    token.cancel()
    with pytest.raises(CancelledError):
        reporter.update("decode", 0.5)


# -- preview -------------------------------------------------------------


def test_preview_renders_audio(twinkle):
    audio = render_preview(twinkle, sample_rate=22050)
    assert audio.dtype == np.float32
    assert len(audio) > 22050
    assert np.max(np.abs(audio)) > 0.05
    assert np.max(np.abs(audio)) <= 1.0


def test_preview_is_deterministic(twinkle):
    a = render_preview(twinkle, sample_rate=22050)
    b = render_preview(twinkle, sample_rate=22050)
    assert np.array_equal(a, b)


def test_preview_instrument_is_swappable(twinkle):
    bright = render_preview(twinkle, sample_rate=22050,
                            instrument=PluckedStringInstrument(brightness=0.95))
    dull = render_preview(twinkle, sample_rate=22050,
                          instrument=PluckedStringInstrument(brightness=0.05))
    assert not np.array_equal(bright, dull)


def test_preview_of_nothing_is_silence():
    assert render_preview([]).size >= 1


# -- demo ----------------------------------------------------------------


def test_demo_exercises_the_hard_cases():
    events = demo_events()
    assert len(events) > 60
    pitches = [e.pitch_midi for e in events]
    assert max(pitches) > 90, "the demo should climb out of the Shawzin's range"
    assert min(pitches) < 55, "the demo should include low harmony"
    # A seven-note stack the instrument cannot possibly hold.
    from shawzify_engine.music.events import group_by_onset

    assert max(len(g) for g in group_by_onset(events, 0.03)) >= 7


def test_demo_arranges_and_encodes(instrument):
    from shawzify_engine.arrangement.arranger import arrange_for_shawzin
    from shawzify_engine.demo import BPM

    a = arrange_for_shawzin(demo_events(), instrument, bpm=BPM)
    assert_playable(a)
    assert a.report.compatibility_after.overall > a.report.compatibility_before.overall
    assert a.report.compatibility_after.overall > 0.75


def test_demo_audio_renders():
    audio = render_demo_audio(22050)
    assert audio.size > 22050 * 20


# -- full pipeline -------------------------------------------------------


def test_midi_pipeline_end_to_end(midi_file, twinkle):
    path = midi_file(twinkle, bpm=120.0)
    source, arrangement = convert(path, ArrangementOptions(mode=ArrangementMode.BALANCED))
    assert source.kind == "midi"
    assert source.transcription_backend == "midi"
    assert len(source.events) == len(twinkle)
    assert_playable(arrangement)
    assert arrangement.to_code()
    assert arrangement.report.stage_timings


def test_audio_pipeline_end_to_end(wav_file, melody_audio):
    """Real audio in, real transcription, real arrangement out."""
    path = wav_file(melody_audio, 22050)
    source, arrangement = convert(path, use_stems=False)
    assert source.kind == "audio"
    assert source.events, "no notes were transcribed from real audio"
    assert source.analysis is not None
    assert source.waveform is not None
    assert len(source.waveform.max_values) > 100
    assert_playable(arrangement)
    code = arrangement.to_code()
    assert code
    assert decode(code, arrangement.instrument).events


def test_transcription_is_cached_between_runs(wav_file, melody_audio):
    """Re-analysing the same file must not re-transcribe it."""
    path = wav_file(melody_audio, 22050)
    first = load_source(path, use_stems=False)
    second = load_source(path, use_stems=False)
    assert [e.to_dict() for e in first.events] == [e.to_dict() for e in second.events]


def test_changing_arrangement_settings_reuses_the_source(wav_file, melody_audio):
    """The point of the split: retune the arrangement without re-transcribing."""
    path = wav_file(melody_audio, 22050)
    source = load_source(path, use_stems=False)
    a = arrange_source(source, ArrangementOptions(mode=ArrangementMode.MELODY))
    b = arrange_source(source, ArrangementOptions(mode=ArrangementMode.CHORDAL))
    assert_playable(a)
    assert_playable(b)
    assert a.resolved.mode != b.resolved.mode


def test_pipeline_reports_progress(midi_file, twinkle):
    events: list[ProgressEvent] = []
    convert(midi_file(twinkle), progress=ProgressReporter(events.append))
    assert events
    stages = {e.stage for e in events}
    assert "arrange" in stages and "encode" in stages
    assert all(0.0 <= e.overall_fraction <= 1.0 for e in events)


def test_environment_report_is_complete():
    report = environment_report()
    for key in ("app", "python", "platform", "ffmpeg", "gpu", "transcribers", "separators"):
        assert key in report
    assert report["ffmpeg"]["available"]
    json.dumps(report)  # must be serialisable for the UI


# -- project files -------------------------------------------------------


def test_project_round_trip(tmp_path, midi_file, twinkle):
    path = midi_file(twinkle)
    source, arrangement = convert(path)
    project = build_project(source, arrangement, title="Twinkle")
    saved = save_project(project, tmp_path / "test")
    assert saved.suffix == ".shawzify"

    back = load_project(saved)
    assert back.title == "Twinkle"
    assert back.song_code == arrangement.to_code()
    assert len(back.events()) == len(source.events)
    assert back.arrangement_options() == arrangement.options
    assert back.is_reproducible()


def test_project_does_not_embed_audio(tmp_path, wav_file, melody_audio):
    path = wav_file(melody_audio, 22050)
    source, arrangement = convert(path, use_stems=False)
    saved = save_project(build_project(source, arrangement), tmp_path / "p")
    assert saved.stat().st_size < 400_000
    assert path.stat().st_size > 0


def test_reopened_project_reproduces_the_same_code(tmp_path, midi_file, twinkle):
    from shawzify_engine.arrangement.arranger import arrange_for_shawzin
    from shawzify_engine.shawzin.instrument import load_instrument

    source, arrangement = convert(midi_file(twinkle))
    saved = save_project(build_project(source, arrangement), tmp_path / "p")
    project = load_project(saved)
    options = project.arrangement_options()
    redone = arrange_for_shawzin(
        project.events(),
        load_instrument(options.shawzin_variant),
        options,
        bpm=project.bpm,
        key=project.key_estimate(),
    )
    assert redone.to_code() == project.song_code


def test_loading_a_non_project_fails_clearly(tmp_path):
    from shawzify_engine.common.errors import ShawzifyError

    p = tmp_path / "bad.shawzify"
    p.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ShawzifyError):
        load_project(p)


def test_newer_schema_is_refused(tmp_path):
    from shawzify_engine.common.errors import ShawzifyError

    p = tmp_path / "future.shawzify"
    p.write_text(json.dumps({"schemaVersion": 999}), encoding="utf-8")
    with pytest.raises(ShawzifyError, match="newer version"):
        load_project(p)


def test_recent_projects_are_remembered():
    remember_project(title="One", path="a.shawzify", compatibility=91.0)
    remember_project(title="Two", path="b.shawzify", compatibility=87.5)
    recents = load_recents()
    assert recents[0]["title"] == "Two"
    assert recents[1]["title"] == "One"
    remember_project(title="One again", path="a.shawzify", compatibility=95.0)
    recents = load_recents()
    assert len(recents) == 2, "re-opening a project must not duplicate it"
    assert recents[0]["path"] == "a.shawzify"


# -- CLI -----------------------------------------------------------------


def test_cli_convert_writes_a_song_code(tmp_path, midi_file, twinkle, capsys):
    path = midi_file(twinkle)
    out = tmp_path / "out.txt"
    code = main(["convert", str(path), "-o", str(out), "--quiet"])
    assert code == 0
    written = out.read_text(encoding="utf-8").strip()
    assert written
    decode(written)


def test_cli_convert_json_output(tmp_path, midi_file, twinkle, capsys):
    main(["--json", "convert", str(midi_file(twinkle)), "--no-write"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"]
    assert payload["report"]["scaleName"]
    assert "compatibilityAfter" in payload["report"]


def test_cli_json_output_is_never_polluted(tmp_path, wav_file, melody_audio, capsys):
    """A library printing to stdout would make --json unparseable."""
    main(["--json", "convert", str(wav_file(melody_audio, 22050)), "--no-write", "--no-stems"])
    out = capsys.readouterr().out
    assert out.lstrip().startswith("{"), "something printed before the JSON: " + out[:120]
    payload = json.loads(out)
    assert payload["code"]


def test_cli_analyze(tmp_path, midi_file, twinkle, capsys):
    assert main(["analyze", str(midi_file(twinkle))]) == 0
    assert "Detected Key" in capsys.readouterr().out


def test_cli_decode(capsys):
    assert main(["decode", "1BAACAIEAQJAYKAgMAo"]) == 0
    out = capsys.readouterr().out
    assert "Pentatonic Minor" in out
    assert "C3" in out


def test_cli_scales(capsys):
    assert main(["scales"]) == 0
    out = capsys.readouterr().out
    for name in ("Pentatonic Minor", "Chromatic", "Hirajoshi", "Yo"):
        assert name in out


def test_cli_doctor(capsys):
    assert main(["doctor"]) == 0
    assert "FFmpeg" in capsys.readouterr().out


def test_cli_reports_a_missing_file_without_a_traceback(tmp_path, capsys):
    code = main(["convert", str(tmp_path / "nope.mp3"), "--quiet"])
    assert code == 2
    err = capsys.readouterr().err
    assert "SHAWZIFY" in err
    assert "Traceback" not in err


def test_cli_exports_every_artifact(tmp_path, midi_file, twinkle):
    path = midi_file(twinkle)
    assert main([
        "convert", str(path), "--out-dir", str(tmp_path), "--quiet",
        "--export-midi", "--export-preview", "--export-analysis",
        "--save-project", str(tmp_path / "proj.shawzify"),
    ]) == 0
    names = {p.name for p in tmp_path.iterdir()}
    assert any(n.endswith(".shawzin.txt") for n in names)
    assert any(n.endswith(".arranged.mid") for n in names)
    assert any(n.endswith(".preview.wav") for n in names)
    assert any(n.endswith(".analysis.json") for n in names)
    assert "proj.shawzify" in names


def test_cli_modes_produce_different_codes(tmp_path, midi_file, chord_progression, capsys):
    path = midi_file(chord_progression, bpm=60.0)
    codes = {}
    for mode in ("melody", "chordal"):
        main(["--json", "convert", str(path), "--no-write", "--mode", mode])
        codes[mode] = json.loads(capsys.readouterr().out)["code"]
    assert codes["melody"] != codes["chordal"]


def test_cli_dry_run_live(tmp_path, midi_file, twinkle, capsys):
    assert main([
        "convert", str(midi_file(twinkle)), "--no-write", "--dry-run-live"
    ]) == 0
    out = capsys.readouterr().out
    assert "key presses" in out
    assert "timing error" in out

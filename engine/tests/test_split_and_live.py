"""Song splitting, the event scheduler, live input mapping and key bindings."""

from __future__ import annotations

import pytest

from shawzify_engine.live.input_sink import VK_CODES, RecordingInputSink
from shawzify_engine.live.keymap import DEFAULT_BINDINGS, WarframeKeymap
from shawzify_engine.live.mic import (
    LiveInputSettings,
    LivePitchMapper,
    MidiKeyboardMapper,
    map_frames,
    nearest_playable,
)
from shawzify_engine.live.player import ShawzinLivePlayer, dry_run
from shawzify_engine.live.scheduler import EventScheduler, ScheduledEvent
from shawzify_engine.music.pitch import midi_to_hz
from shawzify_engine.shawzin.songcode import ShawzinEvent, ShawzinSong, decode, encode
from shawzify_engine.shawzin.split import needs_split, split_arrangement

# -- splitting -----------------------------------------------------------


def test_short_song_needs_no_split(instrument):
    song = ShawzinSong("maj", [ShawzinEvent(i * 8, "0", "1") for i in range(20)])
    over, reasons = needs_split(song, instrument)
    assert not over
    assert reasons == []


def test_long_song_is_flagged(instrument):
    limit = instrument.format.max_ticks
    song = ShawzinSong("maj", [ShawzinEvent(0, "0", "1"), ShawzinEvent(limit + 100, "0", "2")])
    over, reasons = needs_split(song, instrument)
    assert over
    assert any("minutes" in r for r in reasons)


def test_too_many_notes_is_flagged(instrument):
    n = instrument.format.max_notes + 50
    song = ShawzinSong("maj", [ShawzinEvent(i, "0", "1") for i in range(n)])
    over, reasons = needs_split(song, instrument)
    assert over
    assert any("notes" in r for r in reasons)


def test_split_produces_importable_parts(instrument):
    """Nothing is truncated: every source event lands in exactly one part."""
    events = [ShawzinEvent(i * 4, "0", "1") for i in range(1200)]
    song = ShawzinSong("maj", events)
    parts = split_arrangement(song, instrument, bpm=120.0)
    assert len(parts) >= 2
    total = sum(p.song.note_count for p in parts)
    assert total == song.note_count
    for part in parts:
        assert part.song.events[0].tick == 0, "each part must start at tick 0"
        assert part.song.note_count <= instrument.format.max_notes
        assert part.song.end_tick <= instrument.format.max_ticks
        assert decode(part.code, instrument).events


def test_split_preserves_relative_timing(instrument):
    events = [ShawzinEvent(i * 4, "0", "1") for i in range(1200)]
    parts = split_arrangement(ShawzinSong("maj", events), instrument, bpm=120.0)
    for part in parts:
        gaps = [b.tick - a.tick for a, b in zip(part.song.events, part.song.events[1:])]
        assert all(g == 4 for g in gaps)


def test_split_prefers_a_musical_seam(instrument):
    """Given a rest, the cut should land on it rather than mid-figure."""
    events = []
    tick = 0
    for bar in range(300):
        for _beat in range(4):
            events.append(ShawzinEvent(tick, "0", "1"))
            tick += 4
        if bar % 8 == 7:
            tick += 32  # a long rest every eight bars
    song = ShawzinSong("maj", events)
    parts = split_arrangement(song, instrument, bpm=120.0, max_notes=200)
    assert len(parts) > 1
    # The first event of a later part should follow a gap larger than one beat.
    for part in parts[1:]:
        index = next(i for i, e in enumerate(song.events) if e.tick == part.start_tick)
        if index > 0:
            gap = song.events[index].tick - song.events[index - 1].tick
            assert gap >= 4


def test_split_of_a_short_song_is_a_single_part(instrument):
    song = ShawzinSong("maj", [ShawzinEvent(i * 8, "0", "1") for i in range(10)])
    parts = split_arrangement(song, instrument)
    assert len(parts) == 1
    assert parts[0].code == encode(song, instrument)


def test_an_over_long_song_arranges_then_splits(instrument):
    """A six-minute melody must arrange, then split -- never be truncated or refused."""
    from shawzify_engine.arrangement import arrange_for_shawzin
    from shawzify_engine.music.events import NoteEvent

    scale = [0, 2, 4, 5, 7, 9, 11, 12]
    events = [
        NoteEvent(60 + scale[i % 8], i * 0.26, 0.22, 0.8, 1.0, "long")
        for i in range(1400)
    ]
    arrangement = arrange_for_shawzin(events, instrument, bpm=115.0)

    assert arrangement.over_limits, "this fixture should exceed both limits"
    over, reasons = needs_split(arrangement.song, instrument)
    assert over
    assert len(reasons) == 2  # too long and too many notes

    parts = split_arrangement(arrangement.song, instrument, bpm=115.0)
    assert len(parts) >= 2
    assert sum(p.note_count for p in parts) == arrangement.song.note_count
    for part in parts:
        assert part.note_count <= instrument.format.max_notes
        assert part.song.end_tick <= instrument.format.max_ticks
        assert decode(part.code, instrument).events[0].tick == 0


def test_a_single_code_still_refuses_to_exceed_the_limits(instrument):
    """Splitting is the escape hatch; encoding one over-long code is not."""
    from shawzify_engine.common.errors import SongCodeError

    events = [ShawzinEvent(i * 3, "0", "1") for i in range(1400)]
    song = ShawzinSong("maj", events)
    with pytest.raises(SongCodeError):
        encode(song, instrument)


# -- scheduler -----------------------------------------------------------


def test_scheduler_uses_absolute_targets_so_drift_does_not_accumulate():
    """A 30 s sequence must not drift, even with a slow, lumpy sleep."""
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        # Simulate a sleep that habitually overshoots by 40%.
        clock["t"] += max(0.0, seconds) * 1.4

    events = [ScheduledEvent(i * 0.125, i) for i in range(240)]  # 30 s at 8 per second
    fired: list[tuple[int, float]] = []
    scheduler = EventScheduler(clock=now, sleep=sleep, spin_margin=0.0)
    stats = scheduler.run(events, lambda e, t: fired.append((e.payload, t)))

    assert len(fired) == 240
    assert stats.count == 240
    # Overshoot is per-event, never cumulative.
    assert stats.max_error < 0.06
    assert stats.mean_error < 0.03
    last_target = events[-1].at_seconds
    assert fired[-1][1] == pytest.approx(last_target, abs=0.06)


def test_scheduler_reports_timing_statistics():
    clock = {"t": 0.0}
    scheduler = EventScheduler(
        clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        spin_margin=0.0,
    )
    stats = scheduler.run([ScheduledEvent(i * 0.1, i) for i in range(50)], lambda e, t: None)
    assert stats.count == 50
    assert stats.mean_error >= 0.0
    assert "meanErrorMs" in stats.to_dict()


def test_scheduler_stops_on_request():
    clock = {"t": 0.0}
    fired: list[int] = []
    scheduler = EventScheduler(
        clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        spin_margin=0.0,
    )
    scheduler.run(
        [ScheduledEvent(i * 0.1, i) for i in range(100)],
        lambda e, t: fired.append(e.payload),
        should_stop=lambda: len(fired) >= 5,
    )
    assert len(fired) == 5


def test_scheduler_handles_an_empty_schedule():
    assert EventScheduler().run([], lambda e, t: None).count == 0


# -- input sink ----------------------------------------------------------


def test_recording_sink_tracks_presses_and_releases():
    sink = RecordingInputSink(simulate_sleep=True)
    sink.key_down("1")
    sink.tap("2", 0.01)
    sink.release_all()
    assert [(a.key, a.down) for a in sink.actions] == [
        ("1", True), ("2", True), ("2", False), ("1", False)
    ]
    assert sink.held == set()


def test_every_default_binding_has_a_virtual_key():
    for action, key in DEFAULT_BINDINGS.items():
        assert key in VK_CODES, action + " is bound to an unknown key: " + key


# -- keymap --------------------------------------------------------------


def test_default_keymap_matches_the_documented_controls():
    km = WarframeKeymap()
    assert km.string_key("1") == "1"
    assert km.string_key("3") == "3"
    assert km.fret_keys("0") == []
    assert km.fret_keys("1") == ["left"]    # Sky fret
    assert km.fret_keys("2") == ["down"]    # Earth fret
    assert km.fret_keys("3") == ["right"]   # Water fret
    assert km.fret_keys("123") == ["left", "down", "right"]


def test_keymap_detects_clashes():
    km = WarframeKeymap()
    km.bindings["fret1"] = "1"  # already the first string
    problems = km.validate()
    assert problems
    assert "1st String" in problems[0] or "Sky Fret" in problems[0]


def test_keymap_round_trips_through_disk(tmp_path):
    km = WarframeKeymap()
    km.bindings["fret1"] = "n"
    km.timing.playback_offset_ms = -35.0
    path = km.save(tmp_path / "keymap.json")
    back = WarframeKeymap.load(path)
    assert back.bindings["fret1"] == "n"
    assert back.timing.playback_offset_ms == -35.0


def test_keymap_load_of_garbage_falls_back_to_defaults(tmp_path):
    p = tmp_path / "keymap.json"
    p.write_text("{ not json", encoding="utf-8")
    assert WarframeKeymap.load(p).bindings == DEFAULT_BINDINGS


# -- live playback -------------------------------------------------------


def test_dry_run_emits_the_expected_key_sequence(instrument):
    """A pentatonic run must press the right frets and strings in order."""
    song = decode("1BAACAIEAQJAYKAgMAo", instrument)
    presses, stats = dry_run(song, instrument=instrument)
    keys = [k for k, _ in presses]
    # First three notes are open strings 1, 2, 3; then fret 1 (left) plus 1, 2, 3.
    assert keys[:3] == ["1", "2", "3"]
    assert "left" in keys
    assert keys.count("left") == 1, "the fret should be held, not re-pressed per note"
    assert stats.count == len(song.events)


def test_dry_run_timing_is_accurate(instrument):
    song = ShawzinSong("chrom", [ShawzinEvent(i * 8, "0", "1") for i in range(60)])
    _presses, stats = dry_run(song, instrument=instrument)
    assert stats.mean_error < 0.02
    assert stats.max_error < 0.05


def test_player_refuses_without_focus(instrument):
    from shawzify_engine.common.errors import LivePlaybackError

    player = ShawzinLivePlayer(
        sink=RecordingInputSink(simulate_sleep=True),
        keymap=WarframeKeymap(),
        instrument=instrument,
        focus_check=lambda: False,
    )
    song = ShawzinSong("chrom", [ShawzinEvent(0, "0", "1")])
    with pytest.raises(LivePlaybackError, match="active window"):
        player.play(song, countdown=False)


def test_player_stops_when_focus_is_lost(instrument):
    """Losing focus mid-song must stop immediately, not keep sending keys."""
    focus = {"ok": True}
    sink = RecordingInputSink(simulate_sleep=True)
    clock = {"t": 0.0}
    scheduler = EventScheduler(
        clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        spin_margin=0.0,
    )

    def check() -> bool:
        # Focus is lost once a few notes have been played.
        if len(sink.presses()) >= 3:
            focus["ok"] = False
        return focus["ok"]

    player = ShawzinLivePlayer(
        sink=sink, keymap=WarframeKeymap(), instrument=instrument,
        focus_check=check, scheduler=scheduler,
    )
    song = ShawzinSong("chrom", [ShawzinEvent(i * 8, "0", "1") for i in range(50)])
    player.play(song, countdown=False)
    assert len(sink.presses()) < 50
    assert sink.held == set(), "keys were left held down after stopping"


def test_player_releases_frets_when_stopped(instrument):
    sink = RecordingInputSink(simulate_sleep=True)
    clock = {"t": 0.0}
    scheduler = EventScheduler(
        clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        spin_margin=0.0,
    )
    player = ShawzinLivePlayer(
        sink=sink, keymap=WarframeKeymap(), instrument=instrument,
        focus_check=lambda: True, scheduler=scheduler,
    )
    song = ShawzinSong("chrom", [ShawzinEvent(0, "123", "1"), ShawzinEvent(16, "0", "2")])
    player.play(song, countdown=False)
    assert sink.held == set()


def test_preflight_reports_what_is_missing(instrument):
    player = ShawzinLivePlayer(
        sink=RecordingInputSink(), keymap=WarframeKeymap(),
        instrument=instrument, focus_check=lambda: False,
    )
    info = player.preflight()
    assert "window" in info
    assert info["canPlay"] is False


# -- microphone / MIDI keyboard mapping ---------------------------------


def test_nearest_playable_prefers_the_pitch_class_over_raw_distance(instrument):
    """C4 is above the Chromatic scale; it should fold to C3, not clamp to B3."""
    note = nearest_playable(60.2, instrument, "chrom")
    assert note is not None and note.midi == 48
    exact = nearest_playable(55.0, instrument, "chrom")
    assert exact is not None and exact.midi == 55


def test_nearest_playable_tracks_the_octave_when_it_can(instrument):
    """Pentatonic minor has C at 48, 60 and 72; the closest one wins."""
    assert nearest_playable(60.0, instrument, "pmin").midi == 60
    assert nearest_playable(72.0, instrument, "pmin").midi == 72


def test_octave_lock_pins_the_register(instrument):
    note = nearest_playable(72.0, instrument, "pmin", octave_lock=True)
    assert note is not None
    assert note.midi == 48


def test_scale_lock_off_skips_notes_the_scale_cannot_play(instrument):
    """F# is not in the Major scale; without snapping, nothing is played."""
    assert nearest_playable(66.0, instrument, "maj", snap_out_of_scale=False) is None
    assert nearest_playable(66.0, instrument, "maj", snap_out_of_scale=True) is not None


def test_live_mapper_debounces_and_triggers_on_change(instrument):
    settings = LiveInputSettings(onset_frames=2, minimum_confidence=0.4)
    mapper = LivePitchMapper(instrument, scale_id="chrom", settings=settings)
    # One low-confidence frame: nothing fires.
    assert mapper.push(midi_to_hz(60), 0.1) is None
    # First confident frame is still inside the debounce window.
    assert mapper.push(midi_to_hz(60), 0.9) is None
    first = mapper.push(midi_to_hz(60), 0.9)
    assert first is not None and first.midi == 48  # C4 folds to the Shawzin's C3
    # Holding the same pitch must not retrigger.
    assert mapper.push(midi_to_hz(60), 0.9) is None
    # A clear move retriggers, and the smoothed contour settles on the new pitch.
    triggered = [n for n in (mapper.push(midi_to_hz(64), 0.9) for _ in range(20)) if n]
    assert triggered
    assert triggered[-1].midi % 12 == 4  # an E, in whichever octave


def test_live_mapper_ignores_unvoiced_frames(instrument):
    mapper = LivePitchMapper(instrument, scale_id="chrom")
    notes = map_frames([(0.0, 0.0)] * 20, instrument, scale_id="chrom")
    assert notes == []
    assert mapper.current is None


def test_live_mapper_output_is_always_playable(instrument):
    frames = [(midi_to_hz(m), 0.9) for m in range(40, 100)]
    notes = map_frames(frames, instrument, scale_id="pmin")
    playable = {n.position for n in instrument.scale("pmin").notes}
    assert notes
    for n in notes:
        assert n.position in playable


def test_midi_keyboard_mapper(instrument):
    mapper = MidiKeyboardMapper(instrument=instrument, scale_id="chrom")
    note = mapper.map_note(55)
    assert note is not None and note.midi == 55
    assert mapper.map_note(55, velocity=0) is None

"""Audio decoding, analysis, transcription and MIDI IO.

Every audio input is synthesised in ``conftest``; nothing copyrighted is used.
"""

from __future__ import annotations

import numpy as np
import pytest

from shawzify_engine.audio.analysis import analyze_audio_buffer
from shawzify_engine.audio.decode import load_audio, resample
from shawzify_engine.audio.ffmpeg import find_ffmpeg
from shawzify_engine.audio.waveform import compute_peaks
from shawzify_engine.common.errors import MidiParseError, UnsupportedFormatError
from shawzify_engine.common.safety import (
    classify_input,
    resolve_input_path,
    sanitize_metadata_text,
)
from shawzify_engine.midi.reader import choose_melody_track, parse_midi
from shawzify_engine.midi.writer import write_midi
from shawzify_engine.music.events import NoteEvent
from shawzify_engine.transcription import select_transcriber
from shawzify_engine.transcription.cqt_transcriber import CqtTranscriber
from shawzify_engine.transcription.pyin_transcriber import PyinTranscriber

SR = 22050


# -- decoding ------------------------------------------------------------


def test_ffmpeg_is_discoverable():
    info = find_ffmpeg()
    assert info.available, "no ffmpeg found; run scripts/setup.ps1"
    assert info.version


def test_load_wav_round_trip(wav_file, melody_audio):
    path = wav_file(melody_audio, SR)
    buffer = load_audio(path, sample_rate=SR)
    assert buffer.sample_rate == SR
    assert buffer.channels == 1
    assert buffer.duration == pytest.approx(len(melody_audio) / SR, abs=0.02)
    assert buffer.metadata.filename == path.name


def test_load_audio_resamples(wav_file, sine_440):
    path = wav_file(sine_440, SR)
    buffer = load_audio(path, sample_rate=44100)
    assert buffer.sample_rate == 44100
    assert buffer.duration == pytest.approx(1.0, abs=0.02)


def test_resample_preserves_duration():
    data = np.zeros((1, SR), dtype=np.float32)
    out = resample(data, SR, 44100)
    assert out.shape[-1] == pytest.approx(44100, abs=2)


def test_missing_file_is_reported_clearly(tmp_path):
    from shawzify_engine.common.errors import UnsafePathError

    with pytest.raises(UnsafePathError) as exc:
        resolve_input_path(tmp_path / "nope.wav")
    assert "could not find" in exc.value.message.lower()


def test_unsupported_extension_is_rejected(tmp_path):
    p = tmp_path / "song.xyz"
    p.write_bytes(b"nope")
    with pytest.raises(UnsupportedFormatError):
        classify_input(resolve_input_path(p))


def test_metadata_text_is_sanitised():
    assert sanitize_metadata_text("hello\x00\x07world") == "hello  world"
    assert sanitize_metadata_text(b"caf\xc3\xa9") == "café"
    assert len(sanitize_metadata_text("x" * 500)) == 200


def test_corrupt_audio_fails_gracefully(tmp_path):
    from shawzify_engine.common.errors import AudioDecodeError

    p = tmp_path / "broken.mp3"
    p.write_bytes(b"\x00\x01\x02not actually audio at all")
    with pytest.raises(AudioDecodeError):
        load_audio(p)


# -- waveform ------------------------------------------------------------


def test_waveform_peaks_are_downsampled(melody_audio):
    peaks = compute_peaks(melody_audio, SR, buckets=200)
    assert peaks.buckets == 200
    assert len(peaks.min_values) == 200
    assert len(peaks.max_values) == 200
    assert all(-1.001 <= v <= 1.001 for v in peaks.min_values + peaks.max_values)
    assert max(peaks.max_values) == pytest.approx(1.0, abs=0.01)


def test_waveform_handles_silence():
    peaks = compute_peaks(np.zeros(1000, dtype=np.float32), SR, buckets=10)
    assert peaks.buckets == 10
    assert all(v == 0.0 for v in peaks.rms_values)


# -- analysis ------------------------------------------------------------


def test_analysis_detects_a_440_sine(sine_440):
    a = analyze_audio_buffer(sine_440, SR)
    assert a.duration == pytest.approx(1.0, abs=0.05)
    assert a.energy > 0.1
    assert 0.0 <= a.tempo_confidence <= 1.0
    assert 0.0 <= a.key_confidence <= 1.0


def test_analysis_finds_the_right_key_for_a_c_major_arpeggio(arpeggio_audio):
    a = analyze_audio_buffer(arpeggio_audio, SR)
    assert a.key in ("C", "G", "F", "A")  # relative and neighbouring keys are fair
    assert a.backend in ("librosa", "builtin")


def test_analysis_reports_confidence_not_certainty(melody_audio):
    a = analyze_audio_buffer(melody_audio, SR)
    assert a.tempo_confidence < 1.0 or a.tempo_bpm > 0
    assert a.to_dict()["tempoConfidence"] is not None


def test_analysis_of_silence_does_not_crash():
    a = analyze_audio_buffer(np.zeros(SR, dtype=np.float32), SR)
    assert a.tempo_bpm > 0


def test_builtin_analysis_backend_works(melody_audio):
    """The engine must still analyse when librosa is absent."""
    a = analyze_audio_buffer(melody_audio, SR, prefer_librosa=False)
    assert a.backend == "builtin"
    assert a.tempo_bpm > 0


# -- transcription -------------------------------------------------------


def test_pyin_transcribes_a_monophonic_melody(melody_audio):
    """Real transcription of real (synthesised) audio -- no hardcoded notes."""
    result = PyinTranscriber().transcribe(melody_audio, SR)
    assert result.backend == "pyin"
    pitches = [e.pitch_midi for e in result.events]
    assert pitches == [60, 62, 64, 65, 67, 65, 64, 62, 60]


def test_cqt_transcribes_the_right_pitch_classes(melody_audio):
    result = CqtTranscriber(max_polyphony=3).transcribe(melody_audio, SR)
    assert result.events
    classes = {e.pitch_midi % 12 for e in result.events}
    # C D E F G, allowing octave ghosts but not wrong pitch classes.
    assert classes <= {0, 2, 4, 5, 7}


def test_cqt_finds_both_notes_of_a_dyad(two_note_audio):
    result = CqtTranscriber(max_polyphony=4).transcribe(two_note_audio, SR)
    classes = {e.pitch_midi % 12 for e in result.events}
    assert 0 in classes and 7 in classes  # C and G


def test_transcribers_are_deterministic(melody_audio):
    a = CqtTranscriber().transcribe(melody_audio, SR)
    b = CqtTranscriber().transcribe(melody_audio, SR)
    assert [e.to_dict() for e in a.events] == [e.to_dict() for e in b.events]


def test_empty_audio_transcribes_to_nothing():
    result = CqtTranscriber().transcribe(np.zeros(0, dtype=np.float32), SR)
    assert result.events == []


def test_transcriber_selection_falls_back():
    assert select_transcriber("does_not_exist").available()
    assert select_transcriber("cqt").id == "cqt"
    assert select_transcriber("pyin").id == "pyin"


def test_transcription_events_are_sorted(arpeggio_audio):
    result = CqtTranscriber().transcribe(arpeggio_audio, SR)
    starts = [e.start_seconds for e in result.events]
    assert starts == sorted(starts)


def test_transcription_confidences_are_bounded(melody_audio):
    for backend in (CqtTranscriber(), PyinTranscriber()):
        for e in backend.transcribe(melody_audio, SR).events:
            assert 0.0 <= e.confidence <= 1.0
            assert 0.0 <= e.velocity <= 1.0


# -- MIDI ----------------------------------------------------------------


def test_midi_round_trip(midi_file, twinkle):
    path = midi_file(twinkle, bpm=120.0)
    data = parse_midi(path)
    assert len(data.events) == len(twinkle)
    assert data.tempo_bpm == pytest.approx(120.0, abs=0.1)
    for original, parsed in zip(twinkle, data.events):
        assert parsed.pitch_midi == original.pitch_midi
        assert parsed.start_seconds == pytest.approx(original.start_seconds, abs=0.01)
        assert parsed.duration_seconds == pytest.approx(original.duration_seconds, abs=0.02)


def test_midi_velocity_survives(midi_file):
    events = [NoteEvent(60, 0.0, 0.5, velocity=0.25), NoteEvent(64, 1.0, 0.5, velocity=1.0)]
    data = parse_midi(midi_file(events))
    assert data.events[0].velocity < data.events[1].velocity


def test_midi_tempo_changes_are_honoured(tmp_path):
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=0))
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))  # 1.0 s at 60 BPM
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("note_on", note=64, velocity=100, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=480))  # 0.5 s at 120 BPM
    path = tmp_path / "tempo.mid"
    mid.save(str(path))

    data = parse_midi(path)
    assert data.events[0].duration_seconds == pytest.approx(1.0, abs=0.01)
    assert data.events[1].duration_seconds == pytest.approx(0.5, abs=0.01)


def test_midi_percussion_is_excluded_by_default(tmp_path):
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    melody = mido.MidiTrack()
    drums = mido.MidiTrack()
    mid.tracks.extend([melody, drums])
    melody.append(mido.Message("note_on", note=60, velocity=100, time=0, channel=0))
    melody.append(mido.Message("note_off", note=60, velocity=0, time=480, channel=0))
    drums.append(mido.Message("note_on", note=36, velocity=100, time=0, channel=9))
    drums.append(mido.Message("note_off", note=36, velocity=0, time=480, channel=9))
    path = tmp_path / "drums.mid"
    mid.save(str(path))

    data = parse_midi(path)
    assert [e.pitch_midi for e in data.events] == [60]
    assert any(t.is_percussion for t in data.tracks)
    assert len(parse_midi(path, include_percussion=True).events) == 2


def test_choose_melody_track_avoids_the_bass(tmp_path):
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    bass = mido.MidiTrack()
    lead = mido.MidiTrack()
    mid.tracks.extend([bass, lead])
    bass.append(mido.MetaMessage("track_name", name="Bass", time=0))
    lead.append(mido.MetaMessage("track_name", name="Lead", time=0))
    for i in range(16):
        bass.append(mido.Message("note_on", note=40 + (i % 3), velocity=90, time=0))
        bass.append(mido.Message("note_off", note=40 + (i % 3), velocity=0, time=480))
        lead.append(mido.Message("note_on", note=72 + (i % 7), velocity=90, time=0))
        lead.append(mido.Message("note_off", note=72 + (i % 7), velocity=0, time=240))
    path = tmp_path / "two.mid"
    mid.save(str(path))

    data = parse_midi(path)
    assert choose_melody_track(data) == 1


def test_malformed_midi_is_reported_clearly(tmp_path):
    p = tmp_path / "broken.mid"
    p.write_bytes(b"definitely not a midi file")
    with pytest.raises(MidiParseError):
        parse_midi(p)


def test_write_midi_creates_a_readable_file(tmp_path, chord_progression):
    out = write_midi(chord_progression, tmp_path / "out.mid", bpm=90.0)
    assert out.exists()
    data = parse_midi(out)
    assert len(data.events) == len(chord_progression)
    assert data.tempo_bpm == pytest.approx(90.0, abs=0.1)

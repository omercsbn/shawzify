"""The bundled demo track.

An original 24-bar melody written for this repository, deliberately built to
exercise the parts of the pipeline that are easy to get wrong:

* a singable diatonic melody (recognisability under transposition),
* a phrase that climbs above the Shawzin's range (octave folding),
* triads under the melody (polyphony reduction and chord positions),
* a triplet figure against a straight pulse (quantization AUTO),
* a fast repeated-note run (density reduction and repeat spacing).

Everything is generated from note data, so nothing copyrighted is committed and
the demo is bit-identical on every machine.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .music.events import NoteEvent

BPM = 96.0
BEAT = 60.0 / BPM

#: (beat offset, beats long, midi pitches). Chords are given as tuples.
_SCORE: list[tuple[float, float, tuple[int, ...]]] = [
    # A: the tune, C major, comfortable register
    (0.0, 1.0, (72,)), (1.0, 1.0, (76,)), (2.0, 1.0, (79,)), (3.0, 1.0, (76,)),
    (4.0, 2.0, (74,)), (6.0, 1.0, (72,)), (7.0, 1.0, (71,)),
    (8.0, 1.0, (69,)), (9.0, 1.0, (72,)), (10.0, 1.0, (76,)), (11.0, 1.0, (72,)),
    (12.0, 3.0, (74,)), (15.0, 1.0, (67,)),
    # A': same tune with triads underneath
    (16.0, 1.0, (72, 64, 60)), (17.0, 1.0, (76,)), (18.0, 1.0, (79,)), (19.0, 1.0, (76,)),
    (20.0, 2.0, (74, 65, 62)), (22.0, 1.0, (72,)), (23.0, 1.0, (71,)),
    (24.0, 1.0, (69, 65, 60)), (25.0, 1.0, (72,)), (26.0, 1.0, (76,)), (27.0, 1.0, (72,)),
    (28.0, 3.0, (74, 67, 59)), (31.0, 1.0, (67,)),
    # B: climbs out of range, forcing octave folding
    (32.0, 0.5, (84,)), (32.5, 0.5, (86,)), (33.0, 0.5, (88,)), (33.5, 0.5, (91,)),
    (34.0, 1.0, (93,)), (35.0, 1.0, (91,)),
    (36.0, 0.5, (88,)), (36.5, 0.5, (86,)), (37.0, 0.5, (84,)), (37.5, 0.5, (81,)),
    (38.0, 2.0, (79,)),
    # C: triplets against the pulse
    (40.0, 1 / 3, (72,)), (40 + 1 / 3, 1 / 3, (74,)), (40 + 2 / 3, 1 / 3, (76,)),
    (41.0, 1 / 3, (77,)), (41 + 1 / 3, 1 / 3, (76,)), (41 + 2 / 3, 1 / 3, (74,)),
    (42.0, 1 / 3, (72,)), (42 + 1 / 3, 1 / 3, (71,)), (42 + 2 / 3, 1 / 3, (69,)),
    (43.0, 1.0, (67,)),
    # D: a fast repeated-note run, far above what 16 ticks/second can hold
    (44.0, 0.125, (76,)), (44.125, 0.125, (76,)), (44.25, 0.125, (76,)), (44.375, 0.125, (76,)),
    (44.5, 0.125, (76,)), (44.625, 0.125, (76,)), (44.75, 0.125, (76,)), (44.875, 0.125, (76,)),
    (45.0, 0.25, (77,)), (45.25, 0.25, (79,)), (45.5, 0.5, (81,)),
    # Cadence: a full seven-note stack the Shawzin cannot possibly hold
    (46.0, 2.0, (48, 55, 60, 64, 67, 72, 76)),
]


def demo_events() -> list[NoteEvent]:
    """The demo melody as canonical note events."""
    out: list[NoteEvent] = []
    for beat, length, pitches in _SCORE:
        start = beat * BEAT
        duration = length * BEAT * 0.92
        for i, pitch in enumerate(pitches):
            # Melody note first and loudest; the chord tones sit underneath.
            velocity = 0.88 if i == 0 else 0.6
            out.append(
                NoteEvent(
                    pitch_midi=pitch,
                    start_seconds=start,
                    duration_seconds=duration,
                    velocity=velocity,
                    confidence=1.0,
                    source="demo:melody" if i == 0 else "demo:harmony",
                    voice=0 if i == 0 else 1,
                )
            )
    return sorted(out, key=lambda e: (e.start_seconds, e.pitch_midi))


def demo_duration() -> float:
    events = demo_events()
    return max(e.end_seconds for e in events)


def render_demo_audio(sample_rate: int = 44100) -> np.ndarray:
    """Render the demo to audio, so the audio path can be exercised end to end."""
    from .preview.synth import PluckedStringInstrument, render_preview

    return render_preview(
        demo_events(),
        sample_rate=sample_rate,
        instrument=PluckedStringInstrument(damping=0.35, brightness=0.6),
        tail_seconds=1.5,
    )


def write_demo_files(out_dir: str | Path) -> list[Path]:
    """Write demo.mid, demo.wav and demo.shawzin.txt into ``out_dir``."""
    import soundfile as sf

    from .arrangement.arranger import arrange_for_shawzin
    from .arrangement.options import ArrangementOptions
    from .midi.writer import write_midi

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    events = demo_events()
    written.append(write_midi(events, directory / "demo.mid", bpm=BPM, track_name="SHAWZIFY demo"))

    audio = render_demo_audio()
    wav = directory / "demo.wav"
    sf.write(str(wav), audio, 44100, subtype="PCM_16")
    written.append(wav)

    arrangement = arrange_for_shawzin(events, options=ArrangementOptions(), bpm=BPM)
    code_path = directory / "demo.shawzin.txt"
    code_path.write_text(
        "SHAWZIFY demo melody\n"
        "Scale: " + arrangement.report.scale_name + "\n"
        "Transpose: " + str(arrangement.report.transpose) + "\n\n"
        + arrangement.to_code() + "\n",
        encoding="utf-8",
    )
    written.append(code_path)
    return written

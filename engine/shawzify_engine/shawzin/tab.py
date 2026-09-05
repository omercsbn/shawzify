"""Human-readable Shawzin tab, for the CLI and for debugging an arrangement."""

from __future__ import annotations

from collections.abc import Sequence

from ..music.pitch import note_name
from .instrument import ShawzinInstrument, default_instrument
from .songcode import ShawzinEvent, ShawzinSong

FRET_LABELS = {"0": "open", "1": "sky", "2": "earth", "3": "water"}


def fret_label(fret: str) -> str:
    if fret in FRET_LABELS:
        return FRET_LABELS[fret]
    return "+".join(FRET_LABELS.get(ch, ch) for ch in fret)


def render_tab(
    song: ShawzinSong,
    instrument: ShawzinInstrument | None = None,
    *,
    max_rows: int = 60,
) -> str:
    """One line per event: time, fret state, strings, and what sounds."""
    inst = instrument or default_instrument()
    scale = inst.scale(song.scale_id)
    tps = inst.format.ticks_per_second
    lines = [
        "Scale: " + scale.name + "  (code " + scale.code + ")",
        "  time   fret          str  notes",
        "  ------ ------------- ---- --------------------------",
    ]
    shown = song.events[:max_rows]
    for ev in shown:
        seconds = ev.tick / float(tps)
        sounds: list[str] = []
        for ch in ev.string:
            pos = ev.fret + "-" + ch
            if ev.is_chord_fret:
                chord = scale.chord_at(pos)
                sounds.append(chord.name if chord else pos)
            else:
                note = scale.note_at(pos)
                sounds.append(note_name(note.midi) if note else pos)
        lines.append(
            "  {:>6} {:<13} {:<4} {}".format(
                f"{seconds:.2f}s", fret_label(ev.fret), ev.string, " ".join(sounds)
            )
        )
    if len(song.events) > max_rows:
        lines.append("  ... " + str(len(song.events) - max_rows) + " more events")
    return "\n".join(lines)


def render_grid(
    song: ShawzinSong,
    instrument: ShawzinInstrument | None = None,
    *,
    columns: int = 64,
) -> str:
    """A compact three-string grid, one column per tick, for quick eyeballing."""
    inst = instrument or default_instrument()
    if not song.events:
        return "(empty)"
    end = song.end_tick
    step = max(1, (end + 1) // columns + 1)
    rows = {s: ["-"] * (end // step + 1) for s in ("1", "2", "3")}
    for ev in song.events:
        col = ev.tick // step
        for ch in ev.string:
            if 0 <= col < len(rows[ch]):
                rows[ch][col] = ev.fret[0] if ev.fret != "0" else "o"
    tps = inst.format.ticks_per_second
    header = f"  (each column = {step / tps:.2f}s)"
    return "\n".join([header] + ["  S" + s + " |" + "".join(rows[s]) for s in ("3", "2", "1")])


def describe_positions(events: Sequence[ShawzinEvent]) -> list[str]:
    return [e.fret + "-" + e.string + "@" + str(e.tick) for e in events]

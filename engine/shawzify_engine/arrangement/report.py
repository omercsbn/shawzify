"""Compatibility scoring and quality metrics.

"Playable notes / total notes" is a bad score: it rates a piece that happens to
sit in C pentatonic at 100% even if the arrangement drops half the melody, and
rates a great arrangement of a chromatic tune at 40%. Both numbers here are
weighted by note importance and account for what actually happened to the
music.

* **Original compatibility** -- how much of the source the Shawzin could play
  as-is, with no transposition, on the scale that suits it best. This is the
  "before" number.
* **Optimized compatibility** -- how much of the source's *important*
  information the finished arrangement preserves: pitch, melody, rhythm and
  harmony, minus what was dropped or distorted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..music.events import NoteEvent, group_by_onset
from ..music.pitch import pitch_class
from ..shawzin.instrument import ShawzinInstrument
from .decisions import ArrangementDecision, Operation


@dataclass
class CompatibilityBreakdown:
    pitch_coverage: float = 0.0
    melody_preservation: float = 0.0
    rhythm_preservation: float = 0.0
    harmony_preservation: float = 0.0
    overall: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {k: round(v * 100.0, 1) for k, v in asdict(self).items()}


@dataclass
class QualityMetrics:
    source_notes: int = 0
    output_notes: int = 0
    removed_notes: int = 0
    moved_notes: int = 0
    octave_folded_notes: int = 0
    arpeggiated_notes: int = 0
    chord_substitutions: int = 0
    average_pitch_error: float = 0.0
    weighted_pitch_error: float = 0.0
    timing_error_mean: float = 0.0
    timing_error_max: float = 0.0
    melody_retention: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("average_pitch_error", "weighted_pitch_error", "timing_error_mean", "timing_error_max", "melody_retention"):
            d[k] = round(d[k], 4)
        return {_camel(k): v for k, v in d.items()}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


@dataclass
class ConversionReport:
    """Everything a conversion produced, beyond the code itself."""

    detected_key: str | None = None
    key_confidence: float = 0.0
    detected_bpm: float | None = None
    bpm_confidence: float = 0.0
    scale_id: str = ""
    scale_name: str = ""
    transpose: int = 0
    compatibility_before: CompatibilityBreakdown = field(default_factory=CompatibilityBreakdown)
    compatibility_after: CompatibilityBreakdown = field(default_factory=CompatibilityBreakdown)
    metrics: QualityMetrics = field(default_factory=QualityMetrics)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    stage_timings: list[dict[str, Any]] = field(default_factory=list)
    scale_candidates: list[dict[str, Any]] = field(default_factory=list)
    parts: int = 1
    engine_versions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detectedKey": self.detected_key,
            "keyConfidence": round(self.key_confidence, 3),
            "detectedBpm": round(self.detected_bpm, 2) if self.detected_bpm else None,
            "bpmConfidence": round(self.bpm_confidence, 3),
            "scaleId": self.scale_id,
            "scaleName": self.scale_name,
            "transpose": self.transpose,
            "compatibilityBefore": self.compatibility_before.to_dict(),
            "compatibilityAfter": self.compatibility_after.to_dict(),
            "metrics": self.metrics.to_dict(),
            "warnings": self.warnings,
            "durationSeconds": round(self.duration_seconds, 3),
            "stageTimings": self.stage_timings,
            "scaleCandidates": self.scale_candidates,
            "parts": self.parts,
            "engineVersions": self.engine_versions,
        }


def original_compatibility(
    events: Sequence[NoteEvent],
    instrument: ShawzinInstrument,
    importance: Sequence[float] | None = None,
) -> CompatibilityBreakdown:
    """How playable the source is untouched: no transposition, best scale as-is.

    Deliberately generous on scale choice (the player would pick the best scale)
    and strict on everything else -- no transposing, no octave folding.
    """
    if not events:
        return CompatibilityBreakdown()
    imp = list(importance) if importance is not None else [1.0] * len(events)
    total_imp = sum(imp) or 1.0

    best: CompatibilityBreakdown | None = None
    for scale in instrument.scales:
        playable = set(scale.playable_midi)
        pcs = scale.pitch_classes
        exact = sum(1 for e in events if e.pitch_midi in playable)
        weighted = sum(imp[i] for i, e in enumerate(events) if e.pitch_midi in playable)
        pc_only = sum(1 for e in events if pitch_class(e.pitch_midi) in pcs)

        groups = group_by_onset(events, 0.03)
        # Rhythm survives untouched only where the onset lands on the 1/16 grid.
        tick = 1.0 / instrument.format.ticks_per_second
        on_grid = 0
        for g in groups:
            off = abs((g[0].start_seconds / tick) - round(g[0].start_seconds / tick))
            if off < 0.25:
                on_grid += 1
        rhythm = on_grid / len(groups) if groups else 1.0

        # Harmony: a simultaneity survives only if every note is on one fret row.
        harmony_ok = 0
        for g in groups:
            positions = []
            for e in g:
                positions.extend(n for n in scale.notes if n.midi == e.pitch_midi)
            if not positions:
                continue
            frets = {p.fret for p in positions}
            strings = {p.string for p in positions}
            if len(frets) == 1 and len(strings) == len(g):
                harmony_ok += 1
            elif len(g) == 1:
                harmony_ok += 1
        harmony = harmony_ok / len(groups) if groups else 1.0

        melody_notes = [max(g, key=lambda e: e.pitch_midi) for g in groups]
        melody = sum(1 for e in melody_notes if e.pitch_midi in playable) / max(1, len(melody_notes))

        overall = (
            0.34 * (exact / len(events))
            + 0.22 * (weighted / total_imp)
            + 0.12 * (pc_only / len(events))
            + 0.16 * melody
            + 0.08 * rhythm
            + 0.08 * harmony
        )
        cand = CompatibilityBreakdown(
            pitch_coverage=exact / len(events),
            melody_preservation=melody,
            rhythm_preservation=rhythm,
            harmony_preservation=harmony,
            overall=overall,
        )
        if best is None or cand.overall > best.overall:
            best = cand
    return best or CompatibilityBreakdown()


def optimized_compatibility(
    decisions: Sequence[ArrangementDecision],
    *,
    melody_indices: Sequence[int] = (),
    source_groups: int = 0,
    output_groups: int = 0,
) -> tuple[CompatibilityBreakdown, QualityMetrics]:
    """Score the finished arrangement against the source it came from."""
    metrics = QualityMetrics(source_notes=len(decisions))
    if not decisions:
        return CompatibilityBreakdown(), metrics

    total_imp = sum(d.importance for d in decisions) or 1.0
    kept = [d for d in decisions if not d.removed and d.output_midi is not None]
    metrics.output_notes = len(kept)
    metrics.removed_notes = len(decisions) - len(kept)
    metrics.moved_notes = sum(1 for d in kept if d.pitch_delta != 0)
    metrics.octave_folded_notes = sum(1 for d in kept if Operation.OCTAVE_FOLD in d.operations)
    metrics.arpeggiated_notes = sum(1 for d in kept if Operation.ARPEGGIATE in d.operations)
    metrics.chord_substitutions = sum(1 for d in kept if Operation.CHORD_SUBSTITUTE in d.operations)

    if kept:
        # Pitch error is measured *modulo the global transposition*: shifting the
        # whole song does not distort it, moving one note relative to the rest does.
        deltas = [d.pitch_delta for d in kept]
        base = sorted(deltas)[len(deltas) // 2]
        errs = [abs(d.pitch_delta - base) for d in kept]
        metrics.average_pitch_error = sum(errs) / len(errs)
        metrics.weighted_pitch_error = sum(
            e * d.importance for e, d in zip(errs, kept)
        ) / (sum(d.importance for d in kept) or 1.0)
        timings = [abs(d.timing_delta) for d in kept]
        metrics.timing_error_mean = sum(timings) / len(timings)
        metrics.timing_error_max = max(timings)

    melody_set = set(melody_indices)
    if melody_set:
        kept_melody = sum(
            1 for d in kept if d.source_index in melody_set
        )
        metrics.melody_retention = kept_melody / len(melody_set)
    else:
        metrics.melody_retention = len(kept) / len(decisions)

    # -- the four public sub-scores -------------------------------------
    weighted_kept = sum(d.importance for d in kept)
    coverage = weighted_kept / total_imp

    # A kept note still loses credit for pitch error.
    pitch_quality = 0.0
    if kept:
        deltas = [d.pitch_delta for d in kept]
        base = sorted(deltas)[len(deltas) // 2]
        acc = 0.0
        for d in kept:
            err = abs(d.pitch_delta - base)
            if err == 0:
                acc += d.importance
            elif err % 12 == 0:
                acc += d.importance * 0.78  # octave displacement keeps the harmony
            else:
                acc += d.importance * max(0.0, 1.0 - err / 4.0) * 0.6
        pitch_quality = acc / total_imp

    melody_quality = metrics.melody_retention
    if melody_set and kept:
        mel_kept = [d for d in kept if d.source_index in melody_set]
        if mel_kept:
            deltas = [d.pitch_delta for d in mel_kept]
            base = sorted(deltas)[len(deltas) // 2]
            exactness = sum(
                1.0 if d.pitch_delta == base else (0.8 if (d.pitch_delta - base) % 12 == 0 else 0.4)
                for d in mel_kept
            ) / len(mel_kept)
            melody_quality = 0.6 * metrics.melody_retention + 0.4 * exactness

    # Rhythm: how little the onsets had to move, in units of a 1/16 s tick.
    if kept:
        rhythm_quality = sum(
            max(0.0, 1.0 - abs(d.timing_delta) / 0.125) * d.importance for d in kept
        ) / (sum(d.importance for d in kept) or 1.0)
    else:
        rhythm_quality = 0.0

    # Harmony: what share of simultaneities survived as simultaneities.
    if source_groups > 0:
        harmony_quality = min(1.0, output_groups / source_groups)
    else:
        harmony_quality = coverage

    overall = (
        0.30 * pitch_quality
        + 0.30 * melody_quality
        + 0.22 * rhythm_quality
        + 0.10 * harmony_quality
        + 0.08 * coverage
    )
    return (
        CompatibilityBreakdown(
            pitch_coverage=pitch_quality,
            melody_preservation=melody_quality,
            rhythm_preservation=rhythm_quality,
            harmony_preservation=harmony_quality,
            overall=max(0.0, min(1.0, overall)),
        ),
        metrics,
    )


def build_warnings(metrics: QualityMetrics, extra: Sequence[str] = ()) -> list[str]:
    """Actionable, non-alarming warnings for the UI."""
    out: list[str] = []
    if metrics.removed_notes > 0:
        pct = 100.0 * metrics.removed_notes / max(1, metrics.source_notes)
        out.append(
            str(metrics.removed_notes)
            + " notes were removed to fit the Shawzin ("
            + str(round(pct, 1))
            + "% of the source). Raise Complexity to keep more."
        )
    if metrics.octave_folded_notes > 0:
        out.append(
            str(metrics.octave_folded_notes)
            + " notes were shifted by an octave to fit the instrument's range."
        )
    if metrics.arpeggiated_notes > 0:
        out.append(
            str(metrics.arpeggiated_notes)
            + " notes were spread into arpeggios where a chord could not be struck at once."
        )
    if metrics.chord_substitutions > 0:
        out.append(
            str(metrics.chord_substitutions)
            + " chords were played using the Shawzin's built-in chord positions."
        )
    if metrics.weighted_pitch_error > 0.6:
        out.append(
            "Some notes are not in the chosen scale and were moved to the nearest "
            "available pitch. Try the Chromatic scale for closer pitches."
        )
    out.extend(extra)
    return out

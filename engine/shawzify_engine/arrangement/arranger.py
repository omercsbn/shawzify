"""The arrangement engine.

Pipeline, in order:

1. importance scoring and phrase detection
2. quantization (AUTO picks a grid from the onset histogram)
3. scale + transposition search
4. density reduction targeted at the passages that actually exceed budget
5. per-group placement: DP-mapped melody, then harmony on the same fret row,
   or a combined-fret chord where that preserves more
6. arpeggiation of what could not sound together, where there is room
7. tick snapping with repeat-note spacing, then validation

Every step records an :class:`ArrangementDecision` so the result can explain
itself. Given the same input, options and engine version the output is
identical -- there is no randomness anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import InstrumentConstraintError
from ..music.events import NoteEvent, group_by_onset, sort_events
from ..music.importance import ImportanceWeights, compute_importance
from ..music.key import KeyEstimate, estimate_key
from ..music.phrases import Phrase, detect_phrases
from ..music.quantize import choose_grid, quantize_events
from ..music.structure import SongStructure, analyze_structure, best_window, recognizability_weights
from ..shawzin.instrument import ShawzinInstrument, ShawzinScale, default_instrument
from ..shawzin.songcode import ShawzinEvent, ShawzinSong, encode, validate_events
from ..version import ARRANGEMENT_ENGINE_VERSION, version_dict
from .arpeggio import plan_arpeggio, should_arpeggiate
from .decisions import ArrangementDecision, Operation, describe_operations
from .density import measure_density, reduce_density, suggest_density
from .mapping import Candidate, MappingCosts, map_melody, map_single
from .options import AUTO, ArrangementOptions, Focus, ResolvedOptions
from .polyphony import best_chord_position, reduce_group
from .report import (
    ConversionReport,
    build_warnings,
    optimized_compatibility,
    original_compatibility,
)
from .scale_optimizer import ScaleCandidate, find_best_shawzin_mapping


@dataclass
class Arrangement:
    """A finished, playable arrangement."""

    song: ShawzinSong
    instrument: ShawzinInstrument
    options: ArrangementOptions
    resolved: ResolvedOptions
    decisions: list[ArrangementDecision] = field(default_factory=list)
    report: ConversionReport = field(default_factory=ConversionReport)
    source_events: list[NoteEvent] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    scale_candidates: list[ScaleCandidate] = field(default_factory=list)
    structure: SongStructure | None = None

    @property
    def scale(self) -> ShawzinScale:
        return self.instrument.scale(self.song.scale_id)

    @property
    def over_limits(self) -> bool:
        """True when this needs splitting before it can be imported as one code."""
        from ..shawzin.split import needs_split

        return needs_split(self.song, self.instrument)[0]

    def to_code(self, *, validate: bool = True) -> str:
        """Encode as a single song code.

        Raises when the arrangement exceeds the game's limits: check
        :attr:`over_limits` and use ``split_arrangement`` for those.
        """
        return encode(self.song, self.instrument, validate=validate)

    def output_notes(self) -> list[NoteEvent]:
        """The arrangement as real notes, for preview and MIDI export."""
        tps = self.instrument.format.ticks_per_second
        scale = self.scale
        out: list[NoteEvent] = []
        for ev in self.song.events:
            seconds = ev.tick / float(tps)
            for ch in ev.string:
                position = ev.fret + "-" + ch
                if ev.is_chord_fret:
                    chord = scale.chord_at(position)
                    if chord is None:
                        continue
                    for m in chord.midi:
                        out.append(
                            NoteEvent(m, seconds, self.instrument.variant.note_length_seconds,
                                      0.8, 1.0, "shawzin:chord " + position)
                        )
                    continue
                note = scale.note_at(position)
                if note is None:
                    continue
                out.append(
                    NoteEvent(note.midi, seconds, self.instrument.variant.note_length_seconds,
                              0.85, 1.0, "shawzin:" + position)
                )
        return sort_events(out)

    def to_dict(self, *, include_decisions: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "song": self.song.to_dict(),
            "resolved": self.resolved.to_dict(),
            "report": self.report.to_dict(),
            "scaleCandidates": [c.to_dict() for c in self.scale_candidates],
            "phrases": [p.to_dict() for p in self.phrases],
            "structure": self.structure.to_dict() if self.structure else None,
            "engineVersion": ARRANGEMENT_ENGINE_VERSION,
        }
        if include_decisions:
            d["decisions"] = [x.to_dict() for x in self.decisions]
        return d


def _resolve_quantization(
    events: Sequence[NoteEvent],
    options: ArrangementOptions,
    bpm: float | None,
    ticks_per_second: int,
) -> tuple[str, float, float]:
    """Returns ``(grid, strength, origin)``; grid ``"off"`` disables quantizing."""
    if options.quantization == "off":
        return ("off", 0.0, 0.0)
    if isinstance(options.quantization, str):
        from ..music.quantize import estimate_grid_origin

        grid = options.quantization
        return (grid, options.quantization_strength, estimate_grid_origin(events, bpm or 120.0, grid))
    if not bpm or bpm <= 0 or len(events) < 4:
        return ("off", 0.0, 0.0)
    grid, score, origin = choose_grid(events, bpm, ticks_per_second=ticks_per_second)
    if score < 0.55:
        # The onsets do not agree with any grid at this tempo; forcing one would
        # do more harm than good.
        return ("off", 0.0, 0.0)
    return (grid, options.quantization_strength, origin)


def _melody_indices(events: Sequence[NoteEvent], tolerance: float = 0.03) -> list[int]:
    index_of = {id(e): i for i, e in enumerate(events)}
    out = []
    for g in group_by_onset(events, tolerance):
        top = max(g, key=lambda e: e.pitch_midi)
        out.append(index_of[id(top)])
    return out


def arrange_for_shawzin(
    events: Sequence[NoteEvent],
    instrument: ShawzinInstrument | None = None,
    options: ArrangementOptions | None = None,
    *,
    bpm: float | None = None,
    bpm_confidence: float = 0.0,
    key: KeyEstimate | None = None,
    importance_weights: ImportanceWeights | None = None,
    structure: SongStructure | None = None,
    progress: Any = None,
) -> Arrangement:
    """Turn source note events into a playable Shawzin arrangement.

    ``structure`` is optional; when absent and ``options.use_structure`` is on,
    it is derived from the events. It feeds two things: an importance boost for
    notes in recognisable sections, and the Hook focus mode.
    """
    opts = options or ArrangementOptions()
    inst = instrument or default_instrument()
    if inst.variant.id != opts.shawzin_variant:
        inst = inst.with_variant(opts.shawzin_variant)
    profile = opts.profile

    incoming = sort_events(events)
    source = incoming
    if not source:
        resolved = ResolvedOptions(
            mode=opts.mode.value, scale_id="pmin", scale_name="Pentatonic Minor",
            transpose=0, quantization="off", quantization_strength=0.0,
            max_density=0.0, arpeggiate_chords=False, lead_in_ticks=0,
        )
        return Arrangement(ShawzinSong("pmin", []), inst, opts, resolved)

    # -- 0. structure, and the focus window it enables -------------------
    if structure is None and opts.use_structure:
        structure = analyze_structure(source, bpm=bpm)

    focus = Focus.FULL if isinstance(opts.focus, type(AUTO)) else opts.focus
    focus_window: tuple[float, float] | None = None
    focus_warning: str | None = None
    if focus is Focus.HOOK and structure is not None:
        total = max(e.end_seconds for e in source)
        limit = inst.format.max_song_seconds
        window = best_window(structure, window_seconds=limit, total_seconds=total)
        if window[1] - window[0] < total - 0.5:
            start, end = window
            trimmed = [
                e.moved(-start) for e in source if start <= e.start_seconds < end
            ]
            if trimmed:
                source = sort_events(trimmed)
                focus_window = window
                segment = structure.segment_at(start + (end - start) / 2)
                focus_warning = (
                    "Focused on the most recognisable "
                    + str(int(end - start))
                    + " seconds (from "
                    + _clock(start)
                    + " to "
                    + _clock(end)
                    + (", around the " + segment.role if segment else "")
                    + "). Switch focus to Full Song to arrange all of it."
                )

    # -- 1. analysis ----------------------------------------------------
    if key is None:
        key = estimate_key(source)
    phrases = detect_phrases(source, bpm=bpm)
    factors = compute_importance(source, bpm=bpm, weights=importance_weights, phrases=phrases)
    importance = [f.total for f in factors]
    if structure is not None and opts.use_structure and focus_window is None:
        # Notes in a repeated, high-energy section are the ones a listener would
        # recognise, so they should be the last to be thinned out.
        weights = recognizability_weights(source, structure)
        importance = [i * w for i, w in zip(importance, weights)]
    if progress:
        progress(0.15, "Scoring note importance")

    # -- 2. quantization ------------------------------------------------
    grid, strength, origin = _resolve_quantization(
        source, opts, bpm, inst.format.ticks_per_second
    )
    if grid != "off":
        working = quantize_events(
            source, bpm or 120.0, grid, strength=strength, origin=origin,
            quantize_durations=False,
        )
    else:
        working = list(source)
    # Quantization preserves order and count, so indices stay aligned with
    # ``source``, ``importance`` and ``phrases``.
    assert len(working) == len(source)
    if progress:
        progress(0.3, "Quantizing rhythm")

    # -- 3. scale search ------------------------------------------------
    candidates = find_best_shawzin_mapping(
        working, inst, opts, importance=importance, key=key, top_n=5
    )
    if not candidates:
        raise InstrumentConstraintError("No Shawzin scale could represent this music.")
    chosen = candidates[0]
    scale = inst.scale(chosen.scale_id)
    transpose = chosen.transpose
    if progress:
        progress(0.45, "Choosing scale " + scale.name)

    # -- 4. density -----------------------------------------------------
    budget = (
        float(opts.max_density)
        if not isinstance(opts.max_density, type(AUTO))
        else suggest_density(working, complexity=opts.complexity) * profile.density_scale
    )
    melody_idx = _melody_indices(working)
    protect = melody_idx if opts.preserve_melody else []
    density = reduce_density(
        working,
        importance,
        max_notes_per_second=budget,
        phrases=phrases,
        protect_indices=protect,
        bpm=bpm,
    )
    alive = set(density.kept)
    if progress:
        progress(0.6, "Managing density")

    # -- 5. decisions scaffold -----------------------------------------
    decisions = [
        ArrangementDecision(
            source_index=i,
            original=source[i],
            importance=importance[i],
        )
        for i in range(len(source))
    ]
    for i in range(len(source)):
        if abs(working[i].start_seconds - source[i].start_seconds) > 1e-6:
            decisions[i].add(Operation.QUANTIZE)
        if transpose != 0:
            decisions[i].add(Operation.TRANSPOSE)
    for i in density.removed:
        decisions[i].add(Operation.REMOVE)
        decisions[i].reason = (
            "Removed: this passage was denser than the Shawzin can play "
            "(" + str(round(budget, 1)) + " notes/second budget)."
        )

    # -- 6. placement ---------------------------------------------------
    live_events = [working[i] for i in sorted(alive)]
    live_indices = sorted(alive)
    groups = group_by_onset(live_events, 0.03)
    index_of = {id(e): live_indices[k] for k, e in enumerate(live_events)}

    lead_source: list[int] = []
    lead_pitches: list[int] = []
    for g in groups:
        top = max(g, key=lambda e: (e.pitch_midi, importance[index_of[id(e)]]))
        lead_source.append(index_of[id(top)])
        lead_pitches.append(top.pitch_midi + transpose)

    costs = MappingCosts().scaled(
        contour_weight=profile.contour_weight, pitch_weight=profile.pitch_error_weight
    )
    lead_map: list[Candidate] = map_melody(lead_pitches, scale, costs=costs)
    if progress:
        progress(0.75, "Mapping melody")

    arpeggiate = (
        profile.arpeggiate_default
        if isinstance(opts.arpeggiate_chords, type(AUTO))
        else bool(opts.arpeggiate_chords)
    )
    tps = inst.format.ticks_per_second
    observed_density = measure_density(live_events, 1.0)

    raw_events: list[tuple[int, str, str, list[int]]] = []  # tick, fret, string, source indices
    group_onsets = [g[0].start_seconds for g in groups]

    for gi, group in enumerate(groups):
        base_tick = int(round(group_onsets[gi] * tps))
        next_tick = (
            int(round(group_onsets[gi + 1] * tps)) if gi + 1 < len(groups) else base_tick + 8
        )
        available = max(0, next_tick - base_tick - 1)

        lead_index = lead_source[gi]
        cand = lead_map[gi]
        lead_note = None
        for n in scale.notes:
            if n.midi == cand.midi:
                lead_note = n
                break
        if lead_note is None:  # pragma: no cover - candidates come from the scale
            raise InstrumentConstraintError(
                "Mapped pitch is not on the instrument.",
                technical="midi=" + str(cand.midi) + " scale=" + scale.id,
            )

        group_indices = [index_of[id(e)] for e in group]

        # Chord substitution: worth it only for real simultaneities in a mode
        # that wants harmony.
        used_chord = False
        if profile.prefer_chord_frets and len(group) >= 2 and scale.chords:
            pitches = [working[i].pitch_midi + transpose for i in group_indices]
            found = best_chord_position(scale, pitches, minimum=0.62)
            if found is not None:
                chord, quality = found
                raw_events.append((base_tick, chord.fret, chord.string, group_indices))
                for i in group_indices:
                    decisions[i].add(Operation.CHORD_SUBSTITUTE)
                    decisions[i].output_midi = min(
                        chord.midi, key=lambda m: abs(m - (working[i].pitch_midi + transpose))
                    )
                    decisions[i].output_seconds = base_tick / float(tps)
                    decisions[i].position = chord.position
                    decisions[i].cost = 1.0 - quality
                    decisions[i].reason = (
                        "Played as the Shawzin " + chord.name + " chord position."
                    )
                used_chord = True
        if used_chord:
            continue

        placements, unplaced = reduce_group(
            working,
            group_indices,
            scale,
            lead_index=lead_index,
            lead_note=lead_note,
            importance=importance,
            max_voices=min(profile.max_voices, inst.max_simultaneous_strings),
            harmony_weight=profile.harmony_weight,
        )
        strings = "".join(sorted({p.string for p in placements}))
        raw_events.append((base_tick, lead_note.fret, strings, [p.source_index for p in placements]))
        for p in placements:
            d = decisions[p.source_index]
            d.output_midi = p.midi
            d.output_seconds = base_tick / float(tps)
            d.position = p.position
            src_pitch = working[p.source_index].pitch_midi + transpose
            if p.midi != src_pitch:
                if (p.midi - src_pitch) % 12 == 0:
                    d.add(Operation.OCTAVE_FOLD)
                else:
                    d.add(Operation.SIMPLIFY)
            if not d.operations:
                d.add(Operation.KEEP)
            d.cost = abs(p.midi - src_pitch) / 12.0
            d.reason = describe_operations(d.operations)

        # Anything that did not fit: arpeggiate if there is room, else drop.
        if unplaced:
            spread = should_arpeggiate(
                unplaced_count=len(unplaced),
                available_ticks=available,
                notes_per_second=observed_density,
                enabled=arpeggiate,
            )
            handled: set[int] = set()
            if spread:
                pitches = [working[i].pitch_midi + transpose for i in unplaced]
                plan = plan_arpeggio(
                    pitches, available_ticks=available, bpm=bpm, ticks_per_second=tps
                )
                if plan is not None:
                    for slot, order_index in enumerate(plan.order):
                        src_i = unplaced[order_index]
                        offset = plan.tick_offsets[slot] + 1
                        tick = base_tick + offset
                        if tick >= next_tick:
                            break
                        mapped = map_single(
                            working[src_i].pitch_midi + transpose, scale, near=cand.midi
                        )
                        note = next((n for n in scale.notes if n.midi == mapped.midi), None)
                        if note is None:
                            continue
                        raw_events.append((tick, note.fret, note.string, [src_i]))
                        d = decisions[src_i]
                        d.add(Operation.ARPEGGIATE)
                        d.output_midi = note.midi
                        d.output_seconds = tick / float(tps)
                        d.position = note.position
                        d.cost = 0.5 + abs(note.midi - (working[src_i].pitch_midi + transpose)) / 12.0
                        d.reason = describe_operations(d.operations)
                        handled.add(src_i)
            for i in unplaced:
                if i in handled:
                    continue
                d = decisions[i]
                d.add(Operation.REMOVE)
                d.reason = (
                    "Removed: the Shawzin cannot sound this note at the same "
                    "moment as the melody (all notes played together must share "
                    "one fret position)."
                )

    if progress:
        progress(0.88, "Placing harmony")

    # -- 7. build song events, enforcing the one-fret-per-instant rule ---
    song_events = _build_song_events(raw_events, opts.min_repeat_ticks, decisions, tps)

    lead_in = (
        inst.format.default_lead_in_ticks
        if isinstance(opts.lead_in_ticks, type(AUTO))
        else int(opts.lead_in_ticks)
    )
    song = ShawzinSong(scale_id=scale.id, events=song_events)
    # Instrument constraints must hold; the length and note-count limits are
    # handled by splitting, so an over-long arrangement is not an error here.
    validate_events(
        song.events,
        inst,
        offset=song.events[0].tick if song.events else 0,
        check_limits=False,
    )

    # -- 8. report ------------------------------------------------------
    before = original_compatibility(source, inst, importance)
    output_groups = len({e.tick for e in song.events})
    after, metrics = optimized_compatibility(
        decisions,
        melody_indices=melody_idx,
        source_groups=len(group_by_onset(source, 0.03)),
        output_groups=output_groups,
    )
    warnings = build_warnings(metrics)
    if focus_warning:
        warnings.insert(0, focus_warning)
    if grid == "off" and isinstance(opts.quantization, type(AUTO)):
        warnings.append("Quantization was left off: the timing did not fit a regular grid.")
    if song.note_count > inst.format.chat_link_max_notes:
        warnings.append(
            "This song has "
            + str(song.note_count)
            + " notes, so it can be imported from the clipboard but not linked in chat "
            "(the chat limit is "
            + str(inst.format.chat_link_max_notes)
            + ")."
        )

    report = ConversionReport(
        detected_key=key.name if key else None,
        key_confidence=key.confidence if key else 0.0,
        detected_bpm=bpm,
        bpm_confidence=bpm_confidence,
        scale_id=scale.id,
        scale_name=scale.name,
        transpose=transpose,
        compatibility_before=before,
        compatibility_after=after,
        metrics=metrics,
        warnings=warnings,
        duration_seconds=song.duration_seconds(tps),
        scale_candidates=[c.to_dict() for c in candidates],
        engine_versions=version_dict(),
    )
    resolved = ResolvedOptions(
        mode=opts.mode.value,
        scale_id=scale.id,
        scale_name=scale.name,
        transpose=transpose,
        quantization=grid,
        quantization_strength=strength,
        max_density=budget,
        arpeggiate_chords=arpeggiate,
        lead_in_ticks=lead_in,
        focus=focus.value,
        focus_window=focus_window,
        detail={
            "observedDensity": round(observed_density, 2),
            "peakDensityAfter": round(density.peak_density, 2),
            "scaleScore": round(chosen.score * 100.0, 2),
            "quantizationOrigin": round(origin, 5),
        },
    )
    if progress:
        progress(1.0, "Arrangement ready")
    return Arrangement(
        song=song,
        instrument=inst,
        options=opts,
        resolved=resolved,
        decisions=decisions,
        report=report,
        source_events=list(source),
        phrases=phrases,
        scale_candidates=candidates,
        structure=structure,
    )


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    return str(minutes) + ":" + str(secs).zfill(2)


def _build_song_events(
    raw: Sequence[tuple[int, str, str, list[int]]],
    min_repeat_ticks: int,
    decisions: Sequence[ArrangementDecision],
    ticks_per_second: int,
) -> list[ShawzinEvent]:
    """Merge, deconflict and order raw placements into valid song events.

    Two rules are enforced here rather than hoped for:
      * one fret state per tick -- a later event with a different fret is nudged
        forward until it has a tick to itself;
      * a string may not be re-plucked within ``min_repeat_ticks``.
    """
    by_tick: dict[int, list[tuple[str, str, list[int]]]] = {}
    for tick, fret, strings, sources in sorted(raw, key=lambda r: (r[0], r[1], r[2])):
        by_tick.setdefault(tick, []).append((fret, strings, sources))

    out: list[ShawzinEvent] = []
    occupied: dict[int, str] = {}  # tick -> fret state already claimed
    last_pluck: dict[str, int] = {}  # string -> last tick used
    # Indexed by target tick so the string-conflict and merge checks stay O(1)
    # rather than scanning everything emitted so far.
    by_target: dict[int, list[ShawzinEvent]] = {}
    index_in_out: dict[int, int] = {}

    for tick in sorted(by_tick):
        for fret, strings, sources in by_tick[tick]:
            target = tick
            # Find a tick whose fret state is free (or already matches).
            for _ in range(64):
                claimed = occupied.get(target)
                if claimed is None or claimed == fret:
                    break
                target += 1
            claimed = occupied.get(target)
            if claimed is not None and claimed != fret:
                for i in sources:
                    decisions[i].add(Operation.REMOVE)
                    decisions[i].reason = (
                        "Removed: no free moment nearby with a compatible fret position."
                    )
                continue

            at_target = by_target.get(target, [])
            usable = ""
            for ch in strings:
                prev = last_pluck.get(ch)
                if prev is not None and target - prev < min_repeat_ticks:
                    continue
                if any(ch in e.string for e in at_target):
                    continue
                usable += ch
            if not usable:
                for i in sources:
                    decisions[i].add(Operation.REMOVE)
                    decisions[i].reason = (
                        "Removed: the same string was already plucked at this moment."
                    )
                continue

            merged = False
            for k, existing in enumerate(at_target):
                if existing.fret == fret:
                    combined = "".join(sorted(set(existing.string + usable)))
                    replacement = ShawzinEvent(target, fret, combined)
                    out[index_in_out[id(existing)]] = replacement
                    at_target[k] = replacement
                    index_in_out[id(replacement)] = index_in_out.pop(id(existing))
                    merged = True
                    break
            if not merged:
                event = ShawzinEvent(target, fret, usable)
                index_in_out[id(event)] = len(out)
                out.append(event)
                by_target.setdefault(target, []).append(event)
            occupied[target] = fret
            for ch in usable:
                last_pluck[ch] = target
            if target != tick:
                for i in sources:
                    decisions[i].output_seconds = target / float(ticks_per_second)

    return sorted(out, key=lambda e: (e.tick, e.fret, e.string))

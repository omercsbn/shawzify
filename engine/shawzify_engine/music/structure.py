"""Song structure and hook detection.

The Shawzin holds four minutes and a thousand notes. A five-minute pop song
does not fit, and the part a listener would recognise is almost never the first
four minutes -- it is the chorus, which usually starts around a third of the way
in.

So SHAWZIFY works out where the sections are, which of them repeat, and which
one is the hook, and then uses that twice:

* **Choosing what to keep.** When a song is over the limit, the "best window"
  is the one containing the hook, not the first N seconds.
* **Choosing which notes survive.** Notes inside a repeated, high-energy
  section carry more recognition than notes in an intro or a bridge, so they
  get an importance boost.

The method is the standard one for structure analysis: a self-similarity matrix
over chroma features, novelty detection along its diagonal for boundaries, then
clustering the resulting segments by how similar they are to each other. It
works on note events as well as audio, which matters because MIDI input never
goes near a spectrogram.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .events import NoteEvent, group_by_onset, sort_events
from .pitch import pitch_class


@dataclass
class Segment:
    """One structural section of a song."""

    index: int
    start_seconds: float
    end_seconds: float
    #: Segments sharing a label are repetitions of the same material.
    label: int
    #: How many times this material occurs in the song.
    repetitions: int = 1
    energy: float = 0.0
    density: float = 0.0
    #: 0..1. How likely a listener is to identify the song from this section.
    recognizability: float = 0.0
    #: Best guess at a musical role, for display only.
    role: str = "section"

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds

    def contains(self, seconds: float) -> bool:
        return self.start_seconds <= seconds < self.end_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "startSeconds": round(self.start_seconds, 3),
            "endSeconds": round(self.end_seconds, 3),
            "durationSeconds": round(self.duration, 3),
            "label": self.label,
            "repetitions": self.repetitions,
            "energy": round(self.energy, 4),
            "density": round(self.density, 3),
            "recognizability": round(self.recognizability, 4),
            "role": self.role,
        }


@dataclass
class SongStructure:
    segments: list[Segment] = field(default_factory=list)
    #: The section a listener would name the song from.
    hook_index: int | None = None
    backend: str = "events"

    @property
    def hook(self) -> Segment | None:
        if self.hook_index is None or self.hook_index >= len(self.segments):
            return None
        return self.segments[self.hook_index]

    def segment_at(self, seconds: float) -> Segment | None:
        for s in self.segments:
            if s.contains(seconds):
                return s
        return self.segments[-1] if self.segments else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "hookIndex": self.hook_index,
            "hook": self.hook.to_dict() if self.hook else None,
            "backend": self.backend,
        }


# -- feature extraction --------------------------------------------------


def chroma_from_events(
    events: Sequence[NoteEvent], *, frame_seconds: float = 0.5, duration: float | None = None
) -> tuple[np.ndarray, float]:
    """A 12 x frames chroma matrix built from note events.

    Works for MIDI and for transcribed audio alike, which is why structure
    analysis does not need the original waveform.
    """
    ordered = sort_events(events)
    if not ordered:
        return (np.zeros((12, 1), dtype=np.float32), frame_seconds)
    total = duration or max(e.end_seconds for e in ordered)
    frames = max(1, int(math.ceil(total / frame_seconds)))
    chroma = np.zeros((12, frames), dtype=np.float32)
    for ev in ordered:
        start = max(0, int(ev.start_seconds / frame_seconds))
        end = min(frames - 1, int(ev.end_seconds / frame_seconds))
        weight = 0.4 + 0.6 * float(np.clip(ev.velocity, 0.0, 1.0))
        chroma[pitch_class(ev.pitch_midi), start : end + 1] += weight
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    return (chroma / np.maximum(norms, 1e-6), frame_seconds)


def structure_features(
    events: Sequence[NoteEvent], *, frame_seconds: float = 0.5, duration: float | None = None
) -> tuple[np.ndarray, float]:
    """Chroma plus register, density and energy contours.

    Chroma alone cannot tell a verse from a chorus in a song that stays in one
    key -- every frame looks alike and the whole track collapses into a single
    section. What actually separates them is that a chorus sits higher, moves
    faster and hits harder, so those three contours join the feature vector.
    """
    ordered = sort_events(events)
    chroma, frame_seconds = chroma_from_events(
        ordered, frame_seconds=frame_seconds, duration=duration
    )
    frames = chroma.shape[1]
    register = np.zeros(frames, dtype=np.float32)
    density = np.zeros(frames, dtype=np.float32)
    energy = np.zeros(frames, dtype=np.float32)
    counts = np.zeros(frames, dtype=np.float32)

    for ev in ordered:
        index = min(frames - 1, max(0, int(ev.start_seconds / frame_seconds)))
        register[index] += ev.pitch_midi
        energy[index] += float(np.clip(ev.velocity, 0.0, 1.0))
        counts[index] += 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        register = np.where(counts > 0, register / np.maximum(counts, 1e-6), 0.0)
    density = counts.copy()

    # Smooth the contours over a few seconds: a section is a trend, not a frame.
    span = max(3, int(round(4.0 / frame_seconds)) | 1)
    kernel = np.ones(span, dtype=np.float32) / span
    def smooth(values: np.ndarray) -> np.ndarray:
        if values.size < span:
            return values
        return np.convolve(values, kernel, mode="same")

    register = smooth(register)
    density = smooth(density)
    energy = smooth(energy)

    def scaled(values: np.ndarray) -> np.ndarray:
        low, high = float(values.min()), float(values.max())
        if high - low < 1e-6:
            return np.zeros_like(values)
        return (values - low) / (high - low)

    # Weights set how much each contour can outvote harmony. Chroma is a unit
    # vector of 12 components, so a single contour at 0.7 is roughly comparable.
    extras = np.vstack(
        [
            0.70 * scaled(register),
            0.55 * scaled(density),
            0.45 * scaled(energy),
        ]
    ).astype(np.float32)
    return (np.vstack([chroma, extras]), frame_seconds)


def _self_similarity(features: np.ndarray) -> np.ndarray:
    """Cosine similarity between every pair of frames."""
    normed = features / np.maximum(np.linalg.norm(features, axis=0, keepdims=True), 1e-6)
    return np.clip(normed.T @ normed, 0.0, 1.0)


def _novelty(similarity: np.ndarray, kernel_size: int) -> np.ndarray:
    """Checkerboard-kernel novelty: high where the music changes character."""
    n = similarity.shape[0]
    half = max(1, kernel_size // 2)
    if n < 2 * half + 1:
        return np.zeros(n, dtype=np.float32)

    # A Gaussian-tapered checkerboard kernel: positive on the two diagonal
    # quadrants, negative on the off-diagonal ones.
    axis = np.arange(-half, half + 1, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(axis, axis)
    taper = np.exp(-0.35 * (grid_x**2 + grid_y**2) / (half**2 + 1e-6))
    checker = np.sign(grid_x) * np.sign(grid_y)
    kernel = (checker * taper).astype(np.float32)

    novelty = np.zeros(n, dtype=np.float32)
    for i in range(half, n - half):
        block = similarity[i - half : i + half + 1, i - half : i + half + 1]
        novelty[i] = float(np.sum(block * kernel))
    novelty = np.maximum(novelty, 0.0)
    peak = novelty.max()
    return novelty / peak if peak > 0 else novelty


def _pick_boundaries(
    novelty: np.ndarray, frame_seconds: float, *, min_segment_seconds: float
) -> list[int]:
    """Local maxima of the novelty curve, spaced at least a section apart."""
    min_gap = max(1, int(min_segment_seconds / frame_seconds))
    if novelty.size < 3:
        return []
    threshold = float(novelty.mean() + 0.5 * novelty.std())
    peaks: list[int] = []
    for i in range(1, len(novelty) - 1):
        if novelty[i] < threshold:
            continue
        if novelty[i] < novelty[i - 1] or novelty[i] < novelty[i + 1]:
            continue
        if peaks and i - peaks[-1] < min_gap:
            # Keep whichever of the two is the stronger change.
            if novelty[i] > novelty[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)
    return peaks


def _label_segments(features: np.ndarray, bounds: list[tuple[int, int]], threshold: float = 0.93) -> list[int]:
    """Group segments whose average feature vectors are near-identical."""
    centroids = []
    for start, end in bounds:
        block = features[:, start:end]
        if block.size == 0:
            centroids.append(np.zeros(features.shape[0], dtype=np.float32))
        else:
            v = block.mean(axis=1)
            centroids.append(v / max(float(np.linalg.norm(v)), 1e-6))

    labels: list[int] = []
    representatives: list[np.ndarray] = []
    for centroid in centroids:
        matched = -1
        for i, rep in enumerate(representatives):
            if float(centroid @ rep) >= threshold:
                matched = i
                break
        if matched < 0:
            representatives.append(centroid)
            matched = len(representatives) - 1
        labels.append(matched)
    return labels


def _assign_roles(segments: list[Segment], total: float) -> None:
    """Label sections for display. Heuristic and honest about being so."""
    if not segments:
        return
    best_recognizability = max(s.recognizability for s in segments)
    for s in segments:
        position = s.start_seconds / total if total > 0 else 0.0
        if s.index == 0 and s.energy < 0.7 * (best_recognizability or 1.0):
            s.role = "intro"
        elif s.recognizability >= best_recognizability * 0.92 and s.repetitions > 1:
            s.role = "chorus"
        elif s.repetitions > 1:
            s.role = "verse"
        elif position > 0.55 and s.repetitions == 1:
            s.role = "bridge"
        elif s.index == len(segments) - 1:
            s.role = "outro"
        else:
            s.role = "section"


def analyze_structure(
    events: Sequence[NoteEvent],
    *,
    duration: float | None = None,
    bpm: float | None = None,
    frame_seconds: float = 0.5,
    min_segment_seconds: float | None = None,
) -> SongStructure:
    """Find sections, spot the repeats, and pick the hook."""
    ordered = sort_events(events)
    total = duration or (max(e.end_seconds for e in ordered) if ordered else 0.0)
    if len(ordered) < 8 or total < 8.0:
        # Too little to have a structure. One section, and say so.
        segment = Segment(0, 0.0, total, 0, 1, 1.0, len(ordered) / max(total, 1e-6), 1.0, "section")
        return SongStructure([segment], 0, "events")

    # A section is at least four bars, floored at eight seconds.
    if min_segment_seconds is None:
        bar = (60.0 / bpm) * 4.0 if bpm and bpm > 0 else 2.0
        min_segment_seconds = max(8.0, min(30.0, bar * 4.0))

    features, frame_seconds = structure_features(
        ordered, frame_seconds=frame_seconds, duration=total
    )
    frames = features.shape[1]
    similarity = _self_similarity(features)
    kernel = max(3, int(min_segment_seconds / frame_seconds))
    novelty = _novelty(similarity, kernel)
    peaks = _pick_boundaries(novelty, frame_seconds, min_segment_seconds=min_segment_seconds)

    edges = [0, *peaks, frames]
    bounds = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] > edges[i]]
    if not bounds:
        bounds = [(0, frames)]
    labels = _label_segments(features, bounds)

    counts: dict[int, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    # Per-segment energy and density come from the events themselves.
    segments: list[Segment] = []
    for i, ((start, end), label) in enumerate(zip(bounds, labels)):
        t0 = start * frame_seconds
        t1 = min(total, end * frame_seconds)
        inside = [e for e in ordered if t0 <= e.start_seconds < t1]
        span = max(t1 - t0, 1e-6)
        energy = sum(e.velocity for e in inside) / span if inside else 0.0
        density = len(inside) / span
        segments.append(
            Segment(i, t0, t1, label, counts[label], energy, density)
        )

    _score_recognizability(segments, total)
    _assign_roles(segments, total)
    hook = max(range(len(segments)), key=lambda i: segments[i].recognizability)
    return SongStructure(segments, hook, "events")


def _score_recognizability(segments: list[Segment], total: float) -> None:
    """How identifiable each section is.

    Repetition dominates: the part of a song that comes back is the part people
    remember. Energy and density matter next, and sections at the very start or
    very end are discounted because intros and outros rarely carry the tune.
    """
    if not segments:
        return
    max_reps = max(s.repetitions for s in segments) or 1
    max_energy = max((s.energy for s in segments), default=0.0) or 1.0
    max_density = max((s.density for s in segments), default=0.0) or 1.0

    for s in segments:
        repetition = s.repetitions / max_reps
        energy = s.energy / max_energy
        density = min(1.0, s.density / max_density)
        position = (s.start_seconds + s.duration / 2) / total if total > 0 else 0.5
        # A gentle preference for the middle of the song.
        centrality = 1.0 - abs(position - 0.45) * 0.9
        length = min(1.0, s.duration / 20.0)
        s.recognizability = max(
            0.0,
            min(
                1.0,
                0.42 * repetition
                + 0.22 * energy
                + 0.14 * density
                + 0.12 * centrality
                + 0.10 * length,
            ),
        )


def best_window(
    structure: SongStructure,
    *,
    window_seconds: float,
    total_seconds: float,
) -> tuple[float, float]:
    """The ``window_seconds`` stretch that carries the most recognition.

    Used when a song is too long for the Shawzin: rather than taking the first
    four minutes, take the four minutes containing the hook, aligned to section
    boundaries so it does not start mid-phrase.
    """
    if total_seconds <= window_seconds or not structure.segments:
        return (0.0, min(total_seconds, window_seconds))

    starts = sorted({s.start_seconds for s in structure.segments} | {0.0})
    best_start = 0.0
    best_score = -1.0
    for start in starts:
        if start + window_seconds > total_seconds + 1e-6:
            start = max(0.0, total_seconds - window_seconds)
        end = start + window_seconds
        score = 0.0
        for s in structure.segments:
            overlap = max(0.0, min(end, s.end_seconds) - max(start, s.start_seconds))
            if overlap > 0:
                score += s.recognizability * overlap
        if score > best_score:
            best_score = score
            best_start = start
    return (best_start, min(total_seconds, best_start + window_seconds))


def recognizability_weights(
    events: Sequence[NoteEvent], structure: SongStructure
) -> list[float]:
    """A 0..1 multiplier per event, from the section it lives in.

    Feeds the importance model so density reduction sacrifices an intro before
    it touches the chorus.
    """
    ordered = sort_events(events)
    if not structure.segments:
        return [1.0] * len(ordered)
    out: list[float] = []
    for ev in ordered:
        segment = structure.segment_at(ev.start_seconds)
        out.append(0.55 + 0.45 * (segment.recognizability if segment else 0.5))
    return out


def melodic_hook(
    events: Sequence[NoteEvent], structure: SongStructure, *, max_notes: int = 24
) -> list[NoteEvent]:
    """The handful of notes most likely to make someone say "oh, that song".

    The top line of the hook section, trimmed to a phrase-sized run.
    """
    hook = structure.hook
    if hook is None:
        return []
    inside = [e for e in sort_events(events) if hook.contains(e.start_seconds)]
    if not inside:
        return []
    tops = [max(g, key=lambda e: e.pitch_midi) for g in group_by_onset(inside, 0.03)]
    return tops[:max_notes]

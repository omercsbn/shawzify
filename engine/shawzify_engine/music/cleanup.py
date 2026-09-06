"""Remove what the transcriber invented, before it decides the arrangement.

Automatic transcription of a real recording is not a score. It reports notes
that are not there: harmonics an octave or two above the melody, rumble below
it, and fragments a few tens of milliseconds long where a sung note wavered.

Those notes are a small fraction of the total and they are ruinous, because the
decisions that follow are made from the *extremes* of the note set rather than
its bulk. Range fit, transposition and octave folding all read the highest and
lowest pitches present. Measured on Rob Dougan's "Clubbed to Death": 135 notes
out of 4829, under three percent, stretched the apparent range by two octaves
and dropped pitch accuracy from what should have been 56% to 4.6%. Removing
them changed nothing else about the piece and improved it twelvefold.

Two rules, both conservative, because throwing away a real note is worse than
keeping a spurious one:

* A pitch far outside where the music actually lives is dropped only when the
  transcriber was also unsure of it. A piccolo really does play up there; a
  confident outlier is kept.
* A note shorter than the instrument's own tick cannot be played at all. Where
  it is a fragment of the note beside it, it is merged into it rather than
  discarded, so a wavering vocal line becomes one note instead of none.

MIDI input goes nowhere near this. A MIDI file is exact, and its extremes are
the composer's.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .events import NoteEvent

#: One Shawzin tick. Nothing shorter can be represented at all.
TICK_SECONDS = 1.0 / 16.0

#: How far outside the body of the music a pitch must sit to be suspected.
_OUTLIER_MARGIN_SEMITONES = 6.0

#: Only suspect notes the transcriber itself was unsure about.
_DOUBT = 0.6

#: A gap this small between two notes of the same pitch reads as one note.
_MERGE_GAP_SECONDS = 0.09


@dataclass(frozen=True)
class CleanupReport:
    """What was removed, so the interface can say so rather than hide it."""

    kept: int
    outliers_removed: int
    fragments_merged: int
    fragments_removed: int
    low_range: int | None = None
    high_range: int | None = None

    @property
    def removed(self) -> int:
        return self.outliers_removed + self.fragments_removed

    def to_dict(self) -> dict[str, int | None]:
        return {
            "kept": self.kept,
            "outliersRemoved": self.outliers_removed,
            "fragmentsMerged": self.fragments_merged,
            "fragmentsRemoved": self.fragments_removed,
            "lowRange": self.low_range,
            "highRange": self.high_range,
        }

    def summary(self) -> str | None:
        """A sentence for the user, or nothing when nothing happened."""
        parts = []
        if self.outliers_removed:
            parts.append(
                str(self.outliers_removed)
                + " uncertain notes outside the music's range were ignored"
            )
        if self.fragments_merged:
            parts.append(str(self.fragments_merged) + " fragments were joined to the note they belong to")
        if self.fragments_removed:
            parts.append(str(self.fragments_removed) + " notes too short to play were dropped")
        if not parts:
            return None
        return "Cleaned up the transcription: " + ", ".join(parts) + "."


def _confidence(event: NoteEvent) -> float:
    return 1.0 if event.confidence is None else float(event.confidence)


def _body_of_the_music(events: list[NoteEvent]) -> tuple[float, float]:
    """The register the music actually occupies, ignoring its tails."""
    pitches = sorted(e.pitch_midi for e in events)
    count = len(pitches)
    low = pitches[int(count * 0.05)]
    high = pitches[min(count - 1, int(count * 0.95))]
    return low - _OUTLIER_MARGIN_SEMITONES, high + _OUTLIER_MARGIN_SEMITONES


def _merge_fragments(events: list[NoteEvent]) -> tuple[list[NoteEvent], int, int]:
    """Join sub-tick notes to the note they are part of; drop the rest."""
    ordered = sorted(events, key=lambda e: (e.start_seconds, e.pitch_midi))
    result: list[NoteEvent] = []
    merged = 0
    dropped = 0

    for event in ordered:
        previous = None
        for candidate in reversed(result[-8:]):  # recent notes only
            if candidate.pitch_midi != event.pitch_midi:
                continue
            end = candidate.start_seconds + candidate.duration_seconds
            if event.start_seconds - end <= _MERGE_GAP_SECONDS:
                previous = candidate
            break

        long_enough = event.duration_seconds >= TICK_SECONDS
        if previous is not None and (not long_enough or event.start_seconds < previous.start_seconds + previous.duration_seconds):
            # Extend the earlier note rather than plucking the string twice.
            index = result.index(previous)
            end = max(
                previous.start_seconds + previous.duration_seconds,
                event.start_seconds + event.duration_seconds,
            )
            result[index] = NoteEvent(
                pitch_midi=previous.pitch_midi,
                start_seconds=previous.start_seconds,
                duration_seconds=end - previous.start_seconds,
                velocity=max(previous.velocity, event.velocity),
                confidence=max(_confidence(previous), _confidence(event)),
                source=previous.source,
                voice=previous.voice,
            )
            merged += 1
            continue

        if not long_enough:
            dropped += 1
            continue

        result.append(event)

    return result, merged, dropped


def clean_transcription(events: list[NoteEvent]) -> tuple[list[NoteEvent], CleanupReport]:
    """Drop what the transcriber most likely invented. Safe on an empty list."""
    if len(events) < 20:
        # Too few to reason about a distribution, and too few to be worth it.
        return list(events), CleanupReport(kept=len(events), outliers_removed=0,
                                          fragments_merged=0, fragments_removed=0)

    low, high = _body_of_the_music(events)
    confidences = [_confidence(e) for e in events]
    doubtful = min(_DOUBT, statistics.median(confidences))

    kept: list[NoteEvent] = []
    outliers = 0
    for event in events:
        outside = event.pitch_midi < low or event.pitch_midi > high
        if outside and _confidence(event) <= doubtful:
            outliers += 1
            continue
        kept.append(event)

    kept, merged, dropped = _merge_fragments(kept)
    pitches = [e.pitch_midi for e in kept]
    return kept, CleanupReport(
        kept=len(kept),
        outliers_removed=outliers,
        fragments_merged=merged,
        fragments_removed=dropped,
        low_range=min(pitches) if pitches else None,
        high_range=max(pitches) if pitches else None,
    )

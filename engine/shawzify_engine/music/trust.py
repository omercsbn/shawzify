"""How much the transcription should be believed.

The compatibility score answers one question honestly: how much of the note set
it was given survived the instrument. It cannot answer the question a listener
actually asks, which is whether the result sounds like the song, because it
never hears the song. Feed it a transcription that missed the music and it will
report a high number with complete confidence.

That is not hypothetical. BFG Division transcribed to 1.8 notes per second over
a track whose riff alone runs at eight to sixteen, and arranging that thin note
set scored 91%. The number was true and the answer was useless.

Be clear about what this module does with that track: nothing. It gets the
"good" label and the general caveat, the same as any other audio. Three attempts
were made to detect it automatically and all three failed, which is the actual
finding here and is why it is written down at this length. Nobody should spend
another afternoon on it without a new idea.

Three detectors, measured on four tracks and abandoned
------------------------------------------------------

The four: Clubbed to Death (dense piano and strings), BFG Division (the one that
matters), a Turkish pop vocal (honest and sparse), and Fuer Elise as a control.

* **Confidence thresholds.** Basic Pitch's confidences are not calibrated
  probabilities. Across the four the mean sat between 0.46 and 0.52 whether the
  result was good or unrecognisable. Any fixed cut-off through that band is
  arbitrary.
* **Note density against the mix's onset density.** Measured on two different
  signals: onsets from the whole mix, notes from an isolated stem. The honest
  vocal looked as sparse as the missed riff, 0.52 against 0.60 of the onset rate.
* **Loudness the notes do not explain, on the stem the transcriber was given.**
  This fixes the mismatch above by using one signal for both, and it comes out
  backwards: the honest vocal scores 33.6% unexplained and the missed riff 13.4%.
  A vocal stem is full of breath, reverb tails and bleed that are loud and are
  not notes, while a distorted riff does get *some* note reported across its loud
  stretches. Re-deriving the onset rate on the stem as well narrows it to 0.97
  against 1.28, which is a 30% margin on four tracks and would put an honest slow
  ballad on the wrong side of any threshold drawn through it.

What is left is what this reports: a transcription with almost nothing in it at
all, or one the transcriber itself was deeply unsure of. Both are rare and both
are certain. For everything in between it says the one thing that is always true
and was never being said, which is that the compatibility score is about the
arrangement and not about the recording.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .events import NoteEvent

#: Deep uncertainty, well below the band real transcriptions occupy.
_SHAKY_CONFIDENCE = 0.32

#: Below this there is not enough pitched material to arrange anything from.
#: Deliberately far below the sparse-but-honest range: BFG Division sits at 1.8
#: and is not caught, because nothing separates it from a slow ballad. See the
#: three abandoned detectors above before moving this number.
_EMPTY_NOTES_PER_SECOND = 0.3


@dataclass(frozen=True)
class TranscriptionTrust:
    """Whether the notes are worth arranging, separately from how well we did."""

    confidence: float
    notes_per_second: float
    label: str

    @property
    def certain(self) -> bool:
        return self.label == "good"

    def to_dict(self) -> dict[str, float | str]:
        return {
            "confidence": round(self.confidence, 3),
            "notesPerSecond": round(self.notes_per_second, 2),
            "label": self.label,
        }

    def note(self) -> str | None:
        """What to tell the user, in terms of what they will hear."""
        if self.label == "exact":
            return None
        if self.label == "empty":
            return (
                "Almost nothing pitched was transcribed from this audio, so the "
                "arrangement cannot resemble it. Percussion, heavy distortion and very "
                "quiet recordings all do this. Try Stem Source 'vocals', or a cleaner "
                "recording."
            )
        if self.label == "uncertain":
            return (
                "The transcriber was unsure of most of these notes, so the arrangement "
                "may be faithful to notes that were not really there."
            )
        return (
            "Compatibility measures how faithfully the arrangement keeps the notes that "
            "were transcribed. It cannot hear the recording, so a high score on audio "
            "means the arrangement is good, not that the transcription was."
        )


def assess_transcription(
    events: list[NoteEvent], duration_seconds: float, *, kind: str = "audio"
) -> TranscriptionTrust:
    """Judge a transcription. MIDI is exact and needs no caveat."""
    density = len(events) / max(duration_seconds, 1.0)

    if kind == "midi":
        return TranscriptionTrust(1.0, density, "exact")

    scores = [e.confidence for e in events if e.confidence is not None]
    confidence = statistics.mean(scores) if scores else 0.0

    if not events or density < _EMPTY_NOTES_PER_SECOND:
        label = "empty"
    elif confidence < _SHAKY_CONFIDENCE:
        label = "uncertain"
    else:
        label = "good"

    return TranscriptionTrust(confidence, density, label)

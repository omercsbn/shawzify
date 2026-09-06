"""How much the transcription should be believed.

The compatibility score answers one question honestly: how much of the note set
it was given survived the instrument. It cannot answer the question a listener
actually asks, which is whether the result sounds like the song, because it
never hears the song. Feed it a transcription that missed the music and it will
report a high number with complete confidence.

That is not hypothetical. BFG Division transcribed to 1.6 notes per second over
a track whose riff alone runs at eight to sixteen, and arranging that
near-empty note set scored 88%. The number was true and the answer was useless.

What is measurable here, and what is not
----------------------------------------

Detecting *that* case automatically was attempted and abandoned, and the reason
is worth writing down so nobody rebuilds it:

* Confidence thresholds do not work. Basic Pitch's confidences are not
  calibrated probabilities; across four very different tracks the mean sat
  between 0.46 and 0.52 whether the result was good or unrecognisable. Any
  fixed cut-off through that band is arbitrary.
* Comparing note density against the audio's own onset density does not work
  either, because they are measured on different signals. Onsets come from the
  whole mix and the notes come from an isolated stem, so an honest monophonic
  vocal transcription looks just as "sparse" as a guitar riff that was missed:
  0.52 and 0.60 of the onset rate respectively.

So this reports what it can stand behind -- a transcription with almost nothing
in it, or one the transcriber itself was deeply unsure of -- and otherwise says
the one thing that is always true and was never being said: the compatibility
score is about the arrangement, not about the recording.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .events import NoteEvent

#: Deep uncertainty, well below the band real transcriptions occupy.
_SHAKY_CONFIDENCE = 0.32

#: Below this there is not enough pitched material to arrange anything from.
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

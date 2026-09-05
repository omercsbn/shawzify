"""Typed errors that carry a human-readable message plus technical detail.

The UI shows ``message``; ``technical`` goes behind a "Technical Details"
disclosure and into the log. Never raise a bare exception across the engine
boundary -- ``ShawzifyError.wrap`` exists for that.
"""

from __future__ import annotations

import traceback


class ShawzifyError(Exception):
    """Base class for every error the engine reports to a user."""

    code = "shawzify_error"
    #: Short, non-alarming sentence for the UI.
    default_message = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        technical: str | None = None,
        hint: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.hint = hint
        if technical is None and cause is not None:
            technical = "".join(
                traceback.format_exception(type(cause), cause, cause.__traceback__)
            ).strip()
        self.technical = technical
        super().__init__(self.message)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "technical": self.technical,
        }

    @classmethod
    def wrap(cls, exc: BaseException, message: str | None = None) -> ShawzifyError:
        if isinstance(exc, ShawzifyError):
            return exc
        return cls(message, cause=exc)


class UnsupportedFormatError(ShawzifyError):
    code = "unsupported_format"
    default_message = "SHAWZIFY does not recognise that file format."


class AudioDecodeError(ShawzifyError):
    code = "audio_decode_failed"
    default_message = "That audio file could not be read. It may be corrupt or incomplete."


class FFmpegMissingError(ShawzifyError):
    code = "ffmpeg_missing"
    default_message = "FFmpeg is not available, so compressed audio cannot be decoded."


class MidiParseError(ShawzifyError):
    code = "midi_parse_failed"
    default_message = "That MIDI file could not be read."


class SongCodeError(ShawzifyError):
    code = "song_code_invalid"
    default_message = "That Shawzin song code is not valid."


class InstrumentConstraintError(ShawzifyError):
    code = "instrument_constraint"
    default_message = "The arrangement contains something the Shawzin cannot play."


class TranscriptionError(ShawzifyError):
    code = "transcription_failed"
    default_message = "SHAWZIFY could not transcribe notes from that audio."


class StemSeparationError(ShawzifyError):
    code = "stem_separation_failed"
    default_message = "Stem separation failed. SHAWZIFY will use the full mix instead."


class ModelUnavailableError(ShawzifyError):
    code = "model_unavailable"
    default_message = "A required model is not installed."


class CancelledError(ShawzifyError):
    code = "cancelled"
    default_message = "The operation was cancelled."


class LivePlaybackError(ShawzifyError):
    code = "live_playback"
    default_message = "Live playback could not start."


class UnsafePathError(ShawzifyError):
    code = "unsafe_path"
    default_message = "That file path is not allowed."

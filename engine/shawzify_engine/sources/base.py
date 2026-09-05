"""Where audio comes from.

SHAWZIFY's primary input has always been a local file. Providers add other
routes to the *same* place: a local audio file on disk that the normal pipeline
then decodes. Nothing downstream of ``fetch()`` knows or cares which provider
produced the file.

Two rules apply to every provider:

* **Optional.** A provider that cannot run reports ``available() == False`` with
  a reason. The app disables the route and explains why; it never breaks.
* **Local.** Whatever is fetched lands in the user's own cache directory and is
  never uploaded anywhere.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ProgressFn = Callable[[float, str], None]

#: Characters that are unsafe in a filename on Windows, plus control characters.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(text: str, *, max_length: int = 80) -> str:
    """Turn an untrusted title into something safe to use as a filename."""
    cleaned = _UNSAFE.sub("_", text).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "track"
    return cleaned[:max_length]


@dataclass
class TrackReference:
    """What a provider knows about a track before any audio exists.

    Everything here is metadata. The duration in particular is load-bearing:
    it is how SHAWZIFY checks that a resolved audio source is actually the
    track that was asked for, rather than a remix, a live version or an hour
    long loop of it.
    """

    title: str
    artist: str = ""
    album: str = ""
    duration_seconds: float | None = None
    provider: str = "unknown"
    source_id: str = ""
    url: str = ""
    artwork_url: str | None = None
    isrc: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return (self.artist + " - " + self.title).strip(" -") if self.artist else self.title

    @property
    def search_query(self) -> str:
        """A query likely to find this exact recording on a video service."""
        parts = [p for p in (self.artist, self.title) if p]
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "durationSeconds": self.duration_seconds,
            "provider": self.provider,
            "sourceId": self.source_id,
            "url": self.url,
            "artworkUrl": self.artwork_url,
            "isrc": self.isrc,
            "display": self.display,
            "extra": self.extra,
        }


@dataclass
class FetchResult:
    """A local audio file, plus how confident we are it is the right one."""

    path: Path
    reference: TrackReference
    #: 0..1. Below ~0.6 the UI should say the match is uncertain.
    match_confidence: float = 1.0
    match_reason: str = ""
    cached: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "reference": self.reference.to_dict(),
            "matchConfidence": round(self.match_confidence, 3),
            "matchReason": self.match_reason,
            "cached": self.cached,
            "warnings": self.warnings,
        }


class AudioSourceProvider(ABC):
    """Turns some identifier into a local audio file."""

    id: str = "base"
    name: str = "Source"
    #: Whether this provider needs the network.
    online: bool = False

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """``(usable, reason)``. The reason is shown when it is not usable."""

    @abstractmethod
    def handles(self, target: str) -> bool:
        """Whether this provider recognises ``target`` as its own."""

    @abstractmethod
    def resolve(self, target: str) -> TrackReference:
        """Metadata only, no download. Cheap enough to call while typing."""

    @abstractmethod
    def fetch(self, target: str, *, progress: ProgressFn | None = None) -> FetchResult:
        """Produce a local audio file for ``target``."""

    def describe(self) -> dict[str, Any]:
        usable, reason = self.available()
        return {
            "id": self.id,
            "name": self.name,
            "online": self.online,
            "available": usable,
            "detail": reason,
        }


def duration_match_confidence(
    expected: float | None, actual: float | None, *, tolerance: float = 5.0
) -> tuple[float, str]:
    """How well two durations agree, and a sentence explaining the verdict.

    This is the main defence against fetching the wrong recording: a remix, an
    extended edit or a "1 hour version" will not match the reference duration.
    """
    if expected is None or actual is None:
        return (0.75, "Duration could not be checked.")
    delta = abs(expected - actual)
    if delta <= tolerance:
        return (1.0, "Duration matches within " + str(int(delta)) + "s.")
    if delta <= tolerance * 3:
        return (
            0.7,
            "Duration is " + str(int(delta)) + "s off; this may be a different edit.",
        )
    if actual > expected * 3:
        return (
            0.1,
            "The source is far longer than the track. This looks like a compilation "
            "or an extended loop rather than the song.",
        )
    return (
        0.3,
        "Duration is " + str(int(delta)) + "s off. This is probably a different "
        "version of the track.",
    )

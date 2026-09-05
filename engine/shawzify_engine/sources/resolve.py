"""Turning "whatever the user pasted" into a local audio file.

The interesting case is Spotify: it knows exactly what the track is but cannot
supply audio, while YouTube can supply audio but is full of remixes, covers,
live versions and hour-long loops. Putting them together gives both -- an exact
reference to match against, and something to actually listen to.

Candidates are scored on duration agreement first (the strongest signal that
two recordings are the same one) and then on title and artist agreement, with
explicit penalties for the words that mark a different recording. The chosen
match and its confidence are always reported; SHAWZIFY never silently
substitutes a different song.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ..common.cache import Cache
from ..common.errors import ShawzifyError, UnsupportedFormatError
from ..common.safety import classify_input, resolve_input_path
from .base import (
    AudioSourceProvider,
    ProgressFn,
    TrackReference,
    duration_match_confidence,
)
from .local import LocalFileProvider
from .spotify import SpotifyProvider
from .youtube import YouTubeProvider

#: Words that usually mean "not the recording you asked for". Weighted, because
#: "remix" in a candidate for a track that is itself a remix should not be fatal.
_VARIANT_PENALTIES: dict[str, float] = {
    "live": 0.35,
    "cover": 0.45,
    "remix": 0.30,
    "karaoke": 0.55,
    "instrumental": 0.25,
    "acoustic": 0.20,
    "sped up": 0.35,
    "slowed": 0.35,
    "nightcore": 0.5,
    "8d": 0.4,
    "reverb": 0.25,
    "loop": 0.5,
    "1 hour": 0.8,
    "10 hours": 0.9,
    "full album": 0.8,
    "mix": 0.15,
    "mashup": 0.5,
    "tutorial": 0.6,
    "reaction": 0.8,
}

#: Words that make a candidate *more* likely to be the studio recording.
_BONUS_TERMS: dict[str, float] = {
    "official audio": 0.12,
    "official video": 0.08,
    "official music video": 0.08,
    "audio": 0.05,
    "topic": 0.15,  # YouTube's auto-generated artist channels
}

_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")


def _normalise(text: str) -> str:
    """For comparing titles: bracketed decoration is noise here."""
    lowered = (text or "").lower()
    lowered = _BRACKETS.sub(" ", lowered)
    lowered = _PUNCTUATION.sub(" ", lowered)
    return " ".join(lowered.split())


def _flatten(text: str) -> str:
    """For spotting variant markers: keep the brackets' contents.

    "Photograph [1 hour]" and "Song (Live)" put the very words that identify a
    wrong recording inside brackets, so the marker search must not strip them.
    """
    lowered = (text or "").lower()
    lowered = _PUNCTUATION.sub(" ", lowered)
    return " ".join(lowered.split())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


@dataclass
class Candidate:
    reference: TrackReference
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference.to_dict(),
            "score": round(self.score, 3),
            "reasons": self.reasons,
        }


def score_candidate(expected: TrackReference, candidate: TrackReference) -> Candidate:
    """How likely ``candidate`` is to be the same recording as ``expected``."""
    reasons: list[str] = []

    duration_score, duration_reason = duration_match_confidence(
        expected.duration_seconds, candidate.duration_seconds, tolerance=4.0
    )
    reasons.append(duration_reason)

    title_score = _similarity(expected.title, candidate.title)
    haystack = _flatten(
        candidate.title + " " + candidate.artist + " " + str(candidate.extra.get("uploader", ""))
    )
    expected_blob = _flatten(expected.title + " " + expected.artist)

    # A candidate whose *title* contains the expected title counts as a match
    # even when the rest of the title is decorated with channel boilerplate.
    if _normalise(expected.title) and _normalise(expected.title) in _normalise(candidate.title):
        title_score = max(title_score, 0.92)
        reasons.append("Title contains the expected track name.")

    artist_score = _similarity(expected.artist, candidate.artist) if expected.artist else 0.5
    if expected.artist and _normalise(expected.artist) in haystack:
        artist_score = max(artist_score, 0.9)
        reasons.append("Artist name appears in the video.")

    penalty = 0.0
    for term, weight in _VARIANT_PENALTIES.items():
        if term in haystack and term not in expected_blob:
            penalty += weight
            reasons.append("Looks like a " + term + " version.")
    bonus = 0.0
    for term, weight in _BONUS_TERMS.items():
        if term in haystack:
            bonus += weight

    score = (
        0.50 * duration_score
        + 0.30 * title_score
        + 0.20 * artist_score
        + min(0.2, bonus)
        - min(0.9, penalty)
    )
    # A gross duration mismatch is decisive. An hour-long upload of a
    # three-minute song matches the title and the artist perfectly, so without
    # this cap the text agreement would carry it to a respectable score.
    score = min(score, 0.15 + 0.85 * duration_score)
    return Candidate(candidate, max(0.0, min(1.0, score)), reasons)


@dataclass
class ResolvedSource:
    """The outcome of resolving whatever the user pasted."""

    kind: str  # "local" | "youtube" | "spotify"
    reference: TrackReference
    #: Only set once audio actually exists on disk.
    path: Path | None = None
    match_confidence: float = 1.0
    match_reason: str = ""
    alternatives: list[Candidate] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.alternatives is None:
            self.alternatives = []
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reference": self.reference.to_dict(),
            "path": str(self.path) if self.path else None,
            "matchConfidence": round(self.match_confidence, 3),
            "matchReason": self.match_reason,
            "alternatives": [c.to_dict() for c in self.alternatives],
            "warnings": self.warnings,
        }


class SourceResolver:
    """The one entry point for "here is a thing, give me audio"."""

    def __init__(self, cache: Cache | None = None) -> None:
        self.cache = cache or Cache()
        self.local = LocalFileProvider()
        self.youtube = YouTubeProvider(self.cache)
        self.spotify = SpotifyProvider()

    @property
    def providers(self) -> list[AudioSourceProvider]:
        return [self.local, self.youtube, self.spotify]

    def describe(self) -> list[dict[str, Any]]:
        return [p.describe() for p in self.providers]

    def provider_for(self, target: str) -> AudioSourceProvider:
        for provider in (self.spotify, self.youtube, self.local):
            if provider.handles(target):
                return provider
        raise UnsupportedFormatError(
            "SHAWZIFY does not recognise that input.",
            hint="Give it a file path, a YouTube link or a Spotify link.",
        )

    # -- metadata only --------------------------------------------------

    def preview(self, target: str) -> ResolvedSource:
        """Identify the target without downloading anything."""
        provider = self.provider_for(target)
        reference = provider.resolve(target)
        source = ResolvedSource(kind=provider.id, reference=reference)
        if provider is self.local:
            source.path = Path(reference.extra["path"])
        elif provider is self.spotify:
            source.warnings.append(
                "Spotify cannot provide audio. SHAWZIFY will look for this "
                "recording on YouTube."
            )
        return source

    # -- the whole job --------------------------------------------------

    def fetch(
        self,
        target: str,
        *,
        progress: ProgressFn | None = None,
        allow_search: bool = True,
        candidate_index: int = 0,
    ) -> ResolvedSource:
        """Produce local audio for ``target``, whatever kind of thing it is."""
        provider = self.provider_for(target)

        if provider is self.local:
            result = self.local.fetch(target, progress=progress)
            return ResolvedSource(
                kind="local",
                reference=result.reference,
                path=result.path,
                match_confidence=1.0,
                match_reason="Local file.",
            )

        if provider is self.youtube:
            result = self.youtube.fetch(target, progress=progress)
            return ResolvedSource(
                kind="youtube",
                reference=result.reference,
                path=result.path,
                match_confidence=result.match_confidence,
                match_reason=result.match_reason,
                warnings=list(result.warnings),
            )

        # Spotify: metadata from Spotify, audio from YouTube.
        reference = self.spotify.resolve(target)
        if not allow_search:
            raise ShawzifyError(
                "Spotify does not allow applications to download audio.",
                hint="Enable the YouTube lookup, or choose a local copy of the file.",
            )
        return self.fetch_by_reference(
            reference, progress=progress, candidate_index=candidate_index
        )

    def fetch_by_reference(
        self,
        reference: TrackReference,
        *,
        progress: ProgressFn | None = None,
        candidate_index: int = 0,
    ) -> ResolvedSource:
        """Find and download the audio for a known track."""
        usable, reason = self.youtube.available()
        if not usable:
            raise ShawzifyError(
                "SHAWZIFY knows the track but has no way to fetch the audio.",
                hint=reason + " Or point SHAWZIFY at your own copy of the file.",
            )

        if progress:
            progress(0.05, "Searching for " + reference.display)
        found = self.youtube.search(reference.search_query, limit=6)
        if not found:
            raise ShawzifyError(
                "SHAWZIFY could not find “" + reference.display + "” to listen to.",
                hint="Try a local copy of the file instead.",
            )

        ranked = sorted(
            (score_candidate(reference, c) for c in found),
            key=lambda c: -c.score,
        )
        index = max(0, min(candidate_index, len(ranked) - 1))
        chosen = ranked[index]

        warnings: list[str] = []
        if chosen.score < 0.6:
            warnings.append(
                "The best match for “"
                + reference.display
                + "” is uncertain. Check the result, or pick another candidate."
            )

        if progress:
            progress(0.15, "Best match: " + chosen.reference.display)
        result = self.youtube.fetch(
            chosen.reference.url or chosen.reference.source_id,
            progress=lambda f, m="": progress(0.15 + 0.85 * f, m) if progress else None,
            expected=reference,
        )

        # Keep the canonical metadata; the audio is just the carrier.
        merged = TrackReference(
            title=reference.title,
            artist=reference.artist,
            album=reference.album,
            duration_seconds=reference.duration_seconds or result.reference.duration_seconds,
            provider=reference.provider,
            source_id=reference.source_id,
            url=reference.url,
            artwork_url=reference.artwork_url or result.reference.artwork_url,
            isrc=reference.isrc,
            extra={**reference.extra, "audioFrom": result.reference.to_dict()},
        )
        return ResolvedSource(
            kind=reference.provider,
            reference=merged,
            path=result.path,
            match_confidence=chosen.score,
            match_reason=" ".join(chosen.reasons),
            alternatives=ranked,
            warnings=warnings + list(result.warnings),
        )

    def search(self, query: str, limit: int = 6) -> list[Candidate]:
        """Free-text search across whatever providers are usable."""
        out: list[Candidate] = []
        if self.spotify.available()[0]:
            for reference in self.spotify.search(query, limit=limit):
                out.append(Candidate(reference, 1.0, ["From Spotify."]))
        if self.youtube.available()[0]:
            for reference in self.youtube.search(query, limit=limit):
                out.append(Candidate(reference, 0.9, ["From YouTube."]))
        return out


def looks_like_url(target: str) -> bool:
    return bool(re.match(r"^(https?://|spotify:)", (target or "").strip(), re.I))


def is_supported_local_file(target: str) -> bool:
    try:
        classify_input(resolve_input_path(target))
        return True
    except Exception:  # noqa: BLE001
        return False

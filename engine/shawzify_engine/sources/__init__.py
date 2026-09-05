"""Audio source providers: local files, YouTube, Spotify metadata."""

from .base import AudioSourceProvider, FetchResult, TrackReference
from .local import LocalFileProvider
from .resolve import Candidate, ResolvedSource, SourceResolver, looks_like_url, score_candidate
from .spotify import SpotifyCredentials, SpotifyProvider
from .youtube import YouTubeProvider

__all__ = [
    "AudioSourceProvider",
    "TrackReference",
    "FetchResult",
    "LocalFileProvider",
    "YouTubeProvider",
    "SpotifyProvider",
    "SpotifyCredentials",
    "SourceResolver",
    "ResolvedSource",
    "Candidate",
    "score_candidate",
    "looks_like_url",
]

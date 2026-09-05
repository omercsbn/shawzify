"""YouTube (and anything else yt-dlp handles) as an audio source.

yt-dlp is an optional dependency and is not bundled: it is a fast-moving tool
that users are better off updating themselves, and SHAWZIFY works fully without
it. When it is absent the route is disabled with an explanation rather than
failing at the point of use.

Downloads land in the user's own cache, keyed by video id, and are never
uploaded anywhere. Nothing here bypasses any access control -- it fetches what
a browser would fetch from a public page.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common.cache import Cache
from ..common.errors import ShawzifyError
from ..common.logging import get_logger
from ..common.safety import sanitize_metadata_text
from .base import (
    AudioSourceProvider,
    FetchResult,
    ProgressFn,
    TrackReference,
    duration_match_confidence,
    safe_filename,
)

#: Recognised URL shapes. Anything else is left to another provider.
_URL_PATTERNS = (
    re.compile(r"^https?://(www\.|m\.|music\.)?youtube\.com/watch\?", re.I),
    re.compile(r"^https?://(www\.)?youtu\.be/", re.I),
    re.compile(r"^https?://(www\.|m\.|music\.)?youtube\.com/shorts/", re.I),
)
_ID_PATTERN = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")

#: Refuse anything longer than this: a two-hour mix is never the intended input
#: and downloading it would waste a lot of the user's time and disk.
MAX_DURATION_SECONDS = 20 * 60


class YouTubeProvider(AudioSourceProvider):
    id = "youtube"
    name = "YouTube"
    online = True

    def __init__(self, cache: Cache | None = None) -> None:
        self.cache = cache or Cache()
        self.log = get_logger("sources")

    # -- availability ---------------------------------------------------

    def available(self) -> tuple[bool, str]:
        try:
            import yt_dlp

            return (True, "yt-dlp " + str(yt_dlp.version.__version__))
        except Exception:  # noqa: BLE001
            return (
                False,
                "yt-dlp is not installed. Install it with "
                "'engine/.venv/Scripts/python.exe -m pip install -U yt-dlp'.",
            )

    def handles(self, target: str) -> bool:
        text = (target or "").strip()
        return any(p.match(text) for p in _URL_PATTERNS)

    # -- internals ------------------------------------------------------

    def _require(self):
        usable, reason = self.available()
        if not usable:
            raise ShawzifyError(
                "YouTube support is not installed.",
                hint=reason,
            )
        import yt_dlp

        return yt_dlp

    @staticmethod
    def video_id(target: str) -> str:
        match = _ID_PATTERN.search(target or "")
        if match:
            return match.group(1)
        # A bare id is accepted too, which makes the CLI pleasant.
        text = (target or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
            return text
        raise ShawzifyError(
            "That does not look like a YouTube link.",
            technical="unparsable target: " + repr(target[:120]),
        )

    def _options(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            # Never let yt-dlp read stdin: as a sidecar ours is a pipe.
            "noninteractive": True,
            "nocheckcertificate": False,
            "retries": 3,
            "socket_timeout": 30,
            # Prefer m4a, but take whatever audio-only stream exists. No
            # re-encoding: SHAWZIFY's own FFmpeg decodes the container later,
            # which is faster and avoids depending on yt-dlp finding ffprobe.
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "logger": _QuietLogger(self.log),
        }
        if extra:
            options.update(extra)
        return options

    def _reference_from_info(self, info: dict[str, Any]) -> TrackReference:
        # yt-dlp exposes music metadata for YouTube Music entries; fall back to
        # the uploader and title, which is what a plain video has.
        title = sanitize_metadata_text(info.get("track") or info.get("title") or "Unknown")
        artist = sanitize_metadata_text(
            info.get("artist") or info.get("creator") or info.get("uploader") or ""
        )
        title = _strip_leading_artist(title, artist)
        return TrackReference(
            title=title,
            artist=artist,
            album=sanitize_metadata_text(info.get("album") or ""),
            duration_seconds=float(info["duration"]) if info.get("duration") else None,
            provider=self.id,
            source_id=str(info.get("id") or ""),
            url=str(info.get("webpage_url") or info.get("original_url") or ""),
            artwork_url=info.get("thumbnail"),
            extra={
                "uploader": sanitize_metadata_text(info.get("uploader") or ""),
                "viewCount": info.get("view_count"),
            },
        )

    # -- public ---------------------------------------------------------

    def resolve(self, target: str, *, use_cache: bool = True) -> TrackReference:
        video_id = self.video_id(target)
        url = "https://www.youtube.com/watch?v=" + video_id
        # Check the cache before importing yt-dlp: the import alone takes a
        # couple of seconds, which would make a cached lookup feel slow.
        if use_cache:
            stored = self.cache.get_json("youtube-meta", video_id)
            if stored:
                return TrackReference(
                    title=stored["title"],
                    artist=stored.get("artist", ""),
                    album=stored.get("album", ""),
                    duration_seconds=stored.get("durationSeconds"),
                    provider=self.id,
                    source_id=stored.get("sourceId", video_id),
                    url=stored.get("url", url),
                    artwork_url=stored.get("artworkUrl"),
                    extra=stored.get("extra") or {},
                )
        yt_dlp = self._require()
        try:
            with yt_dlp.YoutubeDL(self._options({"skip_download": True})) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            raise ShawzifyError(
                "SHAWZIFY could not read that YouTube link.",
                hint="Check the link, and that yt-dlp is up to date.",
                cause=exc,
            ) from exc
        if not isinstance(info, dict):
            raise ShawzifyError("That YouTube link did not return a single video.")
        if info.get("_type") == "playlist":
            raise ShawzifyError(
                "That is a playlist link. Paste a link to a single video.",
            )
        reference = self._reference_from_info(info)
        self.cache.put_json("youtube-meta", video_id, reference.to_dict())
        return reference

    def search(self, query: str, limit: int = 5) -> list[TrackReference]:
        """Find candidate videos for a text query, best first."""
        yt_dlp = self._require()
        try:
            with yt_dlp.YoutubeDL(self._options({"skip_download": True, "extract_flat": False})) as ydl:
                info = ydl.extract_info("ytsearch" + str(int(limit)) + ":" + query, download=False)
        except Exception as exc:  # noqa: BLE001
            raise ShawzifyError(
                "SHAWZIFY could not search YouTube.", cause=exc
            ) from exc
        entries = (info or {}).get("entries") or []
        return [self._reference_from_info(e) for e in entries if isinstance(e, dict)]

    def fetch(
        self,
        target: str,
        *,
        progress: ProgressFn | None = None,
        expected: TrackReference | None = None,
    ) -> FetchResult:
        yt_dlp = self._require()
        video_id = self.video_id(target) if not target.startswith("http") else self.video_id(target)
        url = "https://www.youtube.com/watch?v=" + video_id

        if progress:
            progress(0.05, "Reading video details")
        reference = self.resolve(url)

        if reference.duration_seconds and reference.duration_seconds > MAX_DURATION_SECONDS:
            raise ShawzifyError(
                "That video is "
                + str(int(reference.duration_seconds // 60))
                + " minutes long. SHAWZIFY only fetches videos up to "
                + str(MAX_DURATION_SECONDS // 60)
                + " minutes.",
                hint="Link a single song rather than a mix or a full album.",
            )

        cached = self.cache.get_dir("youtube", video_id)
        if cached is not None:
            existing = _first_audio_file(cached)
            if existing is not None:
                self.log.event("youtube.cache_hit", videoId=video_id)
                if progress:
                    progress(1.0, "Using the cached download")
                confidence, reason = self._confidence(reference, expected)
                return FetchResult(existing, reference, confidence, reason, cached=True)

        target_dir = self.cache.begin_dir("youtube", video_id)
        stem = safe_filename(reference.display) or video_id

        def hook(status: dict[str, Any]) -> None:
            if not progress:
                return
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                done = status.get("downloaded_bytes") or 0
                fraction = (done / total) if total else 0.0
                progress(0.1 + 0.75 * min(1.0, fraction), "Downloading audio")
            elif status.get("status") == "finished":
                progress(0.9, "Converting audio")

        options = self._options(
            {
                "outtmpl": str(target_dir / (stem + ".%(ext)s")),
                "progress_hooks": [hook],
            }
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            raise ShawzifyError(
                "The download failed.",
                hint="The video may be private, region-locked or age-restricted. "
                "Updating yt-dlp often fixes extraction failures.",
                cause=exc,
            ) from exc

        produced = _first_audio_file(target_dir)
        if produced is None:
            raise ShawzifyError(
                "The download finished but produced no audio file.",
                technical="empty cache dir: " + str(target_dir),
            )
        self.cache.commit_dir("youtube", video_id)
        if progress:
            progress(1.0, "Downloaded " + reference.display)

        confidence, reason = self._confidence(reference, expected)
        return FetchResult(produced, reference, confidence, reason)

    def _confidence(
        self, actual: TrackReference, expected: TrackReference | None
    ) -> tuple[float, str]:
        if expected is None:
            return (1.0, "Fetched the linked video directly.")
        return duration_match_confidence(expected.duration_seconds, actual.duration_seconds)


class _QuietLogger:
    """Route yt-dlp's chatter into the structured log instead of stdout."""

    def __init__(self, log) -> None:
        self._log = log

    def debug(self, message: str) -> None:
        if message.startswith("[debug] "):
            return
        self._log.event("yt_dlp", message=message[:400])

    def info(self, message: str) -> None:
        self._log.event("yt_dlp", message=message[:400])

    def warning(self, message: str) -> None:
        self._log.warn("yt_dlp", message=message[:400])

    def error(self, message: str) -> None:
        self._log.warn("yt_dlp.error", message=message[:400])


def _strip_leading_artist(title: str, artist: str) -> str:
    """Drop a redundant "Artist - " prefix so titles do not read "X - X - Song"."""
    if not artist:
        return title
    prefix = artist.strip().lower()
    lowered = title.strip().lower()
    for separator in (" - ", " – ", " — ", ": ", " | "):
        if lowered.startswith(prefix + separator):
            return title.strip()[len(artist) + len(separator) :].strip()
    return title


_AUDIO_SUFFIXES = (".m4a", ".mp3", ".opus", ".webm", ".ogg", ".wav", ".flac", ".aac")


def _first_audio_file(directory: Path) -> Path | None:
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES:
            return path
    return None

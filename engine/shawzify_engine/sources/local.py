"""A file already on disk. The primary input, and the one that always works."""

from __future__ import annotations

from pathlib import Path

from ..common.safety import classify_input, resolve_input_path, sanitize_metadata_text
from .base import AudioSourceProvider, FetchResult, ProgressFn, TrackReference


class LocalFileProvider(AudioSourceProvider):
    id = "local"
    name = "Local file"
    online = False

    def available(self) -> tuple[bool, str]:
        return (True, "Always available.")

    def handles(self, target: str) -> bool:
        text = (target or "").strip()
        if not text or text.lower().startswith(("http://", "https://", "spotify:")):
            return False
        try:
            classify_input(resolve_input_path(text))
            return True
        except Exception:  # noqa: BLE001 - "not a file we handle" is the answer
            return False

    def resolve(self, target: str) -> TrackReference:
        path = resolve_input_path(target)
        kind = classify_input(path)
        duration: float | None = None
        title = sanitize_metadata_text(path.stem, max_length=120)
        artist = ""

        if kind == "audio":
            # Tags are nicer than a filename when they exist, but a missing or
            # unreadable tag must never stop the file being usable.
            try:
                from ..audio.decode import _probe_metadata

                _codec, _bitrate, tag_title, tag_artist = _probe_metadata(path)
                title = tag_title or title
                artist = tag_artist or ""
            except Exception:  # noqa: BLE001
                pass

        return TrackReference(
            title=title,
            artist=artist,
            duration_seconds=duration,
            provider=self.id,
            source_id=path.name,
            url=path.as_uri(),
            extra={"path": str(path), "kind": kind},
        )

    def fetch(self, target: str, *, progress: ProgressFn | None = None) -> FetchResult:
        reference = self.resolve(target)
        if progress:
            progress(1.0, "Using " + reference.title)
        return FetchResult(
            path=Path(reference.extra["path"]),
            reference=reference,
            match_confidence=1.0,
            match_reason="Local file.",
            cached=True,
        )

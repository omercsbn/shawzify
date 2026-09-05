"""Spotify as a *metadata* source.

Spotify does not let applications download audio, and since 27 November 2024 it
also no longer exposes ``audio-features`` or ``audio-analysis`` to newly
registered apps -- so there is no honest way to build "Spotify in, notes out"
directly on their API, and no point pretending otherwise.

What Spotify is genuinely good for is knowing *exactly* what a track is: the
canonical title, artist, album, duration and ISRC. SHAWZIFY uses that to
identify the track and then resolves playable audio elsewhere, checking the
duration to make sure it found the same recording rather than a remix.

SHAWZIFY does its own DSP anyway, which is the point of the product -- the lost
``audio-features`` endpoint would have told us the tempo and key of a track we
are about to measure ourselves.

Credentials are the user's own Spotify app (client id and secret from
developer.spotify.com), stored locally. Without them this provider reports
itself unavailable and explains how to enable it.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common.errors import ShawzifyError
from ..common.logging import get_logger
from ..common.paths import app_dir
from ..common.safety import sanitize_metadata_text
from .base import AudioSourceProvider, FetchResult, ProgressFn, TrackReference

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"

_URL_PATTERN = re.compile(
    r"^https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)", re.I
)
_URI_PATTERN = re.compile(r"^spotify:(track|album|playlist):([A-Za-z0-9]+)$", re.I)


@dataclass
class SpotifyCredentials:
    client_id: str = ""
    client_secret: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @staticmethod
    def path() -> Path:
        return Path(app_dir()) / "spotify.json"

    @staticmethod
    def load() -> SpotifyCredentials:
        import os

        # Environment wins, so CI and power users never have to write the file.
        env = SpotifyCredentials(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
            client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        )
        if env.configured:
            return env
        target = SpotifyCredentials.path()
        if not target.exists():
            return SpotifyCredentials()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return SpotifyCredentials(
                client_id=str(data.get("clientId", "")),
                client_secret=str(data.get("clientSecret", "")),
            )
        except (OSError, json.JSONDecodeError, TypeError):
            return SpotifyCredentials()

    def save(self) -> Path:
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"clientId": self.client_id, "clientSecret": self.client_secret}, indent=2),
            encoding="utf-8",
        )
        return target


class SpotifyProvider(AudioSourceProvider):
    id = "spotify"
    name = "Spotify"
    online = True

    def __init__(self, credentials: SpotifyCredentials | None = None) -> None:
        self.credentials = credentials or SpotifyCredentials.load()
        self.log = get_logger("sources")
        self._token: str | None = None
        self._token_expires = 0.0

    # -- availability ---------------------------------------------------

    def available(self) -> tuple[bool, str]:
        try:
            import requests  # noqa: F401
        except Exception:  # noqa: BLE001
            return (False, "The 'requests' package is not installed.")
        if not self.credentials.configured:
            return (
                False,
                "No Spotify app credentials. Create an app at "
                "developer.spotify.com/dashboard and add the client id and secret "
                "in Settings, or set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
            )
        return (True, "Client credentials configured (metadata only).")

    def handles(self, target: str) -> bool:
        text = (target or "").strip()
        return bool(_URL_PATTERN.match(text) or _URI_PATTERN.match(text))

    # -- auth -----------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 30:
            return self._token
        usable, reason = self.available()
        if not usable:
            raise ShawzifyError("Spotify is not set up.", hint=reason)
        import requests

        basic = base64.b64encode(
            (self.credentials.client_id + ":" + self.credentials.client_secret).encode("utf-8")
        ).decode("ascii")
        try:
            response = requests.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": "Basic " + basic},
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            raise ShawzifyError("SHAWZIFY could not reach Spotify.", cause=exc) from exc
        if response.status_code != 200:
            raise ShawzifyError(
                "Spotify rejected those credentials.",
                hint="Check the client id and secret in Settings.",
                technical=response.text[:400],
            )
        payload = response.json()
        self._token = str(payload["access_token"])
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import requests

        try:
            response = requests.get(
                API + path,
                params=params or {},
                headers={"Authorization": "Bearer " + self._access_token()},
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            raise ShawzifyError("SHAWZIFY could not reach Spotify.", cause=exc) from exc
        if response.status_code == 404:
            raise ShawzifyError("Spotify does not have anything at that link.")
        if response.status_code == 429:
            raise ShawzifyError(
                "Spotify is rate-limiting this app. Wait a moment and try again.",
            )
        if response.status_code == 403:
            raise ShawzifyError(
                "Spotify refused that request.",
                hint="Since November 2024, new apps cannot use the audio-features "
                "and audio-analysis endpoints. SHAWZIFY only needs track metadata, "
                "so check the app's credentials rather than its quota.",
                technical=response.text[:400],
            )
        if response.status_code != 200:
            raise ShawzifyError(
                "Spotify returned an unexpected response.",
                technical=str(response.status_code) + " " + response.text[:400],
            )
        return response.json()

    # -- parsing --------------------------------------------------------

    @staticmethod
    def parse(target: str) -> tuple[str, str]:
        """``(kind, id)`` from a Spotify URL or URI."""
        text = (target or "").strip()
        match = _URL_PATTERN.match(text) or _URI_PATTERN.match(text)
        if not match:
            raise ShawzifyError(
                "That does not look like a Spotify link.",
                technical="unparsable target: " + repr(text[:120]),
            )
        return (match.group(1).lower(), match.group(2))

    def _track_reference(self, item: dict[str, Any]) -> TrackReference:
        artists = ", ".join(
            sanitize_metadata_text(a.get("name", "")) for a in item.get("artists", []) if a
        )
        album = item.get("album") or {}
        images = album.get("images") or []
        return TrackReference(
            title=sanitize_metadata_text(item.get("name", "Unknown")),
            artist=artists,
            album=sanitize_metadata_text(album.get("name", "")),
            duration_seconds=(item.get("duration_ms") or 0) / 1000.0 or None,
            provider=self.id,
            source_id=str(item.get("id") or ""),
            url=str((item.get("external_urls") or {}).get("spotify") or ""),
            artwork_url=images[0]["url"] if images else None,
            isrc=(item.get("external_ids") or {}).get("isrc"),
            extra={
                "popularity": item.get("popularity"),
                "explicit": item.get("explicit"),
                "releaseDate": album.get("release_date"),
                "trackNumber": item.get("track_number"),
            },
        )

    # -- public ---------------------------------------------------------

    def resolve(self, target: str) -> TrackReference:
        kind, item_id = self.parse(target)
        if kind != "track":
            references = self.resolve_many(target)
            if not references:
                raise ShawzifyError("That Spotify " + kind + " has no tracks.")
            return references[0]
        return self._track_reference(self._get("/tracks/" + item_id))

    def resolve_many(self, target: str, limit: int = 50) -> list[TrackReference]:
        """Every track behind a link. A track link yields one; a playlist, many."""
        kind, item_id = self.parse(target)
        if kind == "track":
            return [self._track_reference(self._get("/tracks/" + item_id))]
        if kind == "album":
            album = self._get("/albums/" + item_id)
            tracks = (album.get("tracks") or {}).get("items", [])[:limit]
            # Album track objects omit the album, so graft it back on.
            for t in tracks:
                t.setdefault("album", {k: album.get(k) for k in ("name", "images", "release_date")})
            return [self._track_reference(t) for t in tracks if t]
        payload = self._get(
            "/playlists/" + item_id + "/tracks", {"limit": min(limit, 100)}
        )
        out: list[TrackReference] = []
        for entry in payload.get("items", []):
            track = (entry or {}).get("track")
            if isinstance(track, dict) and track.get("id"):
                out.append(self._track_reference(track))
        return out[:limit]

    def search(self, query: str, limit: int = 5) -> list[TrackReference]:
        payload = self._get("/search", {"q": query, "type": "track", "limit": limit})
        items = ((payload.get("tracks") or {}).get("items")) or []
        return [self._track_reference(i) for i in items if i]

    def fetch(self, target: str, *, progress: ProgressFn | None = None) -> FetchResult:
        """Spotify cannot supply audio; this always explains what to do instead."""
        reference = self.resolve(target)
        raise ShawzifyError(
            "Spotify does not allow applications to download audio, so SHAWZIFY "
            "cannot fetch “" + reference.display + "” from Spotify directly.",
            hint="SHAWZIFY read the track details from Spotify. Let it find the "
            "audio on YouTube, or point it at your own copy of the file.",
            technical="spotify id " + reference.source_id,
        )

# Getting music in: YouTube and Spotify

What each service actually permits, what SHAWZIFY does with that, and why the
two are used together rather than either alone.

## Spotify: exact identity, no audio

Spotify's Web API is excellent at saying *what a track is* and refuses to give
you the track. Both halves matter.

### What was removed, and when

On **27 November 2024** Spotify restricted a group of endpoints for any
application registered after that date
([announcement](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)):

| Endpoint | Status for new apps |
| --- | --- |
| `GET /audio-features` | Unavailable |
| `GET /audio-analysis` | Unavailable |
| `GET /recommendations` | Unavailable |
| `GET /artists/{id}/related-artists` | Unavailable |
| `GET /browse/featured-playlists` | Unavailable |
| 30-second `preview_url` | Restricted |
| Algorithmic / editorial playlists | Unavailable |

Apps that already had extended access keep it; everything registered since gets
403. There is no official replacement.

`audio-features` is the one that would have been tempting — it returned tempo,
key, mode, time signature, energy and valence. It is worth being clear that
losing it costs SHAWZIFY almost nothing: **the product measures all of that from
the audio itself**, because it has to transcribe the notes anyway. A tempo
number from an API is no use without the notes it belongs to.

### What still works, and what SHAWZIFY uses

With client-credentials auth (the user's own app, created at
developer.spotify.com/dashboard):

* `GET /tracks/{id}` — name, artists, album, **duration**, ISRC, artwork
* `GET /albums/{id}` and `GET /playlists/{id}/tracks`
* `GET /search`

SHAWZIFY uses exactly this and nothing else. The duration in particular is
load-bearing: it is how a resolved recording is checked against the track that
was asked for.

Credentials live in `%LOCALAPPDATA%\Shawzify\spotify.json` or in
`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`. Without them the provider reports
itself unavailable and says how to enable it; nothing else breaks.

`SpotifyProvider.fetch()` never pretends. It raises an error that says Spotify
does not allow applications to download audio, and points at the alternative.

## YouTube: audio, and a lot of near-misses

yt-dlp is an **optional** dependency, deliberately not bundled: it is a
fast-moving tool that breaks and gets fixed on a weekly cadence, and users are
better off running `pip install -U yt-dlp` themselves than waiting for a
SHAWZIFY release. When it is absent the route is disabled with that instruction.

What SHAWZIFY does:

* Reads metadata without downloading, so pasting a link shows what it is first.
* Downloads the best audio-only stream, **without re-encoding** — the container
  goes straight to SHAWZIFY's own FFmpeg. Faster, and it avoids depending on
  yt-dlp finding an `ffprobe` that the bundled FFmpeg does not ship.
* Refuses anything over 20 minutes. A two-hour mix is never the intended input.
* Caches by video id, metadata included, so re-opening a track is instant and
  works offline.

## Putting them together

A Spotify link goes: **metadata from Spotify → search YouTube → verify → download.**

The verification step is the interesting part, because a search for
"Artist - Title" returns the studio version alongside live versions, covers,
karaoke tracks, sped-up edits, "8D audio", and one-hour loops. Each candidate is
scored on:

| Signal | Weight | Why |
| --- | --- | --- |
| Duration agreement | 0.50 | The strongest evidence two recordings are the same one |
| Title similarity | 0.30 | |
| Artist agreement | 0.20 | |
| "official audio", a `- Topic` channel | up to +0.20 | Marks the studio upload |
| "live", "cover", "remix", "1 hour", … | up to −0.90 | Marks a different recording |

Two details make it work in practice:

* **Variant markers are matched against the un-stripped title.** Titles are
  normalised for *comparison* by removing bracketed decoration, but the markers
  live inside exactly those brackets — `Photograph [1 hour]`. Searching the
  stripped text would miss every one of them.
* **A gross duration mismatch caps the total score.** An hour-long upload
  matches title and artist perfectly; without the cap, text agreement alone
  carries it to a respectable score. Both cases are regression-tested.

The chosen match and its confidence are always reported. Below 60% the UI says
the match is uncertain, and `--candidate N` (CLI) picks a different result.

## Legality and scope

* Local files remain the primary input. Every link route is optional and can be
  absent without affecting anything else.
* Nothing here bypasses access control, DRM or authentication. yt-dlp fetches
  what a browser fetches from a public page.
* Downloads land in the user's own cache and are never uploaded anywhere.
* SHAWZIFY exists to transcribe music onto a twelve-note game instrument. Do
  not use it to reproduce or redistribute music you do not have the right to.

## Usage

```powershell
# Straight to a song code
shawzify convert "https://www.youtube.com/watch?v=..." --focus hook

# Spotify: identified by Spotify, heard via YouTube
shawzify convert "https://open.spotify.com/track/..."

# Just the audio
shawzify fetch "https://youtu.be/..." -o song.m4a
shawzify fetch "https://youtu.be/..." --candidate 2   # a different search result
```

In the app, paste a link on the home screen. It identifies the track as you
pause typing, then Convert fetches and arranges it.

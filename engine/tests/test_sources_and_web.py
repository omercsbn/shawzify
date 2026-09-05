"""Audio source providers, song structure, Shawzin recommendation, web server.

Nothing here touches the network. Provider behaviour is tested through its
public surface (routing, parsing, scoring, error messages), and the two
network-dependent providers are exercised with injected metadata rather than
live requests -- a test suite that needs YouTube to be up is not a test suite.
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request

import pytest

from shawzify_engine.common.errors import ShawzifyError, UnsupportedFormatError
from shawzify_engine.music.events import NoteEvent
from shawzify_engine.music.structure import (
    analyze_structure,
    best_window,
    melodic_hook,
    recognizability_weights,
    structure_features,
)
from shawzify_engine.shawzin.recommend import (
    MusicProfile,
    profile_music,
    recommend_shawzin,
)
from shawzify_engine.sources import (
    LocalFileProvider,
    SourceResolver,
    SpotifyProvider,
    TrackReference,
    YouTubeProvider,
    looks_like_url,
    score_candidate,
)
from shawzify_engine.sources.base import duration_match_confidence, safe_filename
from shawzify_engine.sources.spotify import SpotifyCredentials

# -- routing -------------------------------------------------------------


@pytest.mark.parametrize(
    "target,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
        ("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", "spotify"),
        ("https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT", "spotify"),
        ("spotify:track:4cOdK2wGLETKBW3PvgPWqT", "spotify"),
        ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "spotify"),
    ],
)
def test_links_route_to_the_right_provider(target, expected):
    assert SourceResolver().provider_for(target).id == expected


def test_local_files_route_to_the_local_provider(wav_file, melody_audio):
    path = wav_file(melody_audio, 22050)
    assert SourceResolver().provider_for(str(path)).id == "local"


def test_unknown_input_is_refused_clearly():
    with pytest.raises(UnsupportedFormatError) as exc:
        SourceResolver().provider_for("https://example.com/not-a-song")
    assert "file path" in (exc.value.hint or "")


def test_looks_like_url():
    assert looks_like_url("https://youtu.be/x")
    assert looks_like_url("spotify:track:x")
    assert not looks_like_url("C:/music/song.mp3")
    assert not looks_like_url("")


def test_youtube_id_extraction():
    for target, expected in [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ]:
        assert YouTubeProvider.video_id(target) == expected


def test_youtube_id_rejects_nonsense():
    with pytest.raises(ShawzifyError):
        YouTubeProvider.video_id("https://example.com/video")


def test_spotify_link_parsing():
    assert SpotifyProvider.parse("https://open.spotify.com/track/abc123") == ("track", "abc123")
    assert SpotifyProvider.parse("spotify:album:xyz") == ("album", "xyz")
    with pytest.raises(ShawzifyError):
        SpotifyProvider.parse("https://open.spotify.com/artist")


def test_spotify_without_credentials_explains_itself(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    provider = SpotifyProvider(SpotifyCredentials())
    usable, reason = provider.available()
    assert not usable
    assert "developer.spotify.com" in reason


def test_spotify_never_claims_to_download(monkeypatch):
    """Spotify does not allow audio downloads; the error must say so plainly."""
    provider = SpotifyProvider(SpotifyCredentials("id", "secret"))
    monkeypatch.setattr(
        provider, "resolve", lambda target: TrackReference("Song", "Artist", provider="spotify")
    )
    with pytest.raises(ShawzifyError) as exc:
        provider.fetch("https://open.spotify.com/track/abc")
    assert "does not allow" in exc.value.message
    assert "YouTube" in (exc.value.hint or "")


def test_spotify_credentials_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    saved = SpotifyCredentials("my-id", "my-secret")
    saved.save()
    loaded = SpotifyCredentials.load()
    assert loaded.client_id == "my-id"
    assert loaded.configured


def test_environment_credentials_win(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env-secret")
    assert SpotifyCredentials.load().client_id == "env-id"


def test_local_provider_reads_a_file(wav_file, melody_audio):
    path = wav_file(melody_audio, 22050)
    provider = LocalFileProvider()
    reference = provider.resolve(str(path))
    assert reference.provider == "local"
    result = provider.fetch(str(path))
    assert result.path == path
    assert result.match_confidence == 1.0


def test_safe_filename_strips_dangerous_characters():
    assert "/" not in safe_filename("AC/DC - Song")
    assert ":" not in safe_filename("Artist: Title")
    assert safe_filename("   ") == "track"
    assert len(safe_filename("x" * 300)) <= 80


# -- match scoring --------------------------------------------------------


def test_duration_match_confidence():
    assert duration_match_confidence(200.0, 202.0)[0] == 1.0
    assert duration_match_confidence(200.0, 212.0)[0] < 1.0
    # An hour-long loop of a three-minute song must score near zero.
    assert duration_match_confidence(200.0, 3600.0)[0] < 0.2
    assert duration_match_confidence(None, 200.0)[0] < 1.0


def _reference(title, artist="", duration=200.0, uploader=""):
    return TrackReference(
        title=title,
        artist=artist,
        duration_seconds=duration,
        provider="youtube",
        extra={"uploader": uploader},
    )


def test_the_studio_version_beats_a_live_version():
    expected = _reference("Photograph", "Ed Sheeran", 260.0)
    studio = _reference("Photograph (Official Music Video)", "Ed Sheeran", 262.0)
    live = _reference("Photograph (Live at Wembley)", "Ed Sheeran", 275.0)
    assert score_candidate(expected, studio).score > score_candidate(expected, live).score


def test_an_hour_long_loop_is_rejected():
    expected = _reference("Photograph", "Ed Sheeran", 260.0)
    loop = _reference("Photograph [1 hour]", "Ed Sheeran", 3600.0)
    scored = score_candidate(expected, loop)
    assert scored.score < 0.35
    assert any("1 hour" in r or "longer" in r for r in scored.reasons)


def test_a_cover_scores_below_the_original():
    expected = _reference("Photograph", "Ed Sheeran", 260.0)
    original = _reference("Photograph", "Ed Sheeran", 261.0)
    cover = _reference("Photograph (cover)", "Someone Else", 259.0)
    assert score_candidate(expected, original).score > score_candidate(expected, cover).score


def test_a_wrong_length_edit_is_penalised():
    expected = _reference("Song", "Band", 200.0)
    short = _reference("Song", "Band", 95.0)
    assert score_candidate(expected, short).score < score_candidate(
        expected, _reference("Song", "Band", 201.0)
    ).score


# -- song structure -------------------------------------------------------


def _sectioned_song() -> list[NoteEvent]:
    """A - B - A - B with a quiet intro: two repeated sections and a lead-in."""
    events: list[NoteEvent] = []
    t = 0.0
    # Quiet, sparse intro.
    for i in range(8):
        events.append(NoteEvent(60 + (i % 3), t, 0.4, 0.3, 1.0, "intro"))
        t += 1.2
    for _ in range(2):
        # A: low, moderate.
        for i in range(24):
            events.append(NoteEvent(55 + [0, 3, 5, 7][i % 4], t, 0.4, 0.6, 1.0, "A"))
            t += 0.5
        # B: higher, denser, louder -- a chorus.
        for i in range(32):
            events.append(NoteEvent(72 + [0, 2, 4, 7][i % 4], t, 0.25, 0.95, 1.0, "B"))
            t += 0.3
    return events


def test_structure_finds_more_than_one_section():
    structure = analyze_structure(_sectioned_song(), bpm=120.0)
    assert len(structure.segments) >= 3
    assert structure.hook_index is not None


def test_repeated_material_shares_a_label():
    structure = analyze_structure(_sectioned_song(), bpm=120.0)
    assert max(s.repetitions for s in structure.segments) >= 2


def test_the_hook_is_the_loud_repeated_section_not_the_intro():
    events = _sectioned_song()
    structure = analyze_structure(events, bpm=120.0)
    hook = structure.hook
    assert hook is not None
    # The intro is the first ~10 seconds and must never be the hook.
    assert hook.start_seconds > 5.0
    assert hook.recognizability >= max(s.recognizability for s in structure.segments) - 1e-6


def test_structure_features_add_contours_to_chroma():
    features, _frame = structure_features(_sectioned_song(), frame_seconds=0.5)
    # Twelve chroma bins plus register, density and energy.
    assert features.shape[0] == 15


def test_structure_survives_tiny_input():
    structure = analyze_structure([NoteEvent(60, 0.0, 0.5)], bpm=120.0)
    assert len(structure.segments) == 1
    assert structure.hook_index == 0


def test_structure_of_nothing_is_empty():
    assert analyze_structure([]).segments


def test_best_window_prefers_the_hook_over_the_opening():
    events = _sectioned_song()
    total = max(e.end_seconds for e in events)
    structure = analyze_structure(events, bpm=120.0)
    start, end = best_window(structure, window_seconds=total * 0.5, total_seconds=total)
    assert end - start <= total * 0.5 + 1e-6
    hook = structure.hook
    assert hook is not None
    # The window must overlap the hook rather than just taking the first half.
    assert min(end, hook.end_seconds) - max(start, hook.start_seconds) > 0


def test_best_window_of_a_short_song_is_the_whole_song():
    events = [NoteEvent(60, i * 0.5, 0.4) for i in range(20)]
    structure = analyze_structure(events, bpm=120.0)
    start, end = best_window(structure, window_seconds=240.0, total_seconds=10.0)
    assert start == 0.0
    assert end == 10.0


def test_recognizability_weights_favour_the_hook():
    events = _sectioned_song()
    structure = analyze_structure(events, bpm=120.0)
    weights = recognizability_weights(events, structure)
    assert len(weights) == len(events)
    assert all(0.5 <= w <= 1.01 for w in weights)
    hook = structure.hook
    assert hook is not None
    inside = [w for w, e in zip(weights, sorted(events, key=lambda x: x.start_seconds))
              if hook.contains(e.start_seconds)]
    outside = [w for w, e in zip(weights, sorted(events, key=lambda x: x.start_seconds))
               if e.start_seconds < 8.0]
    assert sum(inside) / len(inside) > sum(outside) / len(outside)


def test_melodic_hook_returns_the_top_line():
    events = _sectioned_song()
    structure = analyze_structure(events, bpm=120.0)
    notes = melodic_hook(events, structure, max_notes=8)
    assert 0 < len(notes) <= 8


# -- Shawzin recommendation ----------------------------------------------


def _profile(**kwargs) -> MusicProfile:
    base = dict(
        notes_per_second=3.0,
        peak_notes_per_second=6.0,
        mean_polyphony=1.0,
        max_polyphony=1.0,
        chord_fraction=0.0,
        mean_gap_seconds=0.33,
        median_pitch=64,
        low_fraction=0.0,
        sustain_fraction=0.2,
        note_count=100,
    )
    base.update(kwargs)
    return MusicProfile(**base)


def test_every_variant_is_ranked_with_reasons():
    suggestions = recommend_shawzin(_profile())
    assert len(suggestions) == 11
    scores = [s.score for s in suggestions]
    assert scores == sorted(scores, reverse=True)
    for s in suggestions:
        assert s.reasons, s.variant_id
        assert s.timbre, s.variant_id


def test_a_low_riff_recommends_the_bass_shawzin():
    suggestions = recommend_shawzin(
        _profile(median_pitch=40, low_fraction=0.9, notes_per_second=2.0, mean_gap_seconds=0.5)
    )
    assert suggestions[0].variant_id == "tiamat"


def test_a_high_line_does_not_recommend_the_bass_shawzin():
    suggestions = recommend_shawzin(_profile(median_pitch=78, low_fraction=0.0))
    assert suggestions[0].variant_id != "tiamat"
    tiamat = next(s for s in suggestions if s.variant_id == "tiamat")
    assert any("octave lower" in w for w in tiamat.warnings)


def test_chordal_music_prefers_a_polyphonic_shawzin():
    suggestions = recommend_shawzin(
        _profile(chord_fraction=0.9, max_polyphony=3.0, mean_polyphony=3.0, mean_gap_seconds=1.2)
    )
    assert suggestions[0].polyphony == "polyphonic"


def test_monophonic_variants_warn_about_chords():
    suggestions = recommend_shawzin(_profile(chord_fraction=0.8, max_polyphony=3.0))
    corbu = next(s for s in suggestions if s.variant_id == "corbu")
    assert any("Monophonic" in w for w in corbu.warnings)


def test_a_fast_line_penalises_the_longest_sustain():
    suggestions = recommend_shawzin(
        _profile(notes_per_second=10.0, mean_gap_seconds=0.1, peak_notes_per_second=12)
    )
    by_id = {s.variant_id: s for s in suggestions}
    assert by_id["lizzie"].score < by_id["dax"].score
    assert any("muddy" in w or "overlap" in w for w in by_id["lizzie"].warnings)


def test_a_slow_sparse_piece_tolerates_long_sustain():
    fast = recommend_shawzin(_profile(notes_per_second=10.0, mean_gap_seconds=0.1))
    slow = recommend_shawzin(_profile(notes_per_second=0.6, mean_gap_seconds=1.8))
    assert next(s for s in slow if s.variant_id == "corbu").score > next(
        s for s in fast if s.variant_id == "corbu"
    ).score


def test_the_nelumbo_mentions_its_tuning():
    suggestions = recommend_shawzin(_profile())
    nelumbo = next(s for s in suggestions if s.variant_id == "nelumbo")
    assert any("cents" in w for w in nelumbo.warnings)


def test_recommendation_counts_notes_a_variant_would_drop(instrument):
    from shawzify_engine.shawzin.songcode import ShawzinEvent, ShawzinSong

    song = ShawzinSong("maj", [ShawzinEvent(i * 8, "1", "123") for i in range(4)])
    suggestions = recommend_shawzin(_profile(chord_fraction=1.0, max_polyphony=3.0), song=song)
    corbu = next(s for s in suggestions if s.variant_id == "corbu")
    # Monophonic: two of every three strings are lost.
    assert corbu.notes_lost == 8
    dax = next(s for s in suggestions if s.variant_id == "dax")
    assert dax.notes_lost == 0


def test_profile_music_measures_real_properties(chord_progression):
    profile = profile_music(chord_progression)
    assert profile.note_count == 12
    assert profile.max_polyphony == 3.0
    assert profile.chord_fraction == 1.0


# -- the arranger's focus mode -------------------------------------------


def test_hook_focus_trims_to_the_recognisable_window(instrument):
    from shawzify_engine.arrangement import arrange_for_shawzin
    from shawzify_engine.arrangement.options import ArrangementOptions, Focus

    # Six minutes: over the Shawzin's four-minute limit.
    events = [NoteEvent(60 + (i * 7) % 19, i * 0.35, 0.3, 0.8, 1.0, "x") for i in range(1030)]
    full = arrange_for_shawzin(events, instrument, ArrangementOptions(focus=Focus.FULL), bpm=120.0)
    hook = arrange_for_shawzin(events, instrument, ArrangementOptions(focus=Focus.HOOK), bpm=120.0)

    assert full.over_limits
    assert hook.resolved.focus == "hook"
    assert hook.resolved.focus_window is not None
    assert hook.song.duration_seconds() <= instrument.format.max_song_seconds + 1
    assert any("most recognisable" in w for w in hook.report.warnings)


def test_full_focus_never_trims(instrument):
    from shawzify_engine.arrangement import arrange_for_shawzin
    from shawzify_engine.arrangement.options import ArrangementOptions, Focus

    events = [NoteEvent(60 + (i % 12), i * 0.3, 0.25) for i in range(200)]
    arrangement = arrange_for_shawzin(
        events, instrument, ArrangementOptions(focus=Focus.FULL), bpm=120.0
    )
    assert arrangement.resolved.focus_window is None


def test_structure_is_attached_to_the_arrangement(instrument, twinkle):
    from shawzify_engine.arrangement import arrange_for_shawzin

    arrangement = arrange_for_shawzin(twinkle, instrument, bpm=120.0)
    assert arrangement.structure is not None
    assert arrangement.to_dict()["structure"]["segments"]


def test_structure_can_be_turned_off(instrument, twinkle):
    from shawzify_engine.arrangement import arrange_for_shawzin
    from shawzify_engine.arrangement.options import ArrangementOptions

    arrangement = arrange_for_shawzin(
        twinkle, instrument, ArrangementOptions(use_structure=False), bpm=120.0
    )
    assert arrangement.structure is None


# -- the web server -------------------------------------------------------


@pytest.fixture
def web_server():
    from shawzify_engine.web import WebServer

    server = WebServer(port=0).start()
    yield server
    server.stop()


def _get(server, path: str, *, token: str | None = "auto") -> tuple[int, dict]:
    url = "http://127.0.0.1:" + str(server.port) + path
    actual = server.token if token == "auto" else token
    if actual:
        url += ("&" if "?" in path else "?") + "token=" + actual
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - localhost
            return (response.status, json.loads(response.read()))
    except urllib.error.HTTPError as exc:
        try:
            return (exc.code, json.loads(exc.read()))
        except Exception:  # noqa: BLE001
            return (exc.code, {})


def _post(server, path: str, payload: dict, *, token: str | None = "auto") -> tuple[int, dict]:
    url = "http://127.0.0.1:" + str(server.port) + path
    actual = server.token if token == "auto" else token
    if actual:
        url += "?token=" + actual
    request = urllib.request.Request(  # noqa: S310 - localhost only
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (response.status, json.loads(response.read()))
    except urllib.error.HTTPError as exc:
        try:
            return (exc.code, json.loads(exc.read()))
        except Exception:  # noqa: BLE001
            return (exc.code, {})


def test_web_server_refuses_to_bind_beyond_localhost():
    from shawzify_engine.web import WebServer

    with pytest.raises(ShawzifyError, match="localhost"):
        WebServer(host="0.0.0.0", port=0)  # noqa: S104 - the point of the test


def test_health_needs_no_token(web_server):
    status, payload = _get(web_server, "/api/health", token=None)
    assert status == 200
    assert payload["ok"] is True


def test_api_requires_the_token(web_server):
    status, _payload = _post(web_server, "/api/rpc", {"method": "ping"}, token=None)
    assert status == 403
    status, _payload = _post(web_server, "/api/rpc", {"method": "ping"}, token="wrong")
    assert status == 403


def test_api_answers_with_the_token(web_server):
    status, payload = _post(web_server, "/api/rpc", {"method": "ping"})
    assert status == 200
    assert payload["result"]["ok"] is True


def test_api_reports_engine_errors_rather_than_crashing(web_server):
    status, payload = _post(
        web_server, "/api/rpc", {"method": "analyze", "params": {"path": "nope.mp3"}}
    )
    assert status == 200
    assert payload["error"]["code"] == "unsafe_path"


def test_unknown_method_is_an_error(web_server):
    _status, payload = _post(web_server, "/api/rpc", {"method": "nope"})
    assert "error" in payload


def test_media_route_refuses_paths_outside_the_cache(web_server, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    url = (
        "http://127.0.0.1:"
        + str(web_server.port)
        + "/media?token="
        + web_server.token
        + "&path="
        + urllib.request.quote(str(outside))
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            body = response.read()
        raise AssertionError("the server served a file outside its cache: " + str(body[:80]))
    except urllib.error.HTTPError as exc:
        assert exc.code == 403


def test_cross_origin_requests_are_refused(web_server):
    url = "http://127.0.0.1:" + str(web_server.port) + "/api/rpc?token=" + web_server.token
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps({"method": "ping"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310
            raise AssertionError("a cross-origin request was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403


def test_the_token_survives_a_restart(tmp_path, monkeypatch):
    """An open page must not die every time the server is restarted."""
    from shawzify_engine.web import server as web

    monkeypatch.setattr(web, "token_path", lambda: tmp_path / "web-token")

    first = web.stored_token()
    assert len(first) >= 16
    assert web.stored_token() == first


def test_rotating_the_token_replaces_it(tmp_path, monkeypatch):
    from shawzify_engine.web import server as web

    monkeypatch.setattr(web, "token_path", lambda: tmp_path / "web-token")

    first = web.stored_token()
    second = web.stored_token(rotate=True)
    assert second != first
    assert web.stored_token() == second


def test_a_corrupt_token_file_is_replaced(tmp_path, monkeypatch):
    from shawzify_engine.web import server as web

    path = tmp_path / "web-token"
    path.write_text("short", encoding="utf-8")
    monkeypatch.setattr(web, "token_path", lambda: path)

    token = web.stored_token()
    assert len(token) >= 16
    assert token != "short"


def test_a_refused_call_does_not_poison_the_connection(web_server):
    """A rejected POST must still consume its body.

    Browsers reuse one connection for every call. When the server answered an
    unauthorised POST without reading the body, the leftover bytes were parsed
    as the next request line, and every later call on that connection came back
    as 501 Unsupported method -- with the previous call's JSON quoted in the
    error. One stale token broke the whole page, not just its own request.
    """
    connection = http.client.HTTPConnection("127.0.0.1", web_server.port, timeout=10)
    try:
        origin = "http://127.0.0.1:" + str(web_server.port)
        payload = json.dumps({"method": "sources", "params": {}})
        headers = {"Content-Type": "application/json", "Origin": origin}

        connection.request("POST", "/api/rpc?token=wrong", payload, headers)
        refused = connection.getresponse()
        refused.read()
        assert refused.status == 403

        connection.request(
            "POST", "/api/rpc?token=" + web_server.token, payload, headers
        )
        allowed = connection.getresponse()
        body = json.loads(allowed.read())
        assert allowed.status == 200, allowed.reason
        assert "providers" in body["result"]
    finally:
        connection.close()


def test_an_oversized_body_is_refused_without_reading_it(web_server):
    connection = http.client.HTTPConnection("127.0.0.1", web_server.port, timeout=10)
    try:
        connection.putrequest("POST", "/api/rpc?token=" + web_server.token)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Origin", "http://127.0.0.1:" + str(web_server.port))
        connection.putheader("Content-Length", str(64 * 1024 * 1024))
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        assert response.status == 413
    finally:
        connection.close()


def test_the_page_is_served_without_handing_out_the_token(web_server):
    """The document is not itself authorised, so it must carry no secret.

    The browser fetches index.html and its assets without a token -- it cannot
    add one to a <script src>. That makes the page readable by anything running
    on this machine, so the token lives in the page's URL, not in the page.
    """
    url = "http://127.0.0.1:" + str(web_server.port) + "/"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    assert "SHAWZIFY" in body
    assert web_server.token not in body


def test_events_stream_opens(web_server):
    url = (
        "http://127.0.0.1:"
        + str(web_server.port)
        + "/api/events?token="
        + web_server.token
    )
    opened = threading.Event()

    def read() -> None:
        try:
            with urllib.request.urlopen(url, timeout=6) as response:  # noqa: S310
                assert response.headers["Content-Type"].startswith("text/event-stream")
                response.readline()
                opened.set()
        except Exception:  # noqa: BLE001 - the assert below reports it
            pass

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    assert opened.wait(timeout=10), "the event stream did not open"


def test_full_conversion_over_http(web_server, midi_file, twinkle):
    path = midi_file(twinkle, bpm=120.0)
    _status, analysis = _post(
        web_server,
        "/api/rpc",
        {"method": "analyze", "params": {"path": str(path), "useStems": False}},
    )
    source_id = analysis["result"]["sourceId"]

    _status, arranged = _post(
        web_server,
        "/api/rpc",
        {"method": "arrange", "params": {"sourceId": source_id, "options": {"mode": "melody"}}},
    )
    result = arranged["result"]
    assert result["code"]
    assert result["shawzinSuggestions"]
    assert result["musicProfile"]["noteCount"] > 0

    _status, recommended = _post(
        web_server, "/api/rpc", {"method": "recommendShawzin", "params": {"sourceId": source_id}}
    )
    assert len(recommended["result"]["suggestions"]) == 11

    _status, structure = _post(
        web_server, "/api/rpc", {"method": "structure", "params": {"sourceId": source_id}}
    )
    assert structure["result"]["structure"]["segments"]


def test_sources_endpoint_lists_providers(web_server):
    _status, payload = _post(web_server, "/api/rpc", {"method": "sources"})
    ids = {p["id"] for p in payload["result"]["providers"]}
    assert ids == {"local", "youtube", "spotify"}

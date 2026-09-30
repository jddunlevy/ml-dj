import json
from pathlib import Path

import pytest

from fakes import FakeClock, FakeTransport
from mldj.lastfm import (
    LastfmClient,
    LastfmError,
    artist_top_tags,
    artist_top_tags_cached,
    top_tags,
    top_tags_cached,
)
from mldj.transport import Response

FIXTURES = Path(__file__).parent.parent / "fixtures"
TOPTAGS = (FIXTURES / "lastfm-toptags.json").read_bytes()


def client(responses, clock=None):
    return LastfmClient(FakeTransport(responses), clock or FakeClock(), api_key="k")


def test_call_builds_a_json_request_with_the_api_key():
    c = client([Response(200, b"{}")])
    c.call("user.getRecentTracks", user="listener", limit="200")
    _, url, _ = c.transport.requests[0]
    assert url.startswith("https://ws.audioscrobbler.com/2.0/?")
    assert "method=user.getRecentTracks" in url
    assert "format=json" in url
    assert "api_key=k" in url
    assert "user=listener" in url


def test_call_paces_itself_between_requests():
    # Last.fm asks for a handful of requests per second at most; 196 pages must not burst.
    clock = FakeClock(0)
    c = client([Response(200, b"{}"), Response(200, b"{}")], clock)
    c.call("a")
    c.call("b")
    assert clock.sleeps == [250]


def test_call_raises_on_an_error_reported_inside_a_200_body():
    # Last.fm signals API errors in the body, not the HTTP status.
    body = json.dumps({"error": 6, "message": "User not found"}).encode()
    with pytest.raises(LastfmError, match="User not found"):
        client([Response(200, body)]).call("user.getRecentTracks", user="nobody")


def test_call_does_not_retry_a_client_error():
    # A 404 or 403 means a bad key or username; retrying only burns requests.
    c = client([Response(404, b"nope")])
    with pytest.raises(LastfmError, match="404"):
        c.call("a")
    assert len(c.transport.requests) == 1


def test_call_retries_a_429_and_honours_retry_after():
    clock = FakeClock(0)
    c = client([Response(429, b"", {"Retry-After": "2"}), Response(200, b'{"ok":1}')], clock)
    assert c.call("a") == {"ok": 1}
    assert 2000 in clock.sleeps


def test_call_retries_a_transient_500_then_succeeds():
    # Observed for real: a 196-page ingest met a 500 at page ~72, and the same page
    # returned 200 moments later. Without this retry the whole ingest dies.
    clock = FakeClock(0)
    c = client([Response(500, b"boom"), Response(200, b'{"ok":1}')], clock)
    assert c.call("a") == {"ok": 1}
    assert len(c.transport.requests) == 2


def test_call_retries_a_dropped_connection():
    # UrllibTransport reports a transport-level failure as status 0.
    c = client([Response(0, b"connection reset"), Response(200, b'{"ok":1}')])
    assert c.call("a") == {"ok": 1}


def test_call_backs_off_exponentially_between_server_errors():
    clock = FakeClock(0)
    c = client([Response(500, b"")] * 3 + [Response(200, b"{}")], clock)
    c.call("a")
    assert [s for s in clock.sleeps if s >= 1000] == [1000, 2000, 4000]


def test_call_gives_up_after_max_attempts():
    c = LastfmClient(
        FakeTransport([Response(429, b"", {"Retry-After": "1"})] * 3),
        FakeClock(),
        api_key="k",
        max_attempts=3,
    )
    with pytest.raises(LastfmError, match="after 3 attempts"):
        c.call("a")


def test_top_tags_returns_names_with_counts_highest_first():
    assert top_tags(client([Response(200, TOPTAGS)]), "New Order", "Blue Monday") == [
        ("new wave", 100),
        ("synthpop", 92),
        ("80s", 71),
        ("dance", 40),
    ]


def test_top_tags_handles_a_track_with_no_tags():
    body = json.dumps({"toptags": {"tag": []}}).encode()
    assert top_tags(client([Response(200, body)]), "Nobody", "Nothing") == []


def test_top_tags_cached_hits_the_network_once(tmp_path):
    c = client([Response(200, TOPTAGS)])  # a second call would exhaust the script
    first = top_tags_cached(c, "New Order", "Blue Monday", cache_dir=tmp_path)
    second = top_tags_cached(c, "New Order", "Blue Monday", cache_dir=tmp_path)
    assert first == second
    assert len(c.transport.requests) == 1


ARTISTTAGS = (FIXTURES / "lastfm-artisttags.json").read_bytes()


def test_artist_top_tags_parses_and_orders_by_count():
    assert artist_top_tags(client([Response(200, ARTISTTAGS)]), "New Order") == [
        ("new wave", 100),
        ("post-punk", 88),
        ("synthpop", 74),
        ("80s", 61),
        ("electronic", 45),
    ]


def test_artist_top_tags_handles_an_untagged_artist():
    body = json.dumps({"toptags": {"tag": []}}).encode()
    assert artist_top_tags(client([Response(200, body)]), "Nobody At All") == []


def test_artist_top_tags_cached_hits_the_network_once(tmp_path):
    c = client([Response(200, ARTISTTAGS)])  # a second call would exhaust the script
    first = artist_top_tags_cached(c, "New Order", cache_dir=tmp_path)
    second = artist_top_tags_cached(c, "New Order", cache_dir=tmp_path)
    assert first == second
    assert len(c.transport.requests) == 1


def test_artist_and_track_caches_do_not_collide(tmp_path):
    # An artist and a track share a cache filename; only the separate directories keep
    # them apart, so that separation is asserted rather than assumed.
    tracks, artists = tmp_path / "tags", tmp_path / "artist-tags"
    artist_top_tags_cached(client([Response(200, ARTISTTAGS)]), "New Order", cache_dir=artists)
    top_tags_cached(client([Response(200, TOPTAGS)]), "New Order", "", cache_dir=tracks)
    assert artist_top_tags_cached(
        client([]), "New Order", cache_dir=artists
    ) == [("new wave", 100), ("post-punk", 88), ("synthpop", 74), ("80s", 61), ("electronic", 45)]
    assert top_tags_cached(client([]), "New Order", "", cache_dir=tracks)[0] == ("new wave", 100)


# A candidate pool is built from artist.getSimilar -> artist.getTopTracks, and Last.fm does
# not always know the resulting (artist, track) pair by that spelling. Error 6 is what it
# returns for "Track not found". It is an ordinary fact about an obscure track, not a
# failure, and top_tags already promises "an untagged track returns []" - so it must return
# that rather than take down a caller that is looping over hundreds of candidates.


def _error_body(code: int, message: str) -> bytes:
    return json.dumps({"error": code, "message": message}).encode()


def test_lastfm_error_carries_the_api_error_code():
    c = client([Response(200, _error_body(6, "Track not found"))])
    with pytest.raises(LastfmError) as excinfo:
        c.call("track.getTopTags", artist="Nobody", track="Nothing")
    assert excinfo.value.code == 6


def test_lastfm_error_code_is_none_for_a_transport_level_failure():
    c = client([Response(404, b"")])
    with pytest.raises(LastfmError) as excinfo:
        c.call("track.getTopTags")
    assert excinfo.value.code is None


def test_top_tags_treats_an_unknown_track_as_untagged():
    c = client([Response(200, _error_body(6, "Track not found"))])
    assert top_tags(c, "Nobody", "Nothing At All") == []


def test_top_tags_still_raises_on_an_error_that_is_not_a_missing_track():
    # An invalid API key must stop the run loudly. Swallowing it would turn every track in
    # the corpus into an untagged one and the space would quietly build from nothing.
    c = client([Response(200, _error_body(10, "Invalid API key"))])
    with pytest.raises(LastfmError):
        top_tags(c, "Kate Bush", "Wuthering Heights")


def test_artist_top_tags_treats_an_unknown_artist_as_untagged():
    c = client([Response(200, _error_body(6, "Artist not found"))])
    assert artist_top_tags(c, "Nobody At All") == []


def test_top_tags_cached_caches_the_empty_result_for_an_unknown_track(tmp_path):
    # Without this the pool re-asks Last.fm about the same missing track on every refresh,
    # which in live mode is every few seconds.
    c = client([Response(200, _error_body(6, "Track not found"))])
    assert top_tags_cached(c, "Nobody", "Nothing", cache_dir=tmp_path) == []
    assert top_tags_cached(c, "Nobody", "Nothing", cache_dir=tmp_path) == []
    assert len(c.transport.requests) == 1

import json
from pathlib import Path

import pytest

from fakes import FakeClock, FakeTransport
from mldj.lastfm import LastfmClient, LastfmError, top_tags, top_tags_cached
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

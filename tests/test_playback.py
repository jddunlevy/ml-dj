from fakes import FakeTransport
from mldj.playback import PlaybackError, queue_track
from mldj.transport import Response


def token() -> str:
    return "tok"


def test_queue_track_posts_the_uri_as_a_query_parameter():
    """Spotify takes the track on the query string, not in the body, and answers 204."""
    transport = FakeTransport([Response(204, b"")])

    queue_track(transport, token, "spotify:track:4VedfquAzkjR15ntcWmNfL")

    method, url, _ = transport.requests[0]
    assert method == "POST_JSON"
    assert url == (
        "https://api.spotify.com/v1/me/player/queue"
        "?uri=spotify%3Atrack%3A4VedfquAzkjR15ntcWmNfL"
    )


def test_queue_track_refreshes_once_on_401_then_retries():
    """A 401 mid-run means the token died regardless of what the clock said."""
    transport = FakeTransport([Response(401, b""), Response(204, b"")])
    refreshed = []

    queue_track(transport, token, "spotify:track:x", lambda: refreshed.append(1))

    assert refreshed == [1]
    assert len(transport.requests) == 2


def test_queue_track_reports_spotifys_own_message_not_a_guess():
    """playlist.py asserted 'missing scope' for every 403 and sent the last debugging
    session chasing a scope that was fine. Print what Spotify actually said."""
    body = b'{"error":{"status":403,"reason":"PREMIUM_REQUIRED"}}'
    transport = FakeTransport([Response(403, body)])

    try:
        queue_track(transport, token, "spotify:track:x")
    except PlaybackError as err:
        assert "PREMIUM_REQUIRED" in str(err)
    else:
        raise AssertionError("expected PlaybackError")


def test_queue_track_explains_a_missing_device():
    """404 here is not a bad URL - it is nothing playing, which is the common case."""
    body = b'{"error":{"status":404,"message":"Player command failed: No active device"}}'
    transport = FakeTransport([Response(404, body)])

    try:
        queue_track(transport, token, "spotify:track:x")
    except PlaybackError as err:
        assert "no active device" in str(err).lower()
    else:
        raise AssertionError("expected PlaybackError")


def test_queue_track_names_the_fix_when_a_401_survives_a_refresh():
    """A 401 that survives a refresh is a stale GRANT, not a stale token.

    force_refresh happily mints a new access token carrying the OLD scopes, so the retry
    fails identically and the real cause - SCOPE widened since the user last consented -
    never gets named. This is what made the queue write fail silently on 2026-10-03.
    """
    transport = FakeTransport([Response(401, b'{"error":{"message":"Permissions missing"}}')] * 2)

    try:
        queue_track(transport, token, "spotify:track:x", lambda: None)
    except PlaybackError as err:
        assert "re-authorize" in str(err).lower()
        assert ".spotify-tokens.json" in str(err)
    else:
        raise AssertionError("expected PlaybackError")

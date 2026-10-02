import json
import socket
import threading
import urllib.request

import pytest

from fakes import FakeClock, FakeTransport
from mldj.auth import (
    REDIRECT_URI,
    SCOPE,
    Tokens,
    authorize_url,
    code_challenge,
    exchange_code,
    load_tokens,
    merge_token_response,
    parse_callback_code,
    random_verifier,
    refresh_tokens,
    save_tokens,
    should_refresh,
    token_provider,
    wait_for_code,
)
from mldj.transport import Response

# RFC 7636 appendix B publishes this verifier/challenge pair.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_code_challenge_matches_the_rfc_7636_test_vector():
    assert code_challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_random_verifier_is_the_right_length_and_alphabet():
    verifier = random_verifier()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert len(verifier) == 64
    assert set(verifier) <= allowed


def test_random_verifier_does_not_repeat():
    assert random_verifier() != random_verifier()


def test_authorize_url_constructs_the_correct_parameters():
    url = authorize_url("client-abc", RFC_VERIFIER)
    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert "code_challenge_method=S256" in url
    assert f"code_challenge={RFC_CHALLENGE}" in url
    assert "scope=user-read-currently-playing" in url
    assert "playlist-modify-private" in url
    assert "user-library-read" in url
    assert "user-top-read" in url
    assert REDIRECT_URI == "http://127.0.0.1:8888/callback"
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback" in url


def test_parse_callback_code_extracts_the_code():
    assert parse_callback_code("/callback?code=abc123&state=x") == "abc123"


def test_parse_callback_code_returns_none_without_a_code():
    assert parse_callback_code("/favicon.ico") is None
    assert parse_callback_code("/callback?error=access_denied") is None


def test_merge_token_response_computes_an_absolute_expiry():
    tokens = merge_token_response(
        None, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}, now_ms=1_000
    )
    assert tokens == Tokens("a1", "r1", 1_000 + 3_600_000)


def test_merge_token_response_keeps_the_previous_refresh_token_when_none_is_returned():
    # Spotify's refresh response often omits refresh_token; losing it would force re-login.
    prev = Tokens("old", "keep-me", 0)
    tokens = merge_token_response(prev, {"access_token": "a2", "expires_in": 60}, now_ms=5_000)
    assert tokens.refresh_token == "keep-me"


def test_should_refresh_uses_a_sixty_second_margin():
    tokens = Tokens("a", "r", expires_at=100_000)
    assert should_refresh(tokens, now_ms=39_000) is False
    assert should_refresh(tokens, now_ms=40_000) is True


def test_tokens_round_trip_through_disk(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("a1", "r1", 123), path)
    assert load_tokens(path) == Tokens("a1", "r1", 123)


def test_load_tokens_returns_none_when_no_file_exists(tmp_path):
    assert load_tokens(tmp_path / "absent.json") is None


def test_exchange_code_posts_the_verifier():
    payload = json.dumps({"access_token": "a1", "refresh_token": "r1", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    tokens = exchange_code(transport, FakeClock(7_000), "client-abc", "code-1", RFC_VERIFIER)
    method, url, data = transport.requests[0]
    assert (method, url) == ("POST", "https://accounts.spotify.com/api/token")
    assert data["grant_type"] == "authorization_code"
    assert data["code_verifier"] == RFC_VERIFIER
    assert data["redirect_uri"] == REDIRECT_URI
    assert tokens == Tokens("a1", "r1", 7_000 + 3_600_000)


def test_exchange_code_raises_on_a_rejected_exchange():
    transport = FakeTransport([Response(400, b'{"error":"invalid_grant"}')])
    with pytest.raises(SystemExit):
        exchange_code(transport, FakeClock(), "client-abc", "bad", RFC_VERIFIER)


def test_refresh_tokens_sends_the_refresh_grant():
    payload = json.dumps({"access_token": "a2", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    refreshed = refresh_tokens(transport, FakeClock(1_000), "client-abc", Tokens("a1", "r1", 0))
    _, _, data = transport.requests[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "r1"
    assert refreshed == Tokens("a2", "r1", 1_000 + 3_600_000)


def test_token_provider_returns_a_live_token_without_calling_the_network(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("still-good", "r1", expires_at=10_000_000), path)
    transport = FakeTransport([])  # any request would raise
    provide = token_provider(transport, FakeClock(1_000), "client-abc", path)
    assert provide() == "still-good"


def test_token_provider_refreshes_and_persists_an_expiring_token(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("stale", "r1", expires_at=100_000), path)
    payload = json.dumps({"access_token": "fresh", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    provide = token_provider(transport, FakeClock(99_000), "client-abc", path)
    assert provide() == "fresh"
    stored = load_tokens(path)
    assert stored is not None
    assert stored.access_token == "fresh"


def test_wait_for_code_captures_the_code_from_a_real_loopback_request():
    # Local sockets only - this is not the wire. Port 0 lets the OS pick a free port so the
    # test never collides with a real capture session holding 8888.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    ready = threading.Event()
    captured: list[str] = []
    thread = threading.Thread(
        target=lambda: captured.append(wait_for_code(port=port, on_ready=ready.set)),
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=5), "the callback server never bound"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=xyz789", timeout=5) as r:
        assert r.status == 200
    thread.join(timeout=5)
    assert captured == ["xyz789"]


def test_the_token_carries_exactly_the_scopes_the_project_needs():
    assert set(SCOPE.split()) == {
        "user-read-currently-playing",
        "playlist-modify-private",
        "user-library-read",
        "user-top-read",
    }


def test_the_token_never_carries_playback_control():
    # Nothing in this project touches playback. The narrower the token, the smaller the blast
    # radius of a bug in a tool that is one typo from writing to a real account. Queue writing
    # is Phase 4 and stays out until the pitch is delivered.
    assert "user-modify-playback-state" not in SCOPE

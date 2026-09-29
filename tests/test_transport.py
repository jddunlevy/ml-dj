import pytest

from fakes import FakeClock, FakeTransport
from mldj.transport import DEFAULT_RETRY_MS, Response, retry_after_ms


def test_response_json_decodes_the_body():
    assert Response(200, b'{"a": 1}').json() == {"a": 1}


def test_response_json_is_none_for_an_empty_body():
    # A 204 from currently-playing has no body at all.
    assert Response(204, b"").json() is None


def test_response_header_lookup_ignores_case():
    r = Response(429, b"", {"Retry-After": "3"})
    assert r.header("retry-after") == "3"
    assert r.header("RETRY-AFTER") == "3"
    assert r.header("missing") is None


def test_retry_after_converts_whole_seconds_to_milliseconds():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "3"})) == 3000


def test_retry_after_falls_back_when_the_header_is_absent():
    assert retry_after_ms(Response(429, b"", {})) == DEFAULT_RETRY_MS


def test_retry_after_falls_back_when_the_header_is_garbage():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "soon"})) == DEFAULT_RETRY_MS


def test_retry_after_never_returns_a_negative_wait():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "-5"})) == 0


def test_fake_clock_advances_only_when_told_to():
    clock = FakeClock(start_ms=1_000)
    assert clock.now_ms() == 1_000
    clock.sleep_ms(250)
    assert clock.now_ms() == 1_250
    assert clock.sleeps == [250]


def test_fake_transport_replays_its_script_and_records_requests():
    transport = FakeTransport([Response(200, b"{}"), Response(204, b"")])
    assert transport.get("https://example.invalid/a").status == 200
    assert transport.get("https://example.invalid/b").status == 204
    assert [r[1] for r in transport.requests] == [
        "https://example.invalid/a",
        "https://example.invalid/b",
    ]


def test_fake_transport_fails_loudly_when_the_script_runs_out():
    transport = FakeTransport([])
    with pytest.raises(AssertionError):
        transport.get("https://example.invalid/a")

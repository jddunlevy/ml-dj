import json

from fakes import FakeClock, FakeTransport
from mldj.capture import DEFAULT_INTERVAL_MS, run_capture
from mldj.events import EventWriter, read_events
from mldj.transport import Response

TRACK_BODY = json.dumps(
    {
        "progress_ms": 45000,
        "is_playing": True,
        "currently_playing_type": "track",
        "item": {
            "id": "id1",
            "name": "Ceiling Fan",
            "duration_ms": 213000,
            "artists": [{"name": "Paper Lanterns"}],
        },
    }
).encode()


def stop_after(n: int):
    """A should_stop predicate that allows exactly n iterations."""
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > n

    return should_stop


def capture_to(tmp_path, transport, clock, should_stop, interval_ms=1000):
    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        run_capture(
            transport=transport,
            clock=clock,
            access_token=lambda: "tok",
            writer=writer,
            label="dj",
            sid="20250930T000000Z",
            interval_ms=interval_ms,
            should_stop=should_stop,
        )
    return list(read_events(path))


def test_capture_writes_start_polls_and_end(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY), Response(200, TRACK_BODY)])
    events = capture_to(tmp_path, transport, FakeClock(1_000), stop_after(2))
    assert [e["type"] for e in events] == ["session_start", "poll", "poll", "session_end"]
    assert events[0]["interval_ms"] == 1000
    assert events[1]["id"] == "id1"
    assert events[-1]["reason"] == "stopped"


def test_capture_sleeps_the_interval_between_polls_and_never_really_waits(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY)] * 3)
    clock = FakeClock(1_000)
    capture_to(tmp_path, transport, clock, stop_after(3))
    assert clock.sleeps == [1000, 1000, 1000]


def test_capture_sends_a_bearer_token_on_every_poll(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY)])
    capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    _, url, headers = transport.requests[0]
    assert "me/player/currently-playing" in url
    assert headers["Authorization"] == "Bearer tok"


def test_capture_records_a_204_as_idle(tmp_path):
    transport = FakeTransport([Response(204, b"")])
    events = capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    assert [e["type"] for e in events] == ["session_start", "idle", "session_end"]


def test_capture_honours_retry_after_on_a_429_and_logs_a_gap(tmp_path):
    transport = FakeTransport(
        [Response(429, b"", {"Retry-After": "3"}), Response(200, TRACK_BODY)]
    )
    clock = FakeClock(1_000)
    events = capture_to(tmp_path, transport, clock, stop_after(2))
    assert [e["type"] for e in events] == ["session_start", "gap", "poll", "session_end"]
    gap = events[1]
    assert (gap["reason"], gap["retry_ms"]) == ("rate-limited", 3000)
    assert clock.sleeps == [3000, 1000]


def test_capture_logs_a_gap_for_any_other_http_failure(tmp_path):
    transport = FakeTransport([Response(500, b"boom")])
    events = capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    assert events[1]["type"] == "gap"
    assert events[1]["reason"] == "http-500"


def test_capture_writes_session_end_even_when_the_loop_raises(tmp_path):
    # Ctrl-C during a real session must still close the log cleanly.
    class Boom(FakeTransport):
        def get(self, url, headers=None):
            raise KeyboardInterrupt

    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        try:
            run_capture(
                transport=Boom(),
                clock=FakeClock(),
                access_token=lambda: "tok",
                writer=writer,
                label="dj",
                sid="sid",
                interval_ms=1000,
                should_stop=stop_after(1),
            )
        except KeyboardInterrupt:
            pass
    events = list(read_events(path))
    assert events[-1]["type"] == "session_end"
    assert events[-1]["reason"] == "interrupted"


# The Phase 0 report's verdict rule: an interval is "too slow" when the shortest observed gap
# between track changes is at or below two intervals, because the change lands inside the
# polling resolution. The shortest gap measured across the three dj captures was 1129 ms
# (reports/phase0-2026-09-30.md), so two intervals must fit under it with room to spare.
SHORTEST_OBSERVED_TRACK_GAP_MS = 1129


def test_the_default_interval_resolves_the_shortest_track_gap_phase_0_measured():
    assert 2 * DEFAULT_INTERVAL_MS < SHORTEST_OBSERVED_TRACK_GAP_MS


def test_the_default_interval_stays_inside_the_rate_allowance_with_headroom():
    # Spotify's rough allowance is 180 requests/minute; a 429 is a hole in the record, which
    # is worse than coarse resolution, so the loop keeps a third of the allowance in reserve
    # for token refresh and retries.
    requests_per_minute = 60_000 / DEFAULT_INTERVAL_MS
    assert requests_per_minute <= 120

"""Test doubles for the two injected boundaries. No test may use the real ones.

make_play is here too: the measure/ tests all need Play records, and Play carries eleven
fields of which each test cares about two or three.
"""

from collections.abc import Mapping

from mldj.skips import Play
from mldj.transport import Response

MINUTE_MS = 60_000


def make_play(
    artist: str = "Paper Lanterns",
    title: str = "Ceiling Fan",
    outcome: str = "completed",
    *,
    started_at_ms: int = 0,
    session: str = "s1",
    label: str = "dj",
    duration_ms: int = 200_000,
    listened_ms: int | None = None,
    track_id: str | None = None,
    reason: str = "",
) -> Play:
    """A Play with sensible defaults, so a test states only what it is about."""
    if listened_ms is None:
        listened_ms = duration_ms if outcome == "completed" else 5_000
    return Play(
        track_id=track_id if track_id is not None else f"{artist}:{title}",
        title=title,
        artist=artist,
        duration_ms=duration_ms,
        started_at_ms=started_at_ms,
        ended_at_ms=started_at_ms + listened_ms,
        listened_ms=listened_ms,
        outcome=outcome,
        session=session,
        label=label,
        reason=reason or ("ambiguous" if outcome == "unknown" else ""),
    )


class FakeClock:
    """A clock that only moves when the code under test sleeps, or a test advances it."""

    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms
        self.sleeps: list[int] = []

    def now_ms(self) -> int:
        return self._now

    def sleep_ms(self, ms: int) -> None:
        self.sleeps.append(ms)
        self._now += max(0, ms)

    def advance_ms(self, ms: int) -> None:
        self._now += ms


class FakeTransport:
    """Replays a scripted list of Responses and records every request made."""

    def __init__(self, responses: list[Response] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[tuple[str, str, object]] = []

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        self.requests.append(("GET", url, headers))
        return self._next()

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        self.requests.append(("POST", url, data))
        return self._next()

    def _next(self) -> Response:
        if not self.responses:
            raise AssertionError("FakeTransport ran out of scripted responses")
        return self.responses.pop(0)

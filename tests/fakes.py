"""Test doubles for the two injected boundaries. No test may use the real ones."""

from collections.abc import Mapping

from mldj.transport import Response


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

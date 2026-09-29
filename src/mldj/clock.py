"""The time boundary. Injected everywhere so tests never sleep.

This is the only module allowed to call time.time() or time.sleep().
Every timestamp in the project is an integer epoch millisecond.
"""

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...

    def sleep_ms(self, ms: int) -> None: ...


class SystemClock:
    """The real clock. Tests use tests.fakes.FakeClock instead."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep_ms(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000)

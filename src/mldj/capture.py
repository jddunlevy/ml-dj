"""Poll Spotify's currently-playing endpoint and append raw events to a session log.

Poll interval: the default is 1000 ms, against cd-player's 5000 ms, which collapses fast
skips and multi-skip bursts. At 1 request/second this makes 60 requests/minute, well
inside Spotify's rough 180/minute allowance. 1000 ms is a hypothesis, not a settled
value - `mldj report --diagnostics` (Task 12) is where it gets justified or changed.
"""

import argparse
import threading
from collections.abc import Callable

from mldj.clock import Clock, SystemClock
from mldj.env import load_env, require
from mldj.events import (
    EventWriter,
    gap_event,
    poll_event,
    session_end_event,
    session_id,
    session_path,
    session_start_event,
)
from mldj.nowplaying import ENDPOINT, parse_now_playing
from mldj.transport import DEFAULT_RETRY_MS, Transport, UrllibTransport, retry_after_ms

DEFAULT_INTERVAL_MS = 1000


def run_capture(
    *,
    transport: Transport,
    clock: Clock,
    access_token: Callable[[], str],
    writer: EventWriter,
    label: str,
    sid: str,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    should_stop: Callable[[], bool],
) -> None:
    """Poll until should_stop() is true, writing one event per poll.

    access_token is a callable rather than a string because a multi-hour session outlives
    a one-hour token; token_provider refreshes behind this call.
    """
    writer.write(session_start_event(clock.now_ms(), label, interval_ms, sid))
    reason = "stopped"
    try:
        while not should_stop():
            now = clock.now_ms()
            response = transport.get(ENDPOINT, {"Authorization": f"Bearer {access_token()}"})

            if response.status == 429:
                wait_ms = retry_after_ms(response)
                writer.write(gap_event(now, "rate-limited", wait_ms))
                clock.sleep_ms(wait_ms)
                continue
            if response.status == 204:
                writer.write(poll_event(None, now))
            elif response.status == 200:
                writer.write(poll_event(parse_now_playing(response.json(), now), now))
            else:
                writer.write(gap_event(now, f"http-{response.status}", DEFAULT_RETRY_MS))
                clock.sleep_ms(DEFAULT_RETRY_MS)
                continue

            clock.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        reason = "interrupted"
        raise
    except Exception:
        reason = "error"
        raise
    finally:
        writer.write(session_end_event(clock.now_ms(), reason))


def _run(args: argparse.Namespace) -> int:
    from mldj.auth import token_provider

    client_id = require(load_env(), "SPOTIFY_CLIENT_ID")
    transport = UrllibTransport()
    clock = SystemClock()
    sid = session_id(clock.now_ms())
    path = session_path(args.label, sid)
    stop = threading.Event()

    print(f"capturing to {path} every {args.interval_ms} ms - Ctrl-C to stop")
    with EventWriter(path) as writer:
        try:
            run_capture(
                transport=transport,
                clock=clock,
                access_token=token_provider(transport, clock, client_id),
                writer=writer,
                label=args.label,
                sid=sid,
                interval_ms=args.interval_ms,
                should_stop=stop.is_set,
            )
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("capture", help="record a listening session to data/sessions/")
    parser.add_argument(
        "--label",
        required=True,
        help="what was playing, e.g. dj - sessions are labeled by hand, never inferred",
    )
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    parser.set_defaults(handler=_run)

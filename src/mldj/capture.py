"""Poll Spotify's currently-playing endpoint and append raw events to a session log.

Poll interval: the default is 500 ms, and it is now settled by measurement rather than
assumed. The first three dj captures declared 1000 ms and `mldj report --diagnostics`
returned "too slow": the shortest observed gap between track changes was 1129 ms, and the
verdict rule flags any interval whose double reaches that gap, because the change then
lands inside the polling resolution and fast skips collapse into one another. Clearing it
requires an interval under ~564 ms.

500 ms rather than lower: at 2 requests/second the loop makes 120 requests/minute against
Spotify's rough 180/minute allowance, keeping a third in reserve for the token refresh and
retries. A 429 is a hole in the record, which is worse than coarse resolution - missing
data rather than quantized data - so the remaining headroom is not worth trading for
margin against the verdict rule.

The 1129 ms figure is the minimum over the sessions captured so far, so a future session
with a faster change could reopen the question. Re-read the verdict after each capture;
it is printed by `mldj report --diagnostics-only`.
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

DEFAULT_INTERVAL_MS = 500


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

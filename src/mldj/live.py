"""Keep the prototype's inputs current while a capture is running.

`mldj capture` already polls Spotify once a second. Nothing needs to poll twice, and R
must not: `skips.derive_plays` owns the completed / skipped / unknown decision, including
everything it refuses to decide, and a second implementation in another language is a
second thing to be wrong. So live mode is not a second poller. It is a loop that notices
the capture log got longer, re-runs the derivation that already exists, and writes the
result where Shiny is watching.

Two files refresh on two different triggers, because they cost two very different things:

  session.json     a local write, redone whenever the event list changes
  candidates.json  a few dozen Last.fm round trips, redone only when a new artist appears

Both land on stable names. A session-stamped filename would force an app restart every
time a new capture began, which is the thing live mode exists to avoid.
"""

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mldj.candidates import write_pool
from mldj.events import SESSIONS_DIR
from mldj.export import write_session

LIVE_DIR = Path("data/live")  # gitignored; derived from captured listening
DEFAULT_INTERVAL_S = 4.0

BuildEvents = Callable[[Path], list[dict[str, Any]]]
BuildPool = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


@dataclass(frozen=True)
class Refresh:
    events: list[dict[str, Any]]
    session_written: bool
    candidates_written: bool


def newest_log(sessions_dir: Path) -> Path | None:
    """The capture currently being written, or None if nothing has been captured.

    Modification time rather than filename order: a session id sorts chronologically, but
    an older log that is still being appended to is the live one.
    """
    logs = list(Path(sessions_dir).glob("*.jsonl"))
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)


def target_log(sessions_dir: Path, pinned: Path | None) -> Path | None:
    """The log to follow: the pinned one if given, otherwise whatever is newest.

    `newest_log` is right while a single capture runs, but it tracks whatever was written
    last - so restarting a capture silently moves the app off a session you were still
    looking at. A pin that does not exist raises rather than falling back, because quietly
    following the newest log after a typo is the exact surprise the pin exists to prevent.
    """
    if pinned is None:
        return newest_log(sessions_dir)
    pinned = Path(pinned)
    if not pinned.exists():
        raise FileNotFoundError(f"no capture log at {pinned}")
    return pinned


def new_artists(
    previous: Iterable[dict[str, Any]] | None, current: Iterable[dict[str, Any]]
) -> set[str]:
    """Artists in `current` that `previous` had not seen. No previous run means all of them."""
    seen = {e["artist"] for e in previous} if previous is not None else set()
    return {e["artist"] for e in current} - seen


def _label_of(log: Path) -> str:
    """The capture's label, read off the filename rather than re-parsing the log.

    `session_path` builds these as `<label>-<session id>.jsonl`, and the session id never
    contains a hyphen, so the last one splits it.
    """
    stem = log.stem
    return stem.rsplit("-", 1)[0] if "-" in stem else "unknown"


def refresh(
    *,
    log: Path,
    out_dir: Path,
    build_events: BuildEvents,
    build_pool: BuildPool,
    previous: list[dict[str, Any]] | None,
) -> Refresh:
    """One pass. Derives the log, writes only what actually changed."""
    events = build_events(log)
    if previous is not None and events == previous:
        return Refresh(events=events, session_written=False, candidates_written=False)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_session(out_dir / "session.json", log.stem, _label_of(log), events)

    if not new_artists(previous, events):
        return Refresh(events=events, session_written=True, candidates_written=False)

    write_pool(out_dir / "candidates.json", log.stem, build_pool(events))
    return Refresh(events=events, session_written=True, candidates_written=True)


def _run(args: argparse.Namespace) -> int:
    import time

    from mldj.candidates import candidate_pool
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.export import session_events
    from mldj.lastfm import LastfmClient, artist_top_tags_cached, top_tags_cached
    from mldj.match import track_key
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.skips import load_plays
    from mldj.transport import UrllibTransport

    env = load_env()
    client = LastfmClient(UrllibTransport(), SystemClock(), require(env, "LASTFM_API_KEY"))
    history = build_history(read_scrobbles(SCROBBLES_PATH))

    def tags_for(artist: str, title: str) -> list[str]:
        return [name for name, _count in top_tags_cached(client, artist, title)]

    def artist_tags_for(artist: str) -> list[str]:
        return [name for name, _count in artist_top_tags_cached(client, artist)]

    def was_heard(artist: str, title: str) -> bool:
        return track_key(artist, title) in history.keys

    def similar_for(artist: str) -> list[tuple[str, str]]:
        data = client.call("artist.getSimilar", artist=artist, autocorrect="1", limit="20")
        rows = ((data.get("similarartists") or {}).get("artist")) or []
        out: list[tuple[str, str]] = []
        for row in rows:
            name = str(row.get("name") or "")
            if not name:
                continue
            top = client.call("artist.getTopTracks", artist=name, autocorrect="1", limit="5")
            for t in ((top.get("toptracks") or {}).get("track")) or []:
                if t.get("name"):
                    out.append((name, str(t["name"])))
        return out

    def build_events(log: Path) -> list[dict[str, Any]]:
        return session_events(load_plays([log]), tags_for, was_heard, artist_tags_for)

    def build_pool(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return candidate_pool(events, similar_for, tags_for, was_heard, artist_tags_for)

    out_dir = Path(args.out)
    pinned = Path(args.log) if args.log else None
    following = f"pinned to {pinned.name}" if pinned else f"watching {args.sessions}"
    print(f"{following} -> {out_dir} every {args.interval_s}s - Ctrl-C to stop")

    previous: list[dict[str, Any]] | None = None
    watching: Path | None = None
    try:
        while True:
            log = target_log(Path(args.sessions), pinned)
            if log is None:
                print("no capture log yet - start `mldj capture --label dj`")
                time.sleep(args.interval_s)
                continue
            if log != watching:
                # A new capture started. Everything is new again, pool included.
                print(f"following {log.name}")
                watching, previous = log, None

            # A watcher that runs for hours must outlive a bad pass. A Last.fm 500 or a
            # half-written log is a reason to try again in a few seconds, not to stop
            # updating the app. `previous` is left alone so the next pass retries the same
            # work rather than treating the failed refresh as done.
            try:
                result = refresh(
                    log=log,
                    out_dir=out_dir,
                    build_events=build_events,
                    build_pool=build_pool,
                    previous=previous,
                )
            except Exception as err:  # noqa: BLE001 - deliberate: keep watching
                print(f"refresh failed, retrying: {err}")
                time.sleep(args.interval_s)
                continue

            if result.session_written:
                note = " + candidates" if result.candidates_written else ""
                print(f"{len(result.events)} events{note}")
            previous = result.events
            time.sleep(args.interval_s)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("live", help="keep the prototype's inputs current while capturing")
    p.add_argument("--sessions", default=str(SESSIONS_DIR), help="directory of capture logs")
    p.add_argument(
        "--log",
        help="follow this capture log instead of whichever is newest - use it to keep the "
        "app on one session while another capture is running",
    )
    p.add_argument("--out", default=str(LIVE_DIR), help="where Shiny watches for JSON")
    p.add_argument("--interval-s", type=float, default=DEFAULT_INTERVAL_S)
    p.set_defaults(handler=_run)

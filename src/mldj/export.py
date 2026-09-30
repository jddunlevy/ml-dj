"""Derived session events, for the R prototype to replay.

R never parses raw polls and never re-implements skip detection. `skips.derive_plays` already
does that and is tested; a second implementation in another language is a second thing to be
wrong. This module is the boundary: plays in, the prototype's event shape out.

Tags are canonicalized here rather than in R, so the prototype's tag strings are the same
strings `space.json` holds and a lookup cannot silently miss.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mldj.match import track_key
from mldj.skips import Play, load_plays
from mldj.space.vocab import canonical_tag

EXPORT_DIR = Path("data/exports")  # gitignored; derived from captured listening

TagsFor = Callable[[str, str], list[str]]
WasHeard = Callable[[str, str], bool]


def earliness_of(play: Play) -> float:
    """How early the listener bailed: 1.0 is instant, 0.0 is played through.

    A completed track is always 0.0 regardless of arithmetic - some sources report a
    listened_ms slightly under duration_ms, and that must not read as a partial rejection.
    """
    if play.outcome != "skipped":
        return 0.0
    return max(0.0, min(1.0, 1.0 - play.listened_fraction))


def session_events(
    plays: Iterable[Play], tags_for: TagsFor, was_heard: WasHeard | None = None
) -> list[dict[str, Any]]:
    """The prototype's event list, in chronological order.

    `novel` is an upper bound while the scrobble history has its 64-day hole: a track first
    heard inside it reads as never-heard. With no history supplied everything reads novel,
    which is the honest default for a caller that has not provided one.
    """
    events = []
    for play in plays:
        tags = [canonical_tag(t) for t in tags_for(play.artist, play.title)]
        heard = was_heard(play.artist, play.title) if was_heard is not None else False
        events.append(
            {
                "ts": play.started_at_ms,
                "artist": play.artist,
                "title": play.title,
                # Pairs with the key on each candidate. Raw strings stay untouched for
                # display; this is the only thing the two sources are ever joined on.
                "key": list(track_key(play.artist, play.title)),
                "tags": [t for t in tags if t],
                "outcome": play.outcome,
                "earliness": round(earliness_of(play), 4),
                "novel": not heard,
                "duration_ms": play.duration_ms,
                "listened_ms": play.listened_ms,
            }
        )
    return events


def write_session(path: Path, session: str, label: str, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"session": session, "label": label, "events": events}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.lastfm import LastfmClient, top_tags_cached
    from mldj.transport import UrllibTransport

    paths = sorted(Path(args.sessions).glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"no capture logs in {args.sessions} - run `mldj capture` first")

    env = load_env()
    client = LastfmClient(UrllibTransport(), SystemClock(), require(env, "LASTFM_API_KEY"))

    def tags_for(artist: str, title: str) -> list[str]:
        return [name for name, _count in top_tags_cached(client, artist, title)]

    from mldj.match import track_key
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles

    history = build_history(read_scrobbles(SCROBBLES_PATH))

    def was_heard(artist: str, title: str) -> bool:
        return track_key(artist, title) in history.keys

    for path in paths:
        plays = load_plays([path])
        events = session_events(plays, tags_for, was_heard)
        out = Path(args.out) / f"{path.stem}.json"
        label = plays[0].label if plays else "unknown"
        write_session(out, path.stem, label, events)
        skipped = sum(1 for e in events if e["outcome"] == "skipped")
        print(f"{out}: {len(events)} events, {skipped} skipped")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("export-session", help="derived session events for the prototype")
    p.add_argument("--sessions", default="data/sessions", help="directory of capture logs")
    p.add_argument("--out", default=str(EXPORT_DIR), help="where to write the JSON")
    p.set_defaults(handler=_run)

"""The candidate pool, prefetched offline.

Shiny never calls Last.fm. Prefetching keeps the demo deterministic - no rate limit, no
network, no 500 during a presentation - and keeps the R dependency set small enough that the
pitch does not depend on an HTTP client in a second language.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mldj.match import track_key
from mldj.space.vocab import canonical_tag

CANDIDATES_DIR = Path("data/candidates")  # gitignored; derived from captured listening

SimilarFor = Callable[[str], list[tuple[str, str]]]
TagsFor = Callable[[str, str], list[str]]
WasHeard = Callable[[str, str], bool]


def candidate_pool(
    events: Iterable[dict[str, Any]],
    similar_for: SimilarFor,
    tags_for: TagsFor,
    was_heard: WasHeard | None = None,
    artist_tags_for: Callable[[str], list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Tracks reachable from the session's artists, minus everything already played.

    An untagged candidate is dropped rather than kept with an empty tag list: it can never be
    scored, so keeping it only inflates the denominator of "ranked Nth of M".

    Seeds are the session's DISTINCT artists, in first-appearance order. Iterating events
    directly would call similar_for once per event, and a session plays the same artist more
    than once; the `seen` set already made the repeat calls produce nothing, so they bought
    nothing but latency. Under _run each call fans out to ~21 Last.fm requests, so on a
    30-event session with repeats this is the difference between a prefetch that finishes and
    one that trips the rate limit. Output is unchanged - first-appearance order means the
    surviving candidates and their order are identical either way.
    """
    events = list(events)
    played = {(e["artist"], e["title"]) for e in events}
    seeds = list(dict.fromkeys(e["artist"] for e in events))
    seen: set[tuple[str, str]] = set()
    pool: list[dict[str, Any]] = []

    for seed in seeds:
        for artist, title in similar_for(seed):
            key = (artist, title)
            if key in played or key in seen:
                continue
            seen.add(key)
            tags = [canonical_tag(t) for t in tags_for(artist, title)]
            tags = [t for t in tags if t]
            tier = "track"
            if not tags and artist_tags_for is not None:
                # Same 24.5%-vs-95% backoff the session events use. Without it the pool is
                # mostly untagged, and an untagged candidate is dropped - so the pool would
                # silently shrink to the quarter of tracks Last.fm happens to tag directly.
                tags = [canonical_tag(t) for t in artist_tags_for(artist)]
                tags = [t for t in tags if t]
                tier = "artist"
            if not tags:
                continue
            heard = was_heard(artist, title) if was_heard is not None else False
            pool.append(
                {
                    "artist": artist,
                    "title": title,
                    # The normalized join key travels with the row. These strings come from
                    # Last.fm; the session's come from Spotify capture, and R joins the two to
                    # flag the DJ's actual pick. R has no matcher and must not grow one -
                    # a second implementation of match.py is free to drift from this one, and
                    # a silent join failure reads as "the pick was not in the pool", which is
                    # the pitch's headline claim quietly disappearing.
                    "key": list(track_key(artist, title)),
                    "tags": tags,
                    "tier": tier,
                    "novel": not heard,
                }
            )
    return pool


def write_pool(path: Path, session: str, pool: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session": session, "candidates": pool}, indent=1), encoding="utf-8"
    )


def _run(args: argparse.Namespace) -> int:
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.lastfm import LastfmClient, artist_top_tags_cached, top_tags_cached
    from mldj.match import track_key
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.transport import UrllibTransport

    export = Path(args.session)
    if not export.exists():
        raise SystemExit(f"no export at {export} - run `mldj export-session` first")
    payload = json.loads(export.read_text(encoding="utf-8"))

    env = load_env()
    client = LastfmClient(UrllibTransport(), SystemClock(), require(env, "LASTFM_API_KEY"))

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

    def tags_for(artist: str, title: str) -> list[str]:
        return [name for name, _count in top_tags_cached(client, artist, title)]

    def artist_tags_for(artist: str) -> list[str]:
        return [name for name, _count in artist_top_tags_cached(client, artist)]

    history = build_history(read_scrobbles(SCROBBLES_PATH))
    pool = candidate_pool(
        payload["events"],
        similar_for,
        tags_for,
        lambda a, t: track_key(a, t) in history.keys,
        artist_tags_for,
    )
    out = Path(args.out) / f"{payload['session']}.json"
    write_pool(out, payload["session"], pool)
    print(f"{out}: {len(pool)} candidates")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("candidates", help="prefetch a candidate pool for a session")
    p.add_argument("--session", required=True, help="path to a `mldj export-session` JSON file")
    p.add_argument("--out", default=str(CANDIDATES_DIR))
    p.set_defaults(handler=_run)

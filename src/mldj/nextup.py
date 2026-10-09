"""Choose the next track from the session vector and write it to the real queue.

This is the bridge the project was missing. `playback.queue_track` could write one track but
only to a URI handed to it by a person; `playlist.py` could choose tracks but only wrote them
to a new playlist. Neither closed the loop, so nothing in the repo could answer a skip with a
track you then actually hear.

Two decisions are recorded here rather than left to the caller.

**The pool is the library, not the candidate pool.** `data/candidates/*.json` carries
`artist, title, key, tags, tier, novel` and no `uri` - it is Last.fm similar-artist names, not
Spotify entities, so it cannot be queued from at all. The library is the only pool whose rows
can reach the wire, which is why the ranking here is `playlist.py`'s.

**An artist cooldown is not optional.** Artist-tier tags are identical for every track by an
artist, so each of them scores identically against the session vector, and the artist who just
played is by construction among the closest things in the space. Measured on the real 142116Z
session, the uncooled top pick repeats the just-played artist at 2 of 3 positions tested. The
default of 5 is not taste: Phase 0 measured the real DJ enforcing exactly that - 0 artist
repeats across 42 adjacent pairs and no return within 5 tracks - so this keeps the one thing
the product under teardown got right.
"""

import argparse
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mldj.engine import DEFAULT_DECAY, DEFAULT_W, session_new, session_run
from mldj.library import LIBRARY_PATH, ScorableTrack
from mldj.playback import queue_track
from mldj.playlist import exclude_played, rank_library, thin_by_artist
from mldj.space.space import TagSpace
from mldj.transport import Transport

QUEUED_PATH = Path("data/live/queued.json")  # the app reads this; data/ is gitignored
DEFAULT_COOLDOWN = 5  # Phase 0 measured the DJ's own rotation rule at exactly this

# The floor's job is to refuse a DEGENERATE vector, not to demand a strong one. Calibrated
# against two real captured sessions rather than guessed: a healthy moment scores 0.28-0.96,
# and a vector wrecked by three or more consecutive skips scores 0.008-0.10 (the abandoned
# Hall & Oates moment in the Phase 3 plan scored 0.061). 0.15 sits an order of magnitude above
# the degenerate band and well below the usable one. An earlier 0.25 was set from two data
# points and put a legitimate 0.279 moment one hundredth above refusing itself.
DEFAULT_MIN_SCORE = 0.15
DEFAULT_EPSILON = 0.0


@dataclass(frozen=True)
class Pick:
    """One track, with the numbers that justify it. `rank` is the true rank in the full pool."""

    uri: str
    artist: str
    title: str
    score: float
    rank: int
    novel: bool
    pool_size: int


@dataclass(frozen=True)
class Delivery:
    pick: Pick
    written: bool
    reason: str  # queued | dry-run | duplicate


# Capture records the credit exactly as Spotify gives it - "Stevie Nicks, Don Henley" - while
# the library row for the same track is "Stevie Nicks". Comparing those whole strings lets a
# multi-artist credit walk straight through artist rotation. Observed live on 2026-10-08: the
# engine picked the track that was playing at that moment, because neither the cooldown nor
# exclude_played could see that the two names referred to the same artist.
#
# Alternation is ordered, so `featuring` must precede `feat` or the longer word is split in
# half. No trailing \b after the optional dot either: there is no word boundary between the
# "." and the space in "feat. Akon", so `\bfeat\.?\b` matches nothing at all there.
_CREDIT_SPLIT = re.compile(r",|&|\bfeaturing\b|\bfeat\.?|\bft\.?", re.IGNORECASE)


def credit_parts(name: object) -> set[str]:
    """Every name a credit might be matched by, casefolded, including the whole credit.

    Applied to BOTH sides of the comparison, because the mismatch runs in either direction: a
    session can name two artists where the library names one, and a library row can name two
    where the session names one.

    Splitting a genuine band name ("Hall & Oates") into parts that are not artists is
    deliberate and harmless. It can only cool MORE artists than strictly necessary, and more
    rotation is the conservative direction for a rule whose whole purpose is variety.
    """
    raw = str(name or "").strip()
    if not raw:
        return set()
    parts = {raw.casefold()}
    for part in _CREDIT_SPLIT.split(raw):
        cleaned = part.strip().casefold()
        if cleaned:
            parts.add(cleaned)
    return parts


def recent_artists(events: Sequence[Mapping[str, object]], cooldown: int) -> set[str]:
    """Every name credited inside the cooldown window, casefolded.

    Casefolded because the pool's strings come from Spotify and the events' from the capture
    log; a capitalisation difference must not be allowed to defeat the rule silently.
    """
    if cooldown <= 0:
        return set()
    cooled: set[str] = set()
    for event in events[-cooldown:]:
        cooled |= credit_parts(event.get("artist"))
    return cooled


def choose_next(
    space: TagSpace,
    events: Sequence[Mapping[str, object]],
    pool: Sequence[ScorableTrack],
    *,
    decay: float = DEFAULT_DECAY,
    w: float = DEFAULT_W,
    epsilon: float = DEFAULT_EPSILON,
    cooldown: int = DEFAULT_COOLDOWN,
    min_score: float = DEFAULT_MIN_SCORE,
) -> Pick | None:
    """The engine's pick, or None when it should decline to pick at all.

    None is a real answer, not a failure. A session vector decayed to near zero scores its best
    candidate at 0.06, and queueing on that is the engine performing confidence it does not
    have - the exact failure this project diagnoses in the product it is tearing down. The
    floor makes declining the default rather than an act of restraint.
    """
    state = session_run(session_new(space, decay=decay, w=w), events)
    if float(np.linalg.norm(state.v)) == 0.0:
        return None

    cooled = recent_artists(events, cooldown)
    eligible = [t for t in exclude_played(pool, events) if not (credit_parts(t.artist) & cooled)]
    if not eligible:
        return None

    ranked = rank_library(space, state.v, eligible, epsilon=epsilon)
    top = thin_by_artist(ranked, limit=1, per_artist=1)
    if not top or top[0].score < min_score:
        return None

    row = top[0]
    return Pick(
        uri=row.uri,
        artist=row.artist,
        title=row.title,
        score=row.score,
        rank=row.rank,
        novel=row.novel,
        pool_size=len(eligible),
    )


def _read_last(state_path: Path) -> str | None:
    if not state_path.exists():
        return None
    try:
        return str(json.loads(state_path.read_text("utf-8")).get("uri") or "") or None
    except (ValueError, OSError):
        return None  # a corrupt state file must not block a write


def _record(state_path: Path, pick: Pick) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "uri": pick.uri,
                "artist": pick.artist,
                "title": pick.title,
                "score": round(pick.score, 4),
                "rank": pick.rank,
                "pool_size": pick.pool_size,
                "novel": pick.novel,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def deliver(
    transport: Transport,
    access_token: Callable[[], str],
    pick: Pick,
    *,
    dry_run: bool = False,
    force: bool = False,
    state_path: Path = QUEUED_PATH,
    on_unauthorized: Callable[[], None] | None = None,
) -> Delivery:
    """Write the pick to the queue, once. Returns what actually happened.

    The duplicate guard exists because the queue is append-only - Spotify exposes no remove -
    so a second press of the same command is permanent and audible. It keys on the URI alone:
    queueing the same track twice in a row is never what was meant.

    A failed write is deliberately not recorded, or the guard would block the retry of a write
    that never landed. Errors from `queue_track` surface unchanged; a 404 means there is no
    active device, which is the demo's premise missing rather than a condition to paper over.
    """
    if dry_run:
        return Delivery(pick, False, "dry-run")
    if not force and _read_last(state_path) == pick.uri:
        return Delivery(pick, False, "duplicate")

    queue_track(transport, access_token, pick.uri, on_unauthorized)
    _record(state_path, pick)
    return Delivery(pick, True, "queued")


def _run(args: argparse.Namespace) -> int:
    from mldj.auth import token_provider
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.library import cached_tag_index, read_library, tag_library
    from mldj.measure.novelty import build_history
    from mldj.playlist import force_refresh
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.space.space import DEFAULT_SPACE_PATH, EXCLUDED_TERMS, load_space
    from mldj.transport import UrllibTransport

    session = Path(args.session)
    if not session.exists():
        raise SystemExit(f"no session at {session} - is `mldj live` running?")
    events = json.loads(session.read_text("utf-8"))["events"]

    space = load_space(DEFAULT_SPACE_PATH, exclude=EXCLUDED_TERMS)
    tracks = read_library(Path(args.library))
    scrobbles = list(read_scrobbles(SCROBBLES_PATH))
    track_tags, artist_tags = cached_tag_index(tracks, scrobbles=scrobbles)
    history = build_history(scrobbles)
    scorable, _ = tag_library(
        tracks, track_tags, artist_tags, lambda a, t: history.contains(a, t)
    )

    pick = choose_next(
        space,
        events,
        scorable,
        decay=args.decay,
        w=args.w,
        epsilon=args.epsilon,
        cooldown=args.cooldown,
        min_score=args.min_score,
    )
    last = events[-1] if events else {}
    print(f"session: {len(events)} events, last {last.get('outcome')} "
          f"{last.get('artist')} - {last.get('title')}")

    if pick is None:
        print(
            f"declined: nothing clears min-score {args.min_score} on this vector. "
            "The session is too weak to justify a pick - that is an answer, not an error."
        )
        return 0

    flag = "  *novel" if pick.novel else ""
    print(f"pick: {pick.score:+.4f}  {pick.artist} - {pick.title}{flag}")
    print(f"      rank {pick.rank} of {pick.pool_size} eligible (cooldown {args.cooldown})")

    transport = UrllibTransport()
    clock = SystemClock()
    client_id = require(load_env(), "SPOTIFY_CLIENT_ID")
    access_token = token_provider(transport, clock, client_id)

    result = deliver(
        transport,
        access_token,
        pick,
        dry_run=args.dry_run,
        force=args.force,
        state_path=Path(args.state),
        on_unauthorized=lambda: force_refresh(transport, clock, client_id),
    )
    if result.reason == "dry-run":
        print("--dry-run: nothing queued")
    elif result.reason == "duplicate":
        print("already queued this track - pass --force to queue it again")
    else:
        print(f"queued {pick.uri}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("next", help="queue the engine's next pick for a live session")
    p.add_argument("--session", default="data/live/session.json")
    p.add_argument("--library", default=str(LIBRARY_PATH))
    p.add_argument("--state", default=str(QUEUED_PATH))
    p.add_argument("--cooldown", type=int, default=DEFAULT_COOLDOWN)
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--decay", type=float, default=DEFAULT_DECAY)
    p.add_argument("--w", type=float, default=DEFAULT_W)
    p.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    p.add_argument("--dry-run", action="store_true", help="print the pick, queue nothing")
    p.add_argument("--force", action="store_true", help="override the duplicate guard")
    p.set_defaults(handler=_run)

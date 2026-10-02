"""Rank a library against a session vector and write the result as a new playlist.

The ranking uses the session's FINAL vector: one vector, one playlist. A per-step variant -
each track chosen against the vector as it stood - would narrate the session rather than
summarise it, and is the spec's deferred open question rather than an oversight.
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from mldj.engine import DEFAULT_DECAY, DEFAULT_W, tag_vector
from mldj.library import LIBRARY_PATH, ScorableTrack
from mldj.match import track_key
from mldj.space.space import TagSpace
from mldj.transport import Response, Transport

DEFAULT_LIMIT = 30
DEFAULT_PER_ARTIST = 2
DEFAULT_EPSILON = 0.0


@dataclass(frozen=True)
class Ranked:
    rank: int
    uri: str
    artist: str
    title: str
    score: float
    novel: bool


def exclude_played(
    tracks: Sequence[ScorableTrack], events: Sequence[Mapping[str, object]]
) -> list[ScorableTrack]:
    """The pool, minus every track the session played.

    Joined on the normalized key both sides already carry, so a remaster suffix cannot smuggle
    a just-skipped track back into the playlist.
    """
    played = {tuple(event.get("key") or ()) for event in events}
    return [t for t in tracks if track_key(t.artist, t.title) not in played]


def rank_library(
    space: TagSpace,
    v: np.ndarray,
    tracks: Sequence[ScorableTrack],
    epsilon: float = DEFAULT_EPSILON,
) -> list[Ranked]:
    """Every track scored by cosine against v, plus epsilon for a novel one, descending.

    Ties keep the pool's order - Python's sort is stable - so two runs on one session produce
    the same playlist. Novelty is an upper bound while the scrobble hole stands, so epsilon
    amplifies a number that is already generous: default it to zero.
    """
    norm = float(np.linalg.norm(v))
    scored: list[Ranked] = []
    for track in tracks:
        cv = tag_vector(space, track.tags)
        cnorm = float(np.linalg.norm(cv))
        cos = 0.0 if norm == 0 or cnorm == 0 else float(cv @ v / (cnorm * norm))
        scored.append(
            Ranked(
                0, track.uri, track.artist, track.title, cos + epsilon * track.novel,
                track.novel,
            )
        )
    ordered = sorted(scored, key=lambda r: -r.score)
    return [
        Ranked(i + 1, r.uri, r.artist, r.title, r.score, r.novel)
        for i, r in enumerate(ordered)
    ]


def thin_by_artist(ranked: Sequence[Ranked], limit: int, per_artist: int) -> list[Ranked]:
    """At most `per_artist` tracks by any one artist, then at most `limit` rows.

    Artist-tier tags are identical for every track by that artist, so every such track scores
    identically and a stable sort keeps the whole block together. Without this cap a 30-track
    playlist comes from six artists - the prototype measured exactly that on a real pool.

    Ranks are the true ones from the full pool. Renumbering would erase the gaps, and the gaps
    are the tie structure made visible.
    """
    counts: dict[str, int] = {}
    kept: list[Ranked] = []
    for row in ranked:
        if counts.get(row.artist, 0) >= per_artist:
            continue
        counts[row.artist] = counts.get(row.artist, 0) + 1
        kept.append(row)
        if len(kept) == limit:
            break
    return kept


API = "https://api.spotify.com/v1"
ADD_CHUNK = 100  # Spotify's per-request ceiling for playlist additions
WRITE_SCOPES = "playlist-modify-private, user-library-read, user-top-read"


class PlaylistError(RuntimeError):
    pass


def _headers(access_token: Callable[[], str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token()}"}


def _check(response: Response, url: str) -> Response:
    if response.status == 403:
        raise PlaylistError(
            f"403 Forbidden from {url}. This is almost always a missing scope rather than a "
            f"bad request: the token needs {WRITE_SCOPES}. Widening SCOPE invalidates the "
            "cached token, so delete data/.spotify-tokens.json and re-run to re-authorize - "
            "between capture sessions, never during one."
        )
    if response.status >= 400 or response.status == 0:
        raise PlaylistError(f"{response.status} from {url}: {response.body[:200]!r}")
    return response


def _post_json(
    transport: Transport,
    access_token: Callable[[], str],
    url: str,
    payload: Mapping[str, object],
    on_unauthorized: Callable[[], None] | None = None,
) -> Response:
    """POST, refreshing and retrying exactly once on a 401.

    Once, not in a loop: a 401 that survives a refresh is a bad or revoked token, and retrying
    further only hides that behind a hang.
    """
    response = transport.post_json(url, payload, _headers(access_token))
    if response.status == 401 and on_unauthorized is not None:
        on_unauthorized()
        response = transport.post_json(url, payload, _headers(access_token))
    return _check(response, url)


def current_user_id(transport: Transport, access_token: Callable[[], str]) -> str:
    """The account's id, needed to address the playlist-creation endpoint.

    If this ever 403s, the token is missing `user-read-private`; add it to auth.SCOPE rather
    than guessing at the playlist endpoint.
    """
    url = f"{API}/me"
    payload = _check(transport.get(url, _headers(access_token)), url).json()
    if not isinstance(payload, dict) or not payload.get("id"):
        raise PlaylistError(f"{url} returned no id")
    return str(payload["id"])


def playlist_description(
    session: str,
    pool_size: int,
    decay: float,
    w: float,
    epsilon: float,
    meta: Mapping[str, object],
) -> str:
    """Provenance, in the one field that travels with the playlist.

    A playlist that cannot say which space produced it is not reproducible, and the space is
    rebuilt often enough for that to matter.
    """
    built = str(meta.get("built_utc", "unknown"))
    return (
        f"ml-dj · session {session}; pool {pool_size}; decay {decay}, w {w}, "
        f"epsilon {epsilon}; space {meta.get('vocabulary_size', '?')} terms built {built}"
    )


def create_playlist(
    transport: Transport,
    access_token: Callable[[], str],
    user_id: str,
    name: str,
    description: str,
    on_unauthorized: Callable[[], None] | None = None,
) -> str:
    """Create a NEW private playlist and return its id.

    Never updates an existing playlist. Appending to or rewriting one the listener may have
    edited is destructive with no undo, and the saving in clutter does not buy that class of
    bug.
    """
    url = f"{API}/users/{user_id}/playlists"
    payload = {"name": name, "public": False, "description": description}
    body = _post_json(transport, access_token, url, payload, on_unauthorized).json()
    if not isinstance(body, dict) or not body.get("id"):
        raise PlaylistError(f"{url} returned no playlist id")
    return str(body["id"])


def add_tracks(
    transport: Transport,
    access_token: Callable[[], str],
    playlist_id: str,
    uris: Sequence[str],
    on_unauthorized: Callable[[], None] | None = None,
) -> int:
    """Add the URIs in order, chunked at the API's limit. Returns how many were added."""
    url = f"{API}/playlists/{playlist_id}/tracks"
    for start in range(0, len(uris), ADD_CHUNK):
        chunk = list(uris[start : start + ADD_CHUNK])
        _post_json(transport, access_token, url, {"uris": chunk}, on_unauthorized)
    return len(uris)


def publish_playlist(
    transport: Transport,
    access_token: Callable[[], str],
    *,
    name: str,
    description: str,
    uris: Sequence[str],
    dry_run: bool,
    on_unauthorized: Callable[[], None] | None = None,
) -> str | None:
    """The whole write, or nothing at all. Returns the playlist id, or None for a dry run.

    `dry_run` lives here rather than in the argparse handler so that "a dry run makes neither
    call" is a test rather than a promise - it is the guard the spec leans on when it makes
    --dry-run opt-in rather than the default.
    """
    if dry_run:
        return None
    user_id = current_user_id(transport, access_token)
    playlist_id = create_playlist(
        transport, access_token, user_id, name, description, on_unauthorized
    )
    add_tracks(transport, access_token, playlist_id, uris, on_unauthorized)
    return playlist_id


def force_refresh(transport: Transport, clock, client_id: str, path=None) -> None:
    """Refresh the access token now, rather than waiting for the expiry margin.

    token_provider refreshes on a clock; a 401 mid-run means the token is dead regardless of
    what the clock says.
    """
    from mldj.auth import TOKENS_PATH, load_tokens, refresh_tokens, save_tokens

    path = TOKENS_PATH if path is None else path
    tokens = load_tokens(path)
    if tokens is None:
        raise PlaylistError("no cached token to refresh - run any command to authorize")
    save_tokens(refresh_tokens(transport, clock, client_id, tokens), path)


def _run(args) -> int:
    import json
    from pathlib import Path

    from mldj.auth import token_provider
    from mldj.clock import SystemClock
    from mldj.engine import session_new, session_run
    from mldj.env import load_env, require
    from mldj.library import (
        cached_tag_index,
        fetch_library,
        read_library,
        render_coverage,
        tag_library,
        write_library,
    )
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.space.space import DEFAULT_SPACE_PATH, EXCLUDED_TERMS, load_space
    from mldj.transport import UrllibTransport

    export = Path(args.session)
    if not export.exists():
        raise SystemExit(f"no export at {export} - run `mldj export-session` first")
    payload = json.loads(export.read_text(encoding="utf-8"))
    events = payload["events"]

    space = load_space(DEFAULT_SPACE_PATH, exclude=EXCLUDED_TERMS)
    transport = UrllibTransport()
    clock = SystemClock()
    env = load_env()
    client_id = require(env, "SPOTIFY_CLIENT_ID")
    access_token = token_provider(transport, clock, client_id)

    library_path = Path(args.library)
    if args.refresh_library or not library_path.exists():
        tracks = fetch_library(transport, access_token)
        write_library(library_path, tracks)
        print(f"{library_path}: {len(tracks)} library tracks")
    else:
        tracks = read_library(library_path)
        print(
            f"{library_path}: {len(tracks)} library tracks "
            "(cached; --refresh-library to refetch)"
        )

    # The corpus is passed in so the track-tier index is keyed by track_key rather than by
    # the library's own Spotify strings - without it, a remaster suffix misses a cache entry
    # that is sitting on disk and the row falls back to the artist tier, where every track by
    # that artist scores identically. See the scope addition under Task 5.
    scrobbles = list(read_scrobbles(SCROBBLES_PATH))
    track_tags, artist_tags = cached_tag_index(tracks, scrobbles=scrobbles)
    history = build_history(scrobbles)
    scorable, coverage = tag_library(
        tracks, track_tags, artist_tags, lambda a, t: history.contains(a, t)
    )
    # Coverage before ranking, per the spec: a thin pool must be visible here rather than
    # inferred later from a disappointing playlist.
    print(render_coverage(coverage))

    pool = exclude_played(scorable, events)
    outcomes = Counter(str(e.get("outcome")) for e in events)
    print(f"session {payload['session']}: {len(events)} events {dict(outcomes)}")
    print(f"pool: {len(pool)} candidates after dropping what the session played")

    state = session_run(session_new(space, decay=args.decay, w=args.w), events)
    ranked = rank_library(space, state.v, pool, epsilon=args.epsilon)
    chosen = thin_by_artist(ranked, limit=args.limit, per_artist=args.per_artist)

    for row in chosen:
        flag = " *novel" if row.novel else ""
        print(f"  {row.rank:>4}  {row.score:+.4f}  {row.artist} - {row.title}{flag}")

    if args.dry_run:
        print(f"--dry-run: {len(chosen)} tracks, nothing created")
        return 0

    name = args.name or f"ml-dj · {payload['session']}"
    description = playlist_description(
        payload["session"], len(pool), args.decay, args.w, args.epsilon, space.meta
    )

    def on_unauthorized() -> None:
        force_refresh(transport, clock, client_id)

    playlist_id = publish_playlist(
        transport,
        access_token,
        name=name,
        description=description,
        uris=[r.uri for r in chosen],
        dry_run=False,
        on_unauthorized=on_unauthorized,
    )
    print(
        f"created {name}: {len(chosen)} tracks - "
        f"https://open.spotify.com/playlist/{playlist_id}"
    )
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("playlist", help="turn a session into a private playlist")
    p.add_argument("--session", required=True, help="path to a `mldj export-session` JSON file")
    p.add_argument("--name", default=None, help="playlist name; default ml-dj · <session>")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--per-artist", type=int, default=DEFAULT_PER_ARTIST)
    p.add_argument("--decay", type=float, default=DEFAULT_DECAY)
    p.add_argument("--w", type=float, default=DEFAULT_W)
    p.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    p.add_argument("--library", default=str(LIBRARY_PATH))
    p.add_argument("--refresh-library", action="store_true", help="refetch instead of caching")
    p.add_argument("--dry-run", action="store_true", help="print the tracklist, create nothing")
    p.set_defaults(handler=_run)

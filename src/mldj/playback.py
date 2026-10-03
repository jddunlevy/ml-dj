"""Playback control: write the next track to Spotify's queue.

This is the one thing the rest of the project never does. Everything else here reads -
capture polls, the engine scores, Shiny renders - and a recommender that cannot place a
track is a recommender nobody hears. `mldj queue` is the smallest honest proof that the
loop can close: one track, one call, visible in the real client.

The queue is append-only. Spotify exposes no remove-from-queue, so whatever is written is
committed unless the listener skips past it. That is the central design constraint on
Phase 4's queue depth, not an incidental API limitation - see the queue-depth question in
the spec before queueing more than one track ahead.
"""

import urllib.parse
from collections.abc import Callable, Mapping

from mldj.transport import Response, Transport

API = "https://api.spotify.com/v1"


class PlaybackError(RuntimeError):
    pass


def _headers(access_token: Callable[[], str]) -> Mapping[str, str]:
    return {"Authorization": f"Bearer {access_token()}"}


def queue_url(uri: str) -> str:
    """Spotify takes the track on the query string. A raw `spotify:track:` colon is not
    query-safe, so quote it rather than relying on the server to be lenient."""
    return f"{API}/me/player/queue?uri={urllib.parse.quote(uri, safe='')}"


def _check(response: Response, url: str) -> Response:
    """Raise on failure, quoting Spotify rather than guessing at a cause.

    playlist.py asserts "this is almost always a missing scope" for every 403. It was wrong
    - the real cause was a retired endpoint - and the assertion sent a debugging session
    after a scope that was already granted. A diagnosis the caller cannot check is worse
    than no diagnosis, so the body goes in verbatim.
    """
    if response.status == 404:
        raise PlaybackError(
            f"404 from {url}: no active device. Spotify can only queue to a device that is "
            f"already playing - start playback on your phone or desktop, then retry. "
            f"Spotify said: {response.body[:300]!r}"
        )
    if response.status == 401:
        raise PlaybackError(
            f"401 from {url} even after refreshing. A refresh mints a new access token "
            "carrying the scopes you last CONSENTED to, so it cannot add a scope that "
            "SCOPE gained since. Re-authorize: delete data/.spotify-tokens.json and re-run "
            f"to get the consent screen again. Spotify said: {response.body[:300]!r}"
        )
    if response.status >= 400 or response.status == 0:
        raise PlaybackError(f"{response.status} from {url}. Spotify said: {response.body[:300]!r}")
    return response


def queue_track(
    transport: Transport,
    access_token: Callable[[], str],
    uri: str,
    on_unauthorized: Callable[[], None] | None = None,
) -> Response:
    """Append one track to the active device's queue. Returns the 204 on success.

    Refreshes and retries exactly once on a 401: a 401 that survives a refresh is a dead
    token, and looping only hides that behind a hang.
    """
    url = queue_url(uri)
    response = transport.post_json(url, {}, _headers(access_token))
    if response.status == 401 and on_unauthorized is not None:
        on_unauthorized()
        response = transport.post_json(url, {}, _headers(access_token))
    return _check(response, url)


def _run(args) -> int:
    from mldj.auth import token_provider
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.transport import UrllibTransport

    transport = UrllibTransport()
    clock = SystemClock()
    client_id = require(load_env(), "SPOTIFY_CLIENT_ID")
    access_token = token_provider(transport, clock, client_id)

    def on_unauthorized() -> None:
        from mldj.playlist import force_refresh

        force_refresh(transport, clock, client_id)

    now = transport.get(f"{API}/me/player/currently-playing", _headers(access_token))
    if now.status == 200 and isinstance(now.json(), dict):
        item = (now.json() or {}).get("item") or {}
        if item:
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            print(f"now playing: {artists} - {item.get('name')}")

    queue_track(transport, access_token, args.uri, on_unauthorized)
    print(f"queued {args.uri}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("queue", help="append one track to the playback queue")
    p.add_argument("--uri", required=True, help="a spotify:track:... URI")
    p.set_defaults(handler=_run)

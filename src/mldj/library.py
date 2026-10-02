"""The candidate pool: your own Spotify library, with URIs already attached.

The prototype's pool comes from Last.fm artist.getSimilar, which yields NAMES. Turning a name
into something playable needs a search plus a fuzzy match, and on the output side a bad match
puts the wrong song in your playlist - a failure nothing downstream can detect. Reading your
own library instead means every candidate arrives with its URI, and that class of bug cannot
happen.

The cost is that it can only recommend music you already have. That is not a compromise: the
thesis is session adaptation, not discovery.

data/ is gitignored, and the cache lives there because it is a list of what one person listens
to.
"""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mldj.transport import Transport

SAVED_URL = "https://api.spotify.com/v1/me/tracks?limit=50"
TOP_URL = "https://api.spotify.com/v1/me/top/tracks?limit=50&time_range=medium_term"
LIBRARY_PATH = Path("data/library.json")
PLAYABLE_PREFIX = "spotify:track:"


@dataclass(frozen=True)
class LibraryTrack:
    uri: str
    artist: str
    title: str


def _row_to_track(row: object) -> LibraryTrack | None:
    """One page item, from either endpoint, or None when it is not a playable track.

    /v1/me/tracks wraps the track in `track`; /v1/me/top/tracks returns it bare. Local files
    and podcast episodes appear in saved tracks and cannot be added to a playlist by URI.
    """
    if not isinstance(row, dict):
        return None
    item = row.get("track", row)
    if not isinstance(item, dict):
        return None
    uri = str(item.get("uri") or "")
    title = str(item.get("name") or "")
    artists = item.get("artists") or []
    artist = str(artists[0].get("name") or "") if artists else ""
    if not uri.startswith(PLAYABLE_PREFIX) or not title or not artist:
        return None
    return LibraryTrack(uri, artist, title)


def _pages(
    transport: Transport, access_token: Callable[[], str], url: str
) -> Iterable[dict]:
    """Follow Spotify's `next` links until they run out."""
    while url:
        response = transport.get(url, {"Authorization": f"Bearer {access_token()}"})
        if response.status != 200:
            raise RuntimeError(f"{url} returned {response.status}: {response.body[:200]!r}")
        payload = response.json()
        if not isinstance(payload, dict):
            return
        yield payload
        url = str(payload.get("next") or "")


def fetch_library(
    transport: Transport, access_token: Callable[[], str]
) -> list[LibraryTrack]:
    """Saved tracks then top tracks, deduplicated on URI, in first-seen order.

    A top track is usually also a saved track, so the two sources overlap heavily. First-seen
    order means the saved-tracks ordering survives, which keeps a rerun's output stable.
    """
    seen: set[str] = set()
    tracks: list[LibraryTrack] = []
    for url in (SAVED_URL, TOP_URL):
        for page in _pages(transport, access_token, url):
            for row in page.get("items") or []:
                track = _row_to_track(row)
                if track is None or track.uri in seen:
                    continue
                seen.add(track.uri)
                tracks.append(track)
    return tracks


def write_library(path: Path, tracks: Sequence[LibraryTrack]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tracks": [asdict(track) for track in tracks]}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def read_library(path: Path) -> list[LibraryTrack]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [LibraryTrack(**row) for row in raw["tracks"]]

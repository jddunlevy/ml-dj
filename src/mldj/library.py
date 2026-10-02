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

from mldj.lastfm import ARTIST_TAGS_DIR, TAGS_DIR, _cache_path, _read_cached
from mldj.match import normalize_artist, track_key
from mldj.space.vocab import canonical_tag
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


@dataclass(frozen=True)
class ScorableTrack:
    uri: str
    artist: str
    title: str
    tags: tuple[str, ...]
    tier: str
    novel: bool


@dataclass(frozen=True)
class LibraryCoverage:
    """How much of the library can be scored at all, by tier.

    Corpus coverage is 98.2%, but the library is a different set and that figure does not
    transfer. A low number here means the pool is thin and the ranking uninformative, which
    has to be visible before the playlist is written rather than inferred afterwards from a
    disappointing result.
    """

    tracks: int
    track_tier: int
    artist_tier: int
    untagged: int

    @property
    def scorable(self) -> int:
        return self.track_tier + self.artist_tier

    @property
    def coverage(self) -> float:
        return self.scorable / self.tracks if self.tracks else 0.0


def _canonical(tags: Sequence[str]) -> tuple[str, ...]:
    return tuple(t for t in (canonical_tag(tag) for tag in tags) if t)


def tag_library(
    tracks: Sequence[LibraryTrack],
    track_tags: Mapping[tuple[str, str], Sequence[str]],
    artist_tags: Mapping[str, Sequence[str]],
    was_heard: Callable[[str, str], bool] | None = None,
) -> tuple[list[ScorableTrack], LibraryCoverage]:
    """Attach tags to library rows, dropping what cannot be scored.

    Lookups go through match.track_key and normalize_artist, never raw strings: the tag cache
    was filled from Last.fm's names and these rows carry Spotify's. A raw lookup would miss
    every remaster suffix and report a well-tagged library as untagged.

    The artist-tier backoff is the same 24.5%-vs-95% trade export.session_events makes. It
    costs precision - artist-tier tags are identical for every track by that artist, so those
    tracks all score alike - and `tier` records it so the thinning and beat 6 can both say so.
    """
    scorable: list[ScorableTrack] = []
    track_tier = artist_tier = untagged = 0

    for track in tracks:
        tags = _canonical(track_tags.get(track_key(track.artist, track.title), ()))
        tier = "track"
        if not tags:
            tags = _canonical(artist_tags.get(normalize_artist(track.artist), ()))
            tier = "artist"
        if not tags:
            untagged += 1
            continue
        if tier == "track":
            track_tier += 1
        else:
            artist_tier += 1
        heard = was_heard(track.artist, track.title) if was_heard is not None else True
        scorable.append(
            ScorableTrack(
                uri=track.uri,
                artist=track.artist,
                title=track.title,
                tags=tags,
                tier=tier,
                novel=not heard,
            )
        )

    return scorable, LibraryCoverage(len(tracks), track_tier, artist_tier, untagged)


def cached_tag_index(
    tracks: Sequence[LibraryTrack],
    tags_dir: Path = TAGS_DIR,
    artist_tags_dir: Path = ARTIST_TAGS_DIR,
) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    """Tags for these tracks from the on-disk cache alone, making no request.

    The cache is keyed on the raw strings it was fetched with, so a library row can only hit
    it when the same raw strings were fetched. That is why the artist tier matters so much
    here: artist names diverge between Spotify and Last.fm far less than titles do.
    """
    track_tags: dict[tuple[str, str], list[str]] = {}
    artist_tags: dict[str, list[str]] = {}
    for track in tracks:
        rows = _read_cached(_cache_path(tags_dir, track.artist, track.title))
        if rows:
            track_tags[track_key(track.artist, track.title)] = [name for name, _ in rows]
        norm = normalize_artist(track.artist)
        if norm not in artist_tags:
            artist_rows = _read_cached(_cache_path(artist_tags_dir, track.artist, ""))
            if artist_rows:
                artist_tags[norm] = [name for name, _ in artist_rows]
    return track_tags, artist_tags


def render_coverage(coverage: LibraryCoverage) -> str:
    return (
        f"library: {coverage.tracks} tracks; tagged track {coverage.track_tier}, "
        f"artist {coverage.artist_tier}, none {coverage.untagged} "
        f"-> {coverage.coverage:.1%} scorable"
    )

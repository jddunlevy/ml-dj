"""Last.fm API client.

Two gotchas shape this module. Last.fm reports API errors inside a 200 response body
rather than as an HTTP status, and a full history ingest is around 196 sequential
requests, so the client paces itself instead of bursting.
"""

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from mldj.clock import Clock
from mldj.transport import Transport, retry_after_ms

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
TAGS_DIR = Path("data/tags")  # gitignored
ARTIST_TAGS_DIR = Path("data/artist-tags")  # gitignored; separate dir, see _cache_path
TAG_INFO_DIR = Path("data/tag-info")  # gitignored


class LastfmError(RuntimeError):
    """A Last.fm failure. `code` is the API's own error number, None for HTTP-level ones."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


# Last.fm returns 6 for "Track not found" and "Artist not found" alike. A candidate pool is
# built from artist.getSimilar -> artist.getTopTracks, and Last.fm does not always know the
# resulting pair by that spelling, so this is an ordinary fact about an obscure track rather
# than a failure. Every other code - a bad key, a disabled account - still raises: swallowing
# those would turn the whole corpus untagged and the space would build from nothing.
NOT_FOUND = 6


@dataclass
class LastfmClient:
    transport: Transport
    clock: Clock
    api_key: str
    min_interval_ms: int = 250
    max_attempts: int = 4
    backoff_ms: int = 1000
    # None, not 0: "no call yet" must stay distinguishable from "a call at t=0", or the
    # pacing guard silently disables itself whenever the clock starts at zero.
    _last_call_ms: int | None = field(default=None, repr=False)

    def call(self, method: str, **params: str) -> dict:
        query = urllib.parse.urlencode(
            {"method": method, "api_key": self.api_key, "format": "json", **params}
        )
        url = f"{API_ROOT}?{query}"

        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            response = self.transport.get(url)
            self._last_call_ms = self.clock.now_ms()

            # A 196-page ingest reliably meets a transient Last.fm 500, so a server error
            # or a dropped connection (status 0) is retried with an exponential backoff.
            # A 4xx other than 429 is a real error - a bad key or username - and retrying
            # it only wastes requests, so it raises straight away.
            if response.status == 429 or response.status >= 500 or response.status == 0:
                if attempt == self.max_attempts:
                    raise LastfmError(
                        f"{method}: HTTP {response.status} after {attempt} attempts"
                    )
                backoff = self.backoff_ms * 2 ** (attempt - 1)
                wait = retry_after_ms(response, backoff) if response.status == 429 else backoff
                self.clock.sleep_ms(wait)
                continue
            if response.status != 200:
                raise LastfmError(f"{method}: HTTP {response.status}")

            payload = response.json()
            if not isinstance(payload, dict):
                raise LastfmError(f"{method}: unreadable body")
            if "error" in payload:
                code = payload["error"]
                raise LastfmError(
                    f"{method}: {payload.get('message', code)}",
                    code=code if isinstance(code, int) else None,
                )
            return payload

        raise LastfmError(f"{method}: exhausted attempts")

    def _pace(self) -> None:
        if self._last_call_ms is None:
            return
        wait = self.min_interval_ms - (self.clock.now_ms() - self._last_call_ms)
        if wait > 0:
            self.clock.sleep_ms(wait)


def _tag_rows(payload: dict) -> list:
    tags = (payload.get("toptags") or {}).get("tag") or []
    return tags if isinstance(tags, list) else [tags]


def _tags_or_empty(call) -> dict | None:
    """The payload, or None when Last.fm simply does not know the artist or track."""
    try:
        return call()
    except LastfmError as err:
        if err.code == NOT_FOUND:
            return None
        raise


def top_tags(client: LastfmClient, artist: str, title: str) -> list[tuple[str, int]]:
    """Tag names with their counts, highest first. An untagged track returns []."""
    payload = _tags_or_empty(
        lambda: client.call("track.getTopTags", artist=artist, track=title, autocorrect="1")
    )
    if payload is None:
        return []
    rows = [
        (str(row.get("name", "")), int(row.get("count") or 0))
        for row in _tag_rows(payload)
        if isinstance(row, dict) and row.get("name")
    ]
    return sorted(rows, key=lambda pair: -pair[1])


def _cache_path(cache_dir: Path, artist: str, title: str) -> Path:
    """Cache filename for an (artist, title) pair.

    An artist alone is keyed as (artist, "") - so an artist and a track by that artist
    with an empty title collide on filename, and only the separate cache directories keep
    them apart. That is deliberate and asserted by a test; do not merge the directories.
    """
    digest = hashlib.sha1(f"{artist}\t{title}".encode()).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def _read_cached(path: Path) -> list[tuple[str, int]] | None:
    if not path.exists():
        return None
    return [(name, count) for name, count in json.loads(path.read_text(encoding="utf-8"))]


def _write_cached(path: Path, tags: list[tuple[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tags), encoding="utf-8")


def top_tags_cached(
    client: LastfmClient, artist: str, title: str, cache_dir: Path = TAGS_DIR
) -> list[tuple[str, int]]:
    """Disk-cached top_tags. A corpus-wide pull is thousands of calls; cache them."""
    path = _cache_path(cache_dir, artist, title)
    cached = _read_cached(path)
    if cached is not None:
        return cached
    tags = top_tags(client, artist, title)
    _write_cached(path, tags)
    return tags


def artist_top_tags(client: LastfmClient, artist: str) -> list[tuple[str, int]]:
    """An artist's top tags, highest count first.

    Artist-level coverage is around 95% against 24.5% for tracks, so this is the backoff
    tier that gives most of the corpus any tags at all. It is much coarser than track
    tags, which is why anything inheriting from here records its provenance.
    """
    payload = _tags_or_empty(
        lambda: client.call("artist.getTopTags", artist=artist, autocorrect="1")
    )
    if payload is None:
        return []
    rows = [
        (str(row.get("name", "")), int(row.get("count") or 0))
        for row in _tag_rows(payload)
        if isinstance(row, dict) and row.get("name")
    ]
    return sorted(rows, key=lambda pair: -pair[1])


def artist_top_tags_cached(
    client: LastfmClient, artist: str, cache_dir: Path = ARTIST_TAGS_DIR
) -> list[tuple[str, int]]:
    """Disk-cached artist_top_tags, keyed as (artist, "") in its own directory."""
    path = _cache_path(cache_dir, artist, "")
    cached = _read_cached(path)
    if cached is not None:
        return cached
    tags = artist_top_tags(client, artist)
    _write_cached(path, tags)
    return tags


def tag_reach(client: LastfmClient, tag: str) -> int:
    """How many distinct Last.fm users have ever applied this tag, globally.

    The discriminator for tags that are idiosyncratic to one corpus rather than part of a
    shared vocabulary. A radio station's name or somebody's playlist label has a reach of 1
    or 2 - one person used it - while `shoegaze` has 42,668 and `80s` has 100,716. A tag one
    person invented cannot carry shared meaning, whatever it says, so this is measured
    rather than hand-listed.

    It does not catch every kind of junk: evaluative tags like `fav` and `Masterpiece` are
    used by thousands of people, and artist names by tens of thousands. Those need
    min_artists and a short curated list respectively.
    """
    payload = client.call("tag.getInfo", tag=tag)
    info = payload.get("tag") or {}
    try:
        return int(info.get("reach") or 0)
    except (TypeError, ValueError):
        return 0


def tag_reach_cached(
    client: LastfmClient, tag: str, cache_dir: Path = TAG_INFO_DIR
) -> int:
    """Disk-cached tag_reach, stored as a one-entry list so it shares the cache helpers."""
    path = _cache_path(cache_dir, tag, "")
    cached = _read_cached(path)
    if cached is not None:
        return cached[0][1] if cached else 0
    reach = tag_reach(client, tag)
    _write_cached(path, [(tag, reach)])
    return reach

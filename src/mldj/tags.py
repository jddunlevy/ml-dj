"""Pull Last.fm tags for the whole corpus, and report coverage at all three tiers.

Coverage is the ceiling on the semantic space, so it is a command rather than a
remembered number. Measured 2026-09-29 by sampling: about 24.5% of distinct tracks carry
track-level tags (60% play-weighted), against about 95% of artists. That gap is why Phase 1
backs off from track tags to album siblings to artist tags - and why each assignment records
which tier it came from, since inherited tags make same-artist tracks identical by
construction.

Both passes are resumable: the cache is consulted before the network, so re-running skips
what is already held. A per-item failure is counted and stepped over, because one bad track
must never end a several-thousand-call run.

Caches live under data/, which is gitignored. This is derived from personal listening data.
"""

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mldj.lastfm import (
    ARTIST_TAGS_DIR,
    TAGS_DIR,
    LastfmClient,
    LastfmError,
    _cache_path,
    _read_cached,
    artist_top_tags_cached,
    top_tags_cached,
)
from mldj.match import normalize_artist, track_key
from mldj.scrobbles import SCROBBLES_PATH, Scrobble, read_scrobbles

TagRows = list[tuple[str, int]]
TrackKey = tuple[str, str]
ProgressFn = Callable[[str, int, int], None]


@dataclass(frozen=True)
class CoverageSummary:
    distinct_tracks: int
    distinct_artists: int
    # How many tracks a tag answer is actually held for. Below distinct_tracks while a pull
    # is still running, and without it a mid-run coverage figure reads far worse than it is.
    track_fetched: int
    track_tagged: int
    track_untagged: int
    track_coverage: float
    play_weighted_coverage: float
    album_rescued: int
    coverage_after_album: float
    artist_tagged: int
    artist_coverage: float
    distinct_tags: int
    failures: int


@dataclass(frozen=True)
class CorpusIndex:
    """Distinct tracks and artists, with the original strings the API needs."""

    track_reps: dict[TrackKey, tuple[str, str]]
    artist_reps: dict[str, str]
    plays: Counter
    album_of: dict[TrackKey, str]
    scrobbles: int


def index_corpus(scrobbles: Iterable[Scrobble]) -> CorpusIndex:
    track_reps: dict[TrackKey, tuple[str, str]] = {}
    artist_reps: dict[str, str] = {}
    plays: Counter = Counter()
    album_of: dict[TrackKey, str] = {}
    total = 0

    for s in scrobbles:
        total += 1
        key = track_key(s.artist, s.title)
        # First-seen original strings: the cache and the corpus are keyed on the normalized
        # form, but Last.fm needs the real ones.
        track_reps.setdefault(key, (s.artist, s.title))
        album_of.setdefault(key, s.album)
        artist_reps.setdefault(normalize_artist(s.artist), s.artist)
        plays[key] += 1

    return CorpusIndex(track_reps, artist_reps, plays, album_of, total)


def summarize(
    scrobbles: Sequence[Scrobble],
    track_tags: Mapping[TrackKey, TagRows],
    artist_tags: Mapping[str, TagRows],
    failures: int = 0,
    fetched: int | None = None,
) -> CoverageSummary:
    """Coverage arithmetic, independent of how the tags were obtained."""
    index = index_corpus(scrobbles)
    tagged_keys = {k for k, rows in track_tags.items() if rows}

    tagged = sum(1 for k in index.track_reps if k in tagged_keys)
    untagged = len(index.track_reps) - tagged
    tagged_plays = sum(index.plays[k] for k in index.track_reps if k in tagged_keys)

    # An absent album is not an album: pooling on an empty string would join every
    # album-less track by an artist into one bucket.
    by_album: dict[tuple[str, str], list[TrackKey]] = {}
    for key, (artist, _) in index.track_reps.items():
        album = index.album_of.get(key, "")
        if album:
            by_album.setdefault((normalize_artist(artist), album), []).append(key)

    rescued = 0
    for keys in by_album.values():
        if any(k in tagged_keys for k in keys):
            rescued += sum(1 for k in keys if k not in tagged_keys)

    artist_tagged = sum(1 for a in index.artist_reps if artist_tags.get(a))
    considered = tagged + untagged
    distinct_tags = {name for rows in track_tags.values() for name, _ in rows}

    return CoverageSummary(
        distinct_tracks=len(index.track_reps),
        distinct_artists=len(index.artist_reps),
        track_fetched=len(track_tags) if fetched is None else fetched,
        track_tagged=tagged,
        track_untagged=untagged,
        track_coverage=round(tagged / considered, 4) if considered else 0.0,
        play_weighted_coverage=(
            round(tagged_plays / index.scrobbles, 4) if index.scrobbles else 0.0
        ),
        album_rescued=rescued,
        coverage_after_album=(
            round((tagged + rescued) / considered, 4) if considered else 0.0
        ),
        artist_tagged=artist_tagged,
        artist_coverage=(
            round(artist_tagged / len(index.artist_reps), 4) if index.artist_reps else 0.0
        ),
        distinct_tags=len(distinct_tags),
        failures=failures,
    )


def pull_all(
    client: LastfmClient,
    scrobbles: Sequence[Scrobble],
    tags_dir: Path = TAGS_DIR,
    artist_tags_dir: Path = ARTIST_TAGS_DIR,
    on_progress: ProgressFn | None = None,
) -> CoverageSummary:
    """Fetch track tags then artist tags for the whole corpus, then summarize."""
    index = index_corpus(scrobbles)
    track_tags: dict[TrackKey, TagRows] = {}
    artist_tags: dict[str, TagRows] = {}
    failures = 0

    total = len(index.track_reps)
    for i, (key, (artist, title)) in enumerate(index.track_reps.items(), start=1):
        try:
            track_tags[key] = top_tags_cached(client, artist, title, tags_dir)
        except (LastfmError, OSError, ValueError):
            # One unreachable or malformed track must not end a several-thousand-call run.
            failures += 1
        if on_progress:
            on_progress("tracks", i, total)

    a_total = len(index.artist_reps)
    for i, (norm, artist) in enumerate(index.artist_reps.items(), start=1):
        try:
            artist_tags[norm] = artist_top_tags_cached(client, artist, artist_tags_dir)
        except (LastfmError, OSError, ValueError):
            failures += 1
        if on_progress:
            on_progress("artists", i, a_total)

    return summarize(scrobbles, track_tags, artist_tags, failures)


def coverage_only(
    scrobbles: Sequence[Scrobble],
    tags_dir: Path = TAGS_DIR,
    artist_tags_dir: Path = ARTIST_TAGS_DIR,
) -> CoverageSummary:
    """Recompute the summary from the cache alone, making no requests.

    An absent cache entry counts as untagged, so this reports coverage of what has actually
    been fetched - useful while a long pull is still running.
    """
    index = index_corpus(scrobbles)
    track_tags = {
        key: _read_cached(_cache_path(tags_dir, artist, title))
        for key, (artist, title) in index.track_reps.items()
    }
    artist_tags = {
        norm: _read_cached(_cache_path(artist_tags_dir, artist, "")) or []
        for norm, artist in index.artist_reps.items()
    }
    fetched = sum(1 for rows in track_tags.values() if rows is not None)
    return summarize(scrobbles, {k: v or [] for k, v in track_tags.items()}, artist_tags,
                     fetched=fetched)


def _render(summary: CoverageSummary) -> str:
    s = summary
    return "\n".join(
        [
            f"{s.distinct_tracks} distinct tracks, {s.distinct_artists} distinct artists",
            "",
            f"track tier   : {s.track_tagged}/{s.distinct_tracks} = {s.track_coverage:.1%}",
            f"  fetched so far: {s.track_fetched}/{s.distinct_tracks}"
            + (
                f" - of those fetched, {s.track_tagged / s.track_fetched:.1%} are tagged"
                if s.track_fetched and s.track_fetched < s.distinct_tracks
                else ""
            ),
            f"  play-weighted : {s.play_weighted_coverage:.1%}",
            f"  distinct tags : {s.distinct_tags}",
            f"album tier   : rescues {s.album_rescued} untagged tracks "
            f"-> {s.coverage_after_album:.1%} covered",
            f"artist tier  : {s.artist_tagged}/{s.distinct_artists} = {s.artist_coverage:.1%}",
            f"failures     : {s.failures}",
        ]
    )


def _run(args: argparse.Namespace) -> int:
    scrobbles = read_scrobbles(SCROBBLES_PATH)
    if not scrobbles:
        raise SystemExit("no history in data/scrobbles.jsonl - run `mldj ingest` first")

    if args.coverage_only:
        print(_render(coverage_only(scrobbles)))
        return 0

    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.transport import UrllibTransport

    client = LastfmClient(
        UrllibTransport(),
        SystemClock(),
        require(load_env(), "LASTFM_API_KEY"),
        min_interval_ms=args.pace_ms,
    )

    def progress(stage: str, done: int, total: int) -> None:
        if done % 250 == 0 or done == total:
            print(f"  [{stage}] {done}/{total}", flush=True)

    print(f"pulling tags for {len(scrobbles)} scrobbles at {args.pace_ms} ms spacing", flush=True)
    print(_render(pull_all(client, scrobbles, on_progress=progress)))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tags", help="pull Last.fm tags and report coverage")
    parser.add_argument(
        "--coverage-only", action="store_true", help="report from the cache, make no requests"
    )
    parser.add_argument(
        "--pace-ms", type=int, default=300, help="spacing between requests for a long run"
    )
    parser.set_defaults(handler=_run)

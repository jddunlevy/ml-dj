"""Pull the full Last.fm listening history into data/scrobbles.jsonl.

39,100 scrobbles at 200 per page is 196 sequential requests, so this is paced by the
client, resumable, and idempotent: a rerun re-reads what is already on disk and skips
duplicates, so an interrupted ingest costs nothing to restart.

`to` is pinned to the ingest's start time. Without it, scrobbles arriving mid-ingest shift
the page boundaries and rows are silently duplicated or dropped.

**Coverage gaps are reported, loudly.** Novelty rate asks "was this never previously
scrobbled", so a stretch of listening that Last.fm never recorded makes tracks heard in
that window look novel when they are not, and measured novelty comes out overstated. That
direction is safe for credibility - it makes the DJ look better than it is, so the pitch
cannot be accused of flattering its own argument - but the number is still wrong, and it
is wrong in the most recent window, which is exactly where the DJ draws from. IngestSummary
carries gap_days so the report can state it as a caveat rather than have it found later.

This file lives under data/, which is gitignored. It is personal listening data and never
enters the public repo.
"""

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from mldj.clock import SystemClock
from mldj.env import load_env, require
from mldj.lastfm import LastfmClient
from mldj.match import track_key
from mldj.transport import UrllibTransport

SCROBBLES_PATH = Path("data/scrobbles.jsonl")
PAGE_LIMIT = 200
SECONDS_PER_DAY = 86_400
STALE_AFTER_DAYS = 2  # a healthy scrobbler is never more than a day or so behind


@dataclass(frozen=True)
class Scrobble:
    uts: int
    artist: str
    title: str
    album: str


@dataclass(frozen=True)
class IngestSummary:
    pages: int
    written: int
    duplicates: int
    distinct_tracks: int
    oldest_uts: int
    newest_uts: int
    gap_days: int  # days between the newest scrobble and the ingest time

    @property
    def stale(self) -> bool:
        """True when scrobbling has evidently stopped, so novelty will be overstated."""
        return self.gap_days > STALE_AFTER_DAYS


def _rows(payload: dict) -> list:
    tracks = (payload.get("recenttracks") or {}).get("track") or []
    return tracks if isinstance(tracks, list) else [tracks]


def parse_recent_tracks_page(payload: dict) -> tuple[list[Scrobble], int]:
    """Parse one page into scrobbles plus the reported total page count.

    The now-playing entry carries no `date` and is skipped: it is not a scrobble yet.
    """
    attrs = (payload.get("recenttracks") or {}).get("@attr") or {}
    total_pages = int(attrs.get("totalPages") or 1)

    scrobbles: list[Scrobble] = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        if not isinstance(date, dict) or not date.get("uts"):
            continue  # now-playing
        scrobbles.append(
            Scrobble(
                uts=int(date["uts"]),
                artist=str((row.get("artist") or {}).get("#text", "")),
                title=str(row.get("name") or ""),
                album=str((row.get("album") or {}).get("#text", "")),
            )
        )
    return scrobbles, total_pages


def read_scrobbles(path: Path = SCROBBLES_PATH) -> list[Scrobble]:
    if not path.exists():
        return []
    out: list[Scrobble] = []
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                out.append(Scrobble(**json.loads(line)))
    return out


def ingest(
    client: LastfmClient,
    user: str,
    to_uts: int,
    path: Path = SCROBBLES_PATH,
    page_limit: int = PAGE_LIMIT,
    max_pages: int | None = None,
) -> IngestSummary:
    existing = read_scrobbles(path)
    seen = {(s.uts, s.artist, s.title) for s in existing}
    written = duplicates = 0
    page = 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        while True:
            payload = client.call(
                "user.getRecentTracks",
                user=user,
                limit=str(page_limit),
                page=str(page),
                to=str(to_uts),
                extended="0",
            )
            rows, total_pages = parse_recent_tracks_page(payload)
            for scrobble in rows:
                key = (scrobble.uts, scrobble.artist, scrobble.title)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                existing.append(scrobble)
                fh.write(json.dumps(dataclasses.asdict(scrobble), separators=(",", ":")) + "\n")
                written += 1
            fh.flush()
            if page >= total_pages or (max_pages is not None and page >= max_pages):
                break
            page += 1

    # Distinct *tracks*, not scrobbles - spec open question 4. The matrix rank in Phase 1
    # depends on this number, and it is far smaller than the scrobble count.
    distinct = {track_key(s.artist, s.title) for s in existing}
    stamps = [s.uts for s in existing] or [0]
    newest = max(stamps)
    return IngestSummary(
        pages=page,
        written=written,
        duplicates=duplicates,
        distinct_tracks=len(distinct),
        oldest_uts=min(stamps),
        newest_uts=newest,
        gap_days=max(0, (to_uts - newest) // SECONDS_PER_DAY),
    )


def _run(args: argparse.Namespace) -> int:
    env = load_env()
    clock = SystemClock()
    client = LastfmClient(UrllibTransport(), clock, require(env, "LASTFM_API_KEY"))
    summary = ingest(
        client,
        require(env, "LASTFM_USER"),
        to_uts=clock.now_ms() // 1000,
        path=Path(args.path),
        max_pages=args.max_pages,
    )
    print(
        f"{summary.pages} pages, {summary.written} new, {summary.duplicates} already held\n"
        f"{summary.distinct_tracks} distinct tracks from "
        f"{len(read_scrobbles(Path(args.path)))} scrobbles"
    )
    if summary.stale:
        print(
            f"\nWARNING: the newest scrobble is {summary.gap_days} days old.\n"
            "  Listening inside that gap was never recorded, so any track first heard there\n"
            "  will be counted as never-heard and novelty will come out OVERSTATED.\n"
            "  Reconnect scrobbling, and state the gap in the report's honesty section."
        )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ingest", help="pull Last.fm history into data/scrobbles.jsonl")
    parser.add_argument("--max-pages", type=int, default=None, help="stop early, for a smoke test")
    parser.add_argument("--path", default=str(SCROBBLES_PATH), help="where to write the JSONL")
    parser.set_defaults(handler=_run)

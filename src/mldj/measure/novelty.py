"""Novelty rate: of the tracks the DJ played, the share never previously scrobbled.

The pitch's headline number, and the one most exposed to error. Two things to hold onto:

**Both rates are reported.** `play_rate` is novel plays over all plays; `track_rate` is
novel distinct tracks over distinct tracks. A DJ replaying one novel track three times is
not three acts of exploration, so the per-track figure is the fairer one - but the two
diverging is itself a finding about repetition, so neither is dropped.

**Outcome is irrelevant here.** Unlike persistence and repetition, novelty asks only what
was *played*, so an `unknown` outcome still counts and `excluded_unknown` is always 0. The
field exists so the report can state that plainly rather than leave a reader wondering.

**The number is an upper bound while the scrobble history has a gap.** A track first heard
inside an unrecorded window is absent from the index and reads as never-heard. `novel_examples`
is the practical check: anything in that list the listener recognises fell inside the gap.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from mldj.match import track_key
from mldj.scrobbles import Scrobble
from mldj.skips import Play


@dataclass(frozen=True)
class HistoryIndex:
    """Every distinct track in the listening history, as normalized match keys."""

    keys: frozenset[tuple[str, str]]

    def contains(self, artist: str, title: str) -> bool:
        return track_key(artist, title) in self.keys

    def __len__(self) -> int:
        return len(self.keys)


def build_history(scrobbles: Iterable[Scrobble]) -> HistoryIndex:
    return HistoryIndex(frozenset(track_key(s.artist, s.title) for s in scrobbles))


@dataclass(frozen=True)
class NoveltyResult:
    plays: int
    novel_plays: int
    distinct_tracks: int
    novel_tracks: int
    excluded_unknown: int
    play_rate: float
    track_rate: float
    novel_examples: list[tuple[str, str]]


def novelty_rate(
    plays: Iterable[Play], history: HistoryIndex, examples: int = 20
) -> NoveltyResult:
    """Share of played tracks absent from the listening history, per play and per track."""
    considered = [p for p in plays if p.duration_ms > 0]

    novel_plays = 0
    first_seen: dict[tuple[str, str], tuple[str, str]] = {}
    novel_seen: dict[tuple[str, str], tuple[str, str]] = {}

    for play in considered:
        key = track_key(play.artist, play.title)
        first_seen.setdefault(key, (play.artist, play.title))
        if key not in history.keys:
            novel_plays += 1
            novel_seen.setdefault(key, (play.artist, play.title))

    distinct = len(first_seen)
    return NoveltyResult(
        plays=len(considered),
        novel_plays=novel_plays,
        distinct_tracks=distinct,
        novel_tracks=len(novel_seen),
        excluded_unknown=0,
        play_rate=novel_plays / len(considered) if considered else 0.0,
        track_rate=len(novel_seen) / distinct if distinct else 0.0,
        # Insertion-ordered, so the sample is the first novel tracks of the session rather
        # than an arbitrary set - easier to recognise when eyeballing for matcher bugs.
        novel_examples=list(novel_seen.values())[:examples],
    )

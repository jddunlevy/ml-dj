"""Rank a library against a session vector and write the result as a new playlist.

The ranking uses the session's FINAL vector: one vector, one playlist. A per-step variant -
each track chosen against the vector as it stood - would narrate the session rather than
summarise it, and is the spec's deferred open question rather than an oversight.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from mldj.engine import tag_vector
from mldj.library import ScorableTrack
from mldj.match import track_key
from mldj.space.space import TagSpace

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

"""Post-skip persistence: after a skip, how much of the skipped track's character survives.

**This metric is a contrast, not an absolute.** "23% of post-skip tracks share the skipped
artist" means nothing on its own - some artist repetition is normal and even wanted. The
finding is the *difference* between what follows a skip and what follows a completion:

  - if the DJ adapts within the session, persistence after a skip should be measurably
    LOWER than after a completion, and `artist_delta` comes out positive
  - if the two arms are the same, the system is not responding to the strongest signal a
    listener can send, and `artist_delta` sits near zero

That near-zero delta is the "it isn't listening" claim, quantified. Both arms are always
returned, and the post-skip arm must never be reported alone.

Two denominators are reported because they differ. `transitions` counts adjacent pairs;
`tagged_transitions` counts only those where both tracks carry at least one Last.fm tag,
which with thin folksonomy coverage can be far smaller. Beat 6's tag-coverage caveat needs
the real ratio, not an implied one.

Transitions are adjacent plays *within one session*, and a pair touching an `unknown`
outcome is dropped: ambiguous records are not evidence in either direction. `excluded_unknown`
counts the dropped pairs so the report can state what it could not use.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from mldj.lastfm import TAGS_DIR, LastfmClient, top_tags, top_tags_cached
from mldj.match import normalize_artist, track_key
from mldj.skips import Play


@dataclass(frozen=True)
class TagIndex:
    """Top Last.fm tags per distinct track, as normalized match keys."""

    by_key: Mapping[tuple[str, str], frozenset[str]]

    def tags(self, artist: str, title: str) -> frozenset[str]:
        return self.by_key.get(track_key(artist, title), frozenset())


def build_tag_index(
    client: LastfmClient,
    plays: Iterable[Play],
    top_n: int = 5,
    cache_dir: Path | None = TAGS_DIR,
    track_tier_only: set[tuple[str, str]] | None = None,
) -> TagIndex:
    """Fetch top tags for every distinct track in `plays`, once each.

    Scoped to tracks that actually appear in captured sessions - a few hundred calls, not
    the corpus-wide pull, which belongs to Phase 1. cache_dir=None skips the disk cache.

    **This index must never be filled in by backoff, and `track_tier_only` is the guard.**
    Phase 1 can give any track a vector by inheriting tags from its album siblings or its
    artist, which is right for recommending and wrong here: two tracks by one artist that
    both inherited the artist's tags have a tag overlap of 1.0 *by construction*, so a
    persistence metric fed inherited tags would be measuring the backoff rather than the DJ.
    Pass `mldj.space.assign.track_tier_keys(assignments)` to make the restriction explicit
    when Phase 1's assignments are available; without it the restriction still holds, because
    `top_tags` returns nothing for an untagged track and `_arm` skips a transition whose
    either side is untagged.
    """
    by_key: dict[tuple[str, str], frozenset[str]] = {}
    for play in plays:
        key = track_key(play.artist, play.title)
        if key in by_key:
            continue
        if track_tier_only is not None and key not in track_tier_only:
            by_key[key] = frozenset()  # recorded as untagged, never inherited
            continue
        if cache_dir is None:
            rows = top_tags(client, play.artist, play.title)
        else:
            rows = top_tags_cached(client, play.artist, play.title, cache_dir)
        by_key[key] = frozenset(name for name, _ in rows[:top_n])
    return TagIndex(by_key)


@dataclass(frozen=True)
class Arm:
    """One side of the contrast: what followed skips, or what followed completions."""

    transitions: int
    same_artist: int
    artist_rate: float
    mean_tag_jaccard: float
    tagged_transitions: int


@dataclass(frozen=True)
class PersistenceResult:
    after_skip: Arm
    after_completion: Arm
    artist_delta: float  # completion rate minus skip rate; near zero means no adaptation
    tag_delta: float
    excluded_unknown: int


def _transitions(plays: Iterable[Play]) -> Iterator[tuple[Play, Play]]:
    """Adjacent (outgoing, incoming) pairs, in time order, never crossing a session."""
    by_session: dict[str, list[Play]] = {}
    for play in sorted(plays, key=lambda p: p.started_at_ms):
        by_session.setdefault(play.session, []).append(play)
    for session_plays in by_session.values():
        yield from zip(session_plays, session_plays[1:], strict=False)


def _arm(pairs: list[tuple[Play, Play]], tags: TagIndex) -> Arm:
    same = sum(
        1
        for first, second in pairs
        if normalize_artist(first.artist) == normalize_artist(second.artist)
    )
    overlaps: list[float] = []
    for first, second in pairs:
        a = tags.tags(first.artist, first.title)
        b = tags.tags(second.artist, second.title)
        if a and b:  # an untagged side is no evidence, not zero evidence
            overlaps.append(len(a & b) / len(a | b))
    return Arm(
        transitions=len(pairs),
        same_artist=same,
        artist_rate=same / len(pairs) if pairs else 0.0,
        mean_tag_jaccard=sum(overlaps) / len(overlaps) if overlaps else 0.0,
        tagged_transitions=len(overlaps),
    )


def post_skip_persistence(plays: Iterable[Play], tags: TagIndex) -> PersistenceResult:
    """Persistence after skips, against the post-completion baseline that gives it meaning."""
    after_skip: list[tuple[Play, Play]] = []
    after_completion: list[tuple[Play, Play]] = []
    excluded = 0

    for first, second in _transitions(plays):
        if "unknown" in (first.outcome, second.outcome):
            excluded += 1
            continue
        if first.outcome == "skipped":
            after_skip.append((first, second))
        elif first.outcome == "completed":
            after_completion.append((first, second))

    skip_arm = _arm(after_skip, tags)
    done_arm = _arm(after_completion, tags)
    return PersistenceResult(
        after_skip=skip_arm,
        after_completion=done_arm,
        artist_delta=done_arm.artist_rate - skip_arm.artist_rate,
        tag_delta=done_arm.mean_tag_jaccard - skip_arm.mean_tag_jaccard,
        excluded_unknown=excluded,
    )

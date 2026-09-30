"""Assemble the pipeline: corpus and caches in, TagSpace out.

Not in the plan's file list, but `mldj space` needs one place that knows the order -
vocabulary, assignment, matrix, PPMI, SVD - and duplicating that between the CLI and the
sweep would let the two drift apart. Every knob the sweep varies is a parameter here, and
every one of them lands in the space's meta so the result can be rebuilt.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mldj.lastfm import ARTIST_TAGS_DIR, TAG_INFO_DIR, TAGS_DIR, _cache_path, _read_cached
from mldj.scrobbles import Scrobble
from mldj.space.assign import assign_tags, tier_counts
from mldj.space.matrix import build_matrix
from mldj.space.ppmi import ppmi
from mldj.space.reduce import reduce_dimensions
from mldj.space.space import TagSpace
from mldj.space.vocab import build_vocabulary, canonical_tag, tag_artist_spread
from mldj.tags import TagRows, TrackKey, index_corpus


@dataclass(frozen=True)
class CorpusTags:
    """Everything the pipeline needs from disk, read once so a sweep does not re-read it."""

    scrobbles: Sequence[Scrobble]
    track_tags: Mapping[TrackKey, TagRows]
    artist_tags: Mapping[str, TagRows]
    raw_counts: Mapping[str, int]
    artist_spread: Mapping[str, int]
    tag_reach: Mapping[str, int]


def load_corpus_tags(
    scrobbles: Sequence[Scrobble],
    tags_dir: Path = TAGS_DIR,
    artist_tags_dir: Path = ARTIST_TAGS_DIR,
    tag_info_dir: Path = TAG_INFO_DIR,
) -> CorpusTags:
    index = index_corpus(scrobbles)
    track_tags = {
        key: (_read_cached(_cache_path(tags_dir, artist, title)) or [])
        for key, (artist, title) in index.track_reps.items()
    }
    artist_tags = {
        norm: (_read_cached(_cache_path(artist_tags_dir, artist, "")) or [])
        for norm, artist in index.artist_reps.items()
    }

    raw_counts: Counter[str] = Counter()
    for rows in track_tags.values():
        for name, _ in rows:
            raw_counts[name] += 1

    # Reach is per raw spelling; a canonical term takes the highest reach among its
    # spellings, since the most-used spelling is the fairest evidence that the term belongs
    # to a shared vocabulary rather than one person's filing system.
    reach: dict[str, int] = {}
    for raw in raw_counts:
        cached = _read_cached(_cache_path(tag_info_dir, raw, ""))
        if not cached:
            continue
        term = canonical_tag(raw)
        reach[term] = max(reach.get(term, 0), cached[0][1])

    return CorpusTags(
        scrobbles=scrobbles,
        track_tags=track_tags,
        artist_tags=artist_tags,
        raw_counts=dict(raw_counts),
        artist_spread=tag_artist_spread(track_tags, index.track_reps),
        tag_reach=reach,
    )


def build_space(
    corpus: CorpusTags,
    *,
    min_count: int = 3,
    min_artists: int = 3,
    min_reach: int = 0,
    top_n: int = 10,
    include_artists: bool = True,
    shift: float = 0.0,
    context_smoothing: float = 0.75,
    rank: int = 150,
    eigenvalue_weighting: float = 0.5,
    seed: int = 0,
) -> TagSpace:
    """Run the whole pipeline, recording every setting in the space's meta."""
    vocab = build_vocabulary(
        corpus.raw_counts,
        min_count=min_count,
        artist_spread=corpus.artist_spread,
        min_artists=min_artists,
        tag_reach=corpus.tag_reach if min_reach > 0 else None,
        min_reach=min_reach,
    )
    assignments = assign_tags(
        corpus.scrobbles, corpus.track_tags, corpus.artist_tags, vocab, top_n=top_n
    )
    matrix = build_matrix(
        assignments, corpus.artist_tags, vocab, include_artists=include_artists, top_n=top_n
    )
    weighted = ppmi(matrix.counts, shift=shift, context_smoothing=context_smoothing)

    # Truncated SVD needs rank below the smaller dimension; a sweep point that asks for more
    # is clamped rather than crashing the whole sweep.
    usable_rank = min(rank, min(weighted.shape) - 1)
    vectors = reduce_dimensions(
        weighted, rank=usable_rank, eigenvalue_weighting=eigenvalue_weighting, seed=seed
    )

    return TagSpace(
        terms=vocab.terms,
        vectors=vectors,
        display=vocab.display,
        meta={
            "rank": usable_rank,
            "requested_rank": rank,
            "eigenvalue_weighting": eigenvalue_weighting,
            "shift": shift,
            "context_smoothing": context_smoothing,
            "min_count": min_count,
            "min_artists": min_artists,
            "min_reach": min_reach,
            "top_n": top_n,
            "include_artists": include_artists,
            "seed": seed,
            "vocabulary_size": len(vocab),
            "vocabulary_dropped": {
                "rare": vocab.dropped,
                "too_few_artists": vocab.dropped_by_spread,
                "too_little_reach": vocab.dropped_by_reach,
                "nondescriptive": vocab.dropped_as_nondescriptive,
            },
            "item_counts": dict(Counter(matrix.item_kinds)),
            "tier_counts": tier_counts(assignments),
        },
    )

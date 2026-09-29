"""The tags x items co-occurrence matrix that the space is learned from.

**Columns are genuinely annotated items only.** Track-tier assignments become columns;
album-tier and artist-tier ones do not. An inherited tag set is not independent evidence -
if every track by one artist carried that artist's tags, PPMI would read a single human
annotation as hundreds of separate observations, and the space would learn the shape of
`assign.py`'s backoff rather than a fact about how people use these words.

**Tagged artists are columns too, optionally.** An artist's tag set is a real human
annotation of a real entity, so it is legitimate evidence about which tags go together -
and with only about 1,430 tagged tracks in the corpus, the roughly 1,650 tagged artists
more than double the data. They are coarser and may blur fine distinctions, so
`include_artists` is a knob the Task 8 sweep decides on evidence rather than taste.

**Counts are binary presence.** Last.fm returns a 0-100 popularity score per item, not a
frequency: a tag with count 100 on one track was not applied a hundred times. Weighting by
it would mix "how strongly the crowd associates this tag with this item" into a matrix whose
cells are supposed to mean "this tag occurred in this context", so presence is the honest
signal and the popularity order is spent earlier, in `usable_tags`, on choosing *which*
tags survive.

`cooccurrence` is the same-item co-occurrence count that **Phase 2's antonym discriminator
consumes directly**: high distributional similarity with low same-item co-occurrence is the
antonym signature, and the second half of that test is exactly this matrix.

`item_ids` exists for debugging and provenance and **never reaches space.json** - it carries
artist and title strings, which the export is forbidden to contain.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from mldj.space.assign import TrackTags, usable_tags
from mldj.space.vocab import Vocabulary
from mldj.tags import TagRows, TrackKey


@dataclass(frozen=True)
class CountMatrix:
    counts: sparse.csr_matrix  # tags (rows) x items (columns), binary presence
    vocab: Vocabulary
    item_ids: tuple[str, ...]
    item_kinds: tuple[str, ...]  # 'track' | 'artist', parallel to item_ids

    @property
    def shape(self) -> tuple[int, int]:
        return self.counts.shape


def _track_item_id(key: TrackKey) -> str:
    artist, title = key
    return f"track:{artist}|{title}"


def build_matrix(
    assignments: Mapping[TrackKey, TrackTags],
    artist_tags: Mapping[str, TagRows],
    vocab: Vocabulary,
    include_artists: bool = True,
    top_n: int = 10,
) -> CountMatrix:
    """Binary tags x items matrix over track-tier tracks and, optionally, tagged artists."""
    item_ids: list[str] = []
    item_kinds: list[str] = []
    columns: list[tuple[str, ...]] = []

    for key, assigned in assignments.items():
        if assigned.tier != "track" or not assigned.tags:
            continue
        item_ids.append(_track_item_id(key))
        item_kinds.append("track")
        columns.append(assigned.tags)

    if include_artists:
        for artist, rows in artist_tags.items():
            tags = usable_tags(rows, vocab, top_n)
            if not tags:
                continue
            item_ids.append(f"artist:{artist}")
            item_kinds.append("artist")
            columns.append(tags)

    rows_idx: list[int] = []
    cols_idx: list[int] = []
    for column, tags in enumerate(columns):
        for tag in tags:
            row = vocab.index.get(tag)
            if row is not None:  # a tag outside the vocabulary is never a cell
                rows_idx.append(row)
                cols_idx.append(column)

    counts = sparse.csr_matrix(
        (np.ones(len(rows_idx), dtype=np.int32), (rows_idx, cols_idx)),
        shape=(len(vocab), len(columns)),
        dtype=np.int32,
    )
    # A tag can only be present or absent on an item, so duplicate entries - which cannot
    # happen given usable_tags dedupes, but would silently become 2 if they did - are capped.
    counts.data = np.minimum(counts.data, 1)

    return CountMatrix(
        counts=counts,
        vocab=vocab,
        item_ids=tuple(item_ids),
        item_kinds=tuple(item_kinds),
    )


def cooccurrence(matrix: CountMatrix) -> sparse.csr_matrix:
    """Tags x tags same-item co-occurrence counts.

    Entry (i, j) is the number of items carrying both tags; the diagonal is the number of
    items carrying each tag. This is the low-co-occurrence half of Phase 2's antonym
    discriminator - synonyms co-tag the same item constantly, antonyms almost never do.
    """
    counts = matrix.counts
    return sparse.csr_matrix(counts @ counts.T)

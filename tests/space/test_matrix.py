"""The tiny corpus, and its matrix written out by hand.

fixtures/tiny-corpus.jsonl holds four tracks by two artists:

    Alpha - one   (album A1)   tags: mellow, dream pop
    Alpha - two   (album A1)   tags: mellow, shoegaze
    Beta  - three (album B1)   tags: loud, punk
    Beta  - four  (album B1)   tags: none -> inherits from three at album tier

Artist tags: Alpha -> dream pop, Beta -> punk.

All five vocabulary terms are given equal counts, so `build_vocabulary` orders them
alphabetically: dreampop, loud, mellow, punk, shoegaze.

Only track-tier tracks become columns, so "four" is excluded and the track-only matrix is
three columns wide, in corpus order: one, two, three.

              one  two  three
    dreampop   1    0     0
    loud       0    0     1
    mellow     1    1     0
    punk       0    0     1
    shoegaze   0    1     0
"""

import json
from pathlib import Path

import numpy as np

from mldj.match import track_key
from mldj.scrobbles import Scrobble
from mldj.space.assign import assign_tags
from mldj.space.matrix import build_matrix, cooccurrence
from mldj.space.vocab import build_vocabulary

FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "tiny-corpus.jsonl"

TERMS = ["dreampop", "loud", "mellow", "punk", "shoegaze"]
VOCAB = build_vocabulary(
    dict.fromkeys(["dream pop", "loud", "mellow", "punk", "shoegaze"], 9), min_count=1
)

TRACK_TAGS = {
    track_key("Alpha", "one"): [("mellow", 100), ("dream pop", 90)],
    track_key("Alpha", "two"): [("mellow", 100), ("shoegaze", 80)],
    track_key("Beta", "three"): [("loud", 100), ("punk", 70)],
}
ARTIST_TAGS = {"alpha": [("dream pop", 100)], "beta": [("punk", 100)]}

EXPECTED_TRACK_ONLY = np.array(
    [
        [1, 0, 0],  # dreampop
        [0, 0, 1],  # loud
        [1, 1, 0],  # mellow
        [0, 0, 1],  # punk
        [0, 1, 0],  # shoegaze
    ]
)


def scrobbles():
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [Scrobble(**json.loads(line)) for line in lines if line.strip()]


def assignments():
    return assign_tags(scrobbles(), TRACK_TAGS, ARTIST_TAGS, VOCAB)


def matrix(include_artists=False):
    return build_matrix(assignments(), ARTIST_TAGS, VOCAB, include_artists=include_artists)


def test_the_vocabulary_is_in_the_expected_order():
    # Every later hand-computed matrix depends on this row order.
    assert list(VOCAB.terms) == TERMS


def test_matrix_shape_is_vocab_by_items():
    m = matrix()
    assert m.counts.shape == (len(VOCAB), 3)


def test_counts_match_a_hand_computed_tiny_corpus():
    np.testing.assert_array_equal(matrix().counts.toarray(), EXPECTED_TRACK_ONLY)


def test_only_track_tier_assignments_become_columns():
    # "four" inherits from its album sibling, so it is not independent evidence and must
    # not become a column - otherwise PPMI reads one annotation as two observations.
    m = matrix()
    assert len(m.item_ids) == 3
    assert not any("four" in item for item in m.item_ids)


def test_artist_columns_are_included_when_asked_and_excluded_when_not():
    assert matrix(include_artists=False).counts.shape[1] == 3
    assert matrix(include_artists=True).counts.shape[1] == 5


def test_artist_columns_carry_the_artists_own_tags():
    m = matrix(include_artists=True)
    dense = m.counts.toarray()
    alpha = m.item_ids.index("artist:alpha")
    beta = m.item_ids.index("artist:beta")
    assert dense[TERMS.index("dreampop"), alpha] == 1
    assert dense[TERMS.index("mellow"), alpha] == 0
    assert dense[TERMS.index("punk"), beta] == 1


def test_item_kinds_line_up_with_item_ids():
    m = matrix(include_artists=True)
    assert len(m.item_kinds) == len(m.item_ids)
    assert m.item_kinds == ("track", "track", "track", "artist", "artist")


def test_counts_are_binary_presence_not_lastfm_popularity():
    # Last.fm counts are a 0-100 popularity score per item, not a frequency, so summing or
    # weighting by them would not mean anything. Presence is the honest signal.
    assert set(np.unique(matrix().counts.toarray())) <= {0, 1}


def test_a_tag_absent_from_the_vocabulary_never_appears():
    narrow = build_vocabulary({"mellow": 9}, min_count=1)
    m = build_matrix(
        assign_tags(scrobbles(), TRACK_TAGS, ARTIST_TAGS, narrow), ARTIST_TAGS, narrow
    )
    assert m.counts.shape[0] == 1
    assert m.counts.sum() == 2  # mellow is on "one" and "two", and nothing else survives


def test_cooccurrence_is_symmetric_with_tag_totals_on_the_diagonal():
    co = cooccurrence(matrix()).toarray()
    np.testing.assert_array_equal(co, co.T)
    # Diagonal is the number of items carrying each tag.
    np.testing.assert_array_equal(np.diag(co), [1, 1, 2, 1, 1])


def test_cooccurrence_counts_shared_items():
    co = cooccurrence(matrix()).toarray()
    i = TERMS.index
    assert co[i("mellow"), i("dreampop")] == 1  # both on "one"
    assert co[i("mellow"), i("shoegaze")] == 1  # both on "two"
    assert co[i("loud"), i("punk")] == 1  # both on "three"
    assert co[i("mellow"), i("punk")] == 0  # never share an item


def test_cooccurrence_is_what_phase_two_consumes():
    # Phase 2's discriminator is "high distributional similarity + low same-item
    # co-occurrence => antonym", so it reads these counts directly.
    co = cooccurrence(matrix(include_artists=True)).toarray()
    assert co.shape == (len(VOCAB), len(VOCAB))


def test_an_empty_assignment_set_gives_an_empty_matrix():
    m = build_matrix({}, {}, VOCAB, include_artists=False)
    assert m.counts.shape == (len(VOCAB), 0)
    assert m.item_ids == ()

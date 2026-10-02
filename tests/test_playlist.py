import numpy as np

from mldj.library import ScorableTrack
from mldj.playlist import Ranked, exclude_played, rank_library, thin_by_artist
from mldj.space.space import TagSpace


def a_space() -> TagSpace:
    return TagSpace(
        terms=("indie", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
        meta={},
    )


def track(uri: str, artist: str, title: str, tags=("indie",), novel=False) -> ScorableTrack:
    return ScorableTrack(uri, artist, title, tuple(tags), "track", novel)


def test_a_track_played_in_the_session_is_excluded_from_the_pool():
    # A session-adaptive playlist that opens with the track you just skipped is self-evidently
    # broken.
    tracks = [track("spotify:track:1", "X", "A"), track("spotify:track:2", "Y", "B")]
    events = [{"key": ["x", "a"]}]
    assert [t.title for t in exclude_played(tracks, events)] == ["B"]


def test_exclusion_joins_on_the_normalized_key_so_a_remaster_suffix_cannot_slip_through():
    # Note the key literals keep their spaces: normalize_artist("New Order") is "new order",
    # NOT "neworder". canonical_tag strips spaces for TAGS ("New Wave" -> "newwave") but the
    # track-key normalizers do not. Getting this wrong writes a test that fails whatever the
    # implementation does.
    tracks = [track("spotify:track:1", "New Order", "Blue Monday - 2016 Remaster")]
    events = [{"key": ["new order", "blue monday"]}]
    assert exclude_played(tracks, events) == []


def test_ranking_orders_by_cosine_against_the_session_vector():
    tracks = [
        track("spotify:track:1", "X", "Shoegazey", tags=("shoegaze",)),
        track("spotify:track:2", "Y", "Indieish", tags=("indie",)),
    ]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["Indieish", "Shoegazey"]
    assert [r.rank for r in ranked] == [1, 2]


def test_epsilon_lifts_a_novel_track_and_zero_epsilon_leaves_the_order_alone():
    tracks = [
        track("spotify:track:1", "X", "Known", tags=("indie",), novel=False),
        track("spotify:track:2", "Y", "New", tags=("shoegaze",), novel=True),
    ]
    v = np.array([1.0, 0.4])
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=0.0)] == ["Known", "New"]
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=1.0)] == ["New", "Known"]


def test_a_zero_session_vector_scores_everything_at_zero_rather_than_nan():
    ranked = rank_library(a_space(), np.zeros(2), [track("spotify:track:1", "X", "A")])
    assert ranked[0].score == 0.0


def test_ties_keep_the_pool_order_so_a_rerun_produces_the_same_playlist():
    # Strengthened fixture: titles and URIs are deliberately scrambled relative to both pool
    # order and each other, so this can only pass if the implementation preserves the POOL's
    # own order among ties. A tie-break that sorted by title ("Apple","Banana","Cherry") or by
    # uri ("...2","...5","...9") would each produce a DIFFERENT order from the pool's own
    # ("Banana","Apple","Cherry") - so either forbidden rule is caught, not just one of them.
    tracks = [
        track("spotify:track:9", "X", "Banana"),
        track("spotify:track:2", "X", "Apple"),
        track("spotify:track:5", "X", "Cherry"),
    ]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["Banana", "Apple", "Cherry"]


def test_thinning_caps_tracks_per_artist():
    # Artist-tier tags are identical across an artist's tracks, so they all score alike and a
    # stable sort keeps the block together. A 30-track playlist from six artists is the bug
    # the prototype's top_by_artist already found, wearing a different hat.
    ranked = [
        Ranked(1, "spotify:track:1", "X", "A", 0.9, False),
        Ranked(2, "spotify:track:2", "X", "B", 0.9, False),
        Ranked(3, "spotify:track:3", "X", "C", 0.9, False),
        Ranked(4, "spotify:track:4", "Y", "D", 0.5, False),
    ]
    thinned = thin_by_artist(ranked, limit=10, per_artist=2)
    assert [r.title for r in thinned] == ["A", "B", "D"]
    # Ranks must be the TRUE ranks from the full pool, not renumbered: dropping rank 3 (C)
    # must leave a gap, since the gap is the tie structure made visible. A test that checks
    # titles alone cannot tell a correct skip-and-keep from a silent renumbering to [1, 2, 3].
    assert [r.rank for r in thinned] == [1, 2, 4]


def test_thinning_returns_what_exists_rather_than_padding_to_the_limit():
    ranked = [Ranked(1, "spotify:track:1", "X", "A", 0.9, False)]
    thinned = thin_by_artist(ranked, limit=30, per_artist=2)
    assert len(thinned) == 1
    assert thinned[0].rank == 1


def test_thinning_stops_at_the_limit():
    ranked = [
        Ranked(i + 1, f"spotify:track:{i}", f"A{i}", f"T{i}", 1.0 - i / 10, False)
        for i in range(5)
    ]
    thinned = thin_by_artist(ranked, limit=3, per_artist=1)
    assert len(thinned) == 3
    # Every artist here is distinct, so per_artist=1 never itself turns a row away - this
    # isolates the limit from the per-artist cap, rather than letting the two coincide and
    # leaving it ambiguous which one did the work.
    assert [r.rank for r in thinned] == [1, 2, 3]

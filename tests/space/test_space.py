import json

import numpy as np
import pytest

from mldj.space.space import (
    REQUIRED_META,
    SPACE_FORMAT_VERSION,
    TagSpace,
    leaking_terms,
    load_space,
    save_space,
)

TERMS = ("mellow", "chill", "loud", "quiet")
# mellow and chill point the same way, loud is mostly orthogonal, and quiet is exactly
# opposed to loud. Deliberately no ties: equal similarities would make the neighbour
# ordering undefined, and the test would then assert an implementation detail.
VECTORS = np.array(
    [
        [1.0, 0.0],  # mellow
        [0.9, 0.1],  # chill    cos(mellow) ~ 0.994
        [0.2, 1.0],  # loud     cos(mellow) ~ 0.196
        [-0.2, -1.0],  # quiet  cos(mellow) ~ -0.196, cos(loud) = -1
    ]
)

META = {
    "rank": 2,
    "eigenvalue_weighting": 0.5,
    "shift": 0.0,
    "context_smoothing": 0.75,
    "min_count": 3,
    "min_artists": 2,
    "include_artists": True,
    "seed": 0,
    "vocabulary_size": 4,
    "item_counts": {"track": 1363, "artist": 1137},
    "tier_counts": {"track": 1363, "album": 810, "artist": 2928, "none": 730},
}


def space(**overrides):
    return TagSpace(
        terms=TERMS,
        vectors=VECTORS,
        meta={**META, **overrides.pop("meta", {})},
        display=overrides.pop("display", {t: t for t in TERMS}),
    )


# --- geometry --------------------------------------------------------------------------


def test_similarity_is_cosine_and_symmetric():
    s = space()
    assert s.similarity("mellow", "chill") == pytest.approx(0.9 / np.hypot(0.9, 0.1))
    assert s.similarity("mellow", "chill") == s.similarity("chill", "mellow")


def test_a_tag_is_maximally_similar_to_itself():
    assert space().similarity("mellow", "mellow") == pytest.approx(1.0)


def test_opposed_vectors_score_negative():
    assert space().similarity("loud", "quiet") == pytest.approx(-1.0)


def test_similarity_with_an_unknown_tag_is_zero():
    assert space().similarity("mellow", "not a tag") == 0.0


def test_similarity_accepts_a_raw_spelling():
    # Callers hold user-facing strings, not canonical forms.
    assert space().similarity("MELLOW", "mellow") == pytest.approx(1.0)


def test_neighbours_are_sorted_descending_and_exclude_the_query():
    got = space().neighbours("mellow", k=3)
    assert [t for t, _ in got] == ["chill", "loud", "quiet"]
    assert [round(v, 6) for _, v in got] == sorted(
        (round(v, 6) for _, v in got), reverse=True
    )
    assert "mellow" not in [t for t, _ in got]


def test_neighbours_respects_k():
    assert len(space().neighbours("mellow", k=2)) == 2


def test_neighbours_of_an_unknown_tag_is_empty():
    assert space().neighbours("not a tag") == []


def test_vector_returns_none_for_an_unknown_tag_rather_than_raising():
    assert space().vector("not a tag") is None
    assert space().vector("mellow") is not None


# --- compose: the session vector's primitive -------------------------------------------


def test_compose_is_a_weighted_sum():
    got = space().compose(["mellow", "loud"], weights=[1.0, 2.0])
    np.testing.assert_allclose(got, VECTORS[0] + 2.0 * VECTORS[2])


def test_compose_defaults_to_equal_weights():
    np.testing.assert_allclose(space().compose(["mellow", "loud"]), VECTORS[0] + VECTORS[2])


def test_compose_accepts_a_negative_weight():
    # A skip subtracts the skipped track's character, which is the whole mechanism.
    np.testing.assert_allclose(
        space().compose(["mellow", "loud"], weights=[1.0, -1.0]), VECTORS[0] - VECTORS[2]
    )


def test_compose_skips_unknown_tags_without_shifting_the_weights():
    got = space().compose(["mellow", "not a tag", "loud"], weights=[1.0, 5.0, 2.0])
    np.testing.assert_allclose(got, VECTORS[0] + 2.0 * VECTORS[2])


def test_compose_of_nothing_known_is_the_zero_vector():
    got = space().compose(["not a tag"])
    assert got.shape == (2,)
    assert not got.any()


def test_compose_rejects_mismatched_weights():
    with pytest.raises(ValueError, match="weights"):
        space().compose(["mellow", "loud"], weights=[1.0])


# --- the versioned export --------------------------------------------------------------


def test_save_then_load_round_trips_exactly(tmp_path):
    path = tmp_path / "space.json"
    save_space(space(), path)
    loaded = load_space(path)
    assert loaded.terms == TERMS
    np.testing.assert_array_equal(loaded.vectors, VECTORS)
    assert loaded.meta["rank"] == 2
    assert loaded.display == {t: t for t in TERMS}


def test_float_vectors_survive_the_round_trip_bit_for_bit(tmp_path):
    odd = TagSpace(
        terms=("a", "b"),
        vectors=np.array([[0.1, 1 / 3], [np.pi, -2.718281828459045]]),
        meta=META,
        display={"a": "a", "b": "b"},
    )
    path = tmp_path / "space.json"
    save_space(odd, path)
    np.testing.assert_array_equal(load_space(path).vectors, odd.vectors)


def test_save_stamps_the_format_version_and_a_build_time(tmp_path):
    path = tmp_path / "space.json"
    save_space(space(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format_version"] == SPACE_FORMAT_VERSION
    assert raw["meta"]["built_utc"].endswith("+00:00")


def test_meta_records_every_setting_needed_to_rebuild(tmp_path):
    # An undocumented space.json cannot be reproduced, so an evaluation run against it
    # cannot be defended. Missing keys fail the save rather than the reader.
    for missing in REQUIRED_META:
        incomplete = {k: v for k, v in META.items() if k != missing}
        with pytest.raises(ValueError, match=missing):
            save_space(
                TagSpace(terms=TERMS, vectors=VECTORS, meta=incomplete, display={}),
                tmp_path / "bad.json",
            )


def test_meta_includes_the_seed_because_the_spectrum_is_near_degenerate():
    assert "seed" in REQUIRED_META


def test_loading_an_unknown_format_version_fails_loudly(tmp_path):
    path = tmp_path / "space.json"
    save_space(space(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["format_version"] = SPACE_FORMAT_VERSION + 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="format_version"):
        load_space(path)


# --- the privacy gate ------------------------------------------------------------------


def test_the_export_holds_only_tag_strings_and_numbers(tmp_path):
    path = tmp_path / "space.json"
    save_space(space(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"format_version", "meta", "terms", "display", "vectors"}


def test_leaking_terms_finds_a_tag_that_is_also_a_corpus_artist():
    # Last.fm users tag tracks with artist names. Such a term in the export would publish
    # who the listener listens to, which is exactly what the repo must not carry.
    leaks = leaking_terms(
        space(display={"mellow": "Fleetwood Mac", "chill": "chill", "loud": "loud",
                       "quiet": "quiet"}),
        forbidden={"fleetwood mac", "new order"},
    )
    assert leaks == ["Fleetwood Mac"]


def test_leaking_terms_matches_on_the_canonical_form_not_the_raw_string():
    leaks = leaking_terms(
        space(display={"mellow": "FLEETWOOD  MAC", "chill": "chill", "loud": "loud",
                       "quiet": "quiet"}),
        forbidden={"Fleetwood Mac"},
    )
    assert leaks == ["FLEETWOOD  MAC"]


def test_leaking_terms_is_empty_for_a_clean_space():
    assert leaking_terms(space(), forbidden={"fleetwood mac", "new order"}) == []


def test_leaking_terms_also_flags_a_band_named_with_an_ordinary_word():
    """Documents why this is a review list rather than an automatic reject.

    Electronic, Love, fun. and Lush are all real bands, and all four are also ordinary
    descriptive tags. String comparison cannot tell which sense a term carries, and
    dropping `electronic` would gut the vocabulary, so a person decides.
    """
    leaks = leaking_terms(space(), forbidden={"Love", "Radiohead"})
    assert leaks == []  # no term in this fixture is "love"

    with_descriptor = TagSpace(
        terms=("electronic", "mellow"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
        meta=META,
        display={"electronic": "electronic", "mellow": "mellow"},
    )
    # The band Electronic exists, so this matches - and is a false positive a human must
    # clear rather than something to drop automatically.
    assert leaking_terms(with_descriptor, forbidden={"Electronic"}) == ["electronic"]


def test_the_space_records_how_many_terms_were_dropped_as_nondescriptive():
    """Provenance, not bookkeeping. The other three drop reasons are already in meta, and a
    stoplist is the one a reader is most entitled to be suspicious of - so the count of what
    it removed has to travel with the space."""
    from mldj.space.build import CorpusTags, build_space
    from mldj.scrobbles import Scrobble

    scrobbles = [Scrobble(uts=i, artist=f"a{i % 4}", title=f"t{i}", album="x")
                 for i in range(12)]
    track_tags = {(f"a{i % 4}", f"t{i}"): [("shoegaze", 100), ("2013", 100), ("best", 100)]
                  for i in range(12)}
    corpus = CorpusTags(
        scrobbles=scrobbles,
        track_tags=track_tags,
        artist_tags={f"a{i}": [("dreampop", 100)] for i in range(4)},
        raw_counts={"shoegaze": 12, "2013": 12, "best": 12, "dreampop": 12},
        artist_spread={"shoegaze": 4, "2013": 4, "best": 4, "dreampop": 4},
        tag_reach={},
    )
    space = build_space(corpus, min_count=1, min_artists=1, rank=2, seed=0)

    assert space.meta["vocabulary_dropped"]["nondescriptive"] == 2  # 2013 and best
    assert "2013" not in space.terms and "best" not in space.terms


# --- exclusion at load (privacy gate) -----------------------------------------------


FULL_META = {
    "rank": 2,
    "eigenvalue_weighting": 0.0,
    "shift": 1.0,
    "context_smoothing": 1.0,
    "min_count": 2,
    "min_artists": 2,
    "include_artists": False,
    "seed": 0,
    "vocabulary_size": 3,
    "item_counts": {},
    "tier_counts": {},
}


def _saved(tmp_path):
    space = TagSpace(
        terms=("indie", "radiohead", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]),
        meta=FULL_META,
        display={"radiohead": "radiohead"},
    )
    path = tmp_path / "space.json"
    save_space(space, path)
    return path


def test_load_space_drops_excluded_terms_and_keeps_the_vectors_aligned(tmp_path):
    space = load_space(_saved(tmp_path), exclude=("radiohead",))
    assert space.terms == ("indie", "shoegaze")
    # The surviving rows must be the surviving terms' rows, not simply the first two rows.
    assert space.vector("shoegaze").tolist() == [1.0, 1.0]


def test_load_space_excludes_nothing_by_default(tmp_path):
    # The recorded Phase 2 baselines (antonym 0.030, complementary -0.020) were measured over
    # the full vocabulary. A default exclusion would move them with no commit touching them.
    assert load_space(_saved(tmp_path)).terms == ("indie", "radiohead", "shoegaze")


def test_the_excluded_terms_are_the_four_the_privacy_review_confirmed():
    # R/space.R holds the same list. Two implementations of one exclusion must not drift.
    from mldj.space.space import EXCLUDED_TERMS
    assert EXCLUDED_TERMS == ("radiohead", "kanyewest", "kendricklamar", "timbaland")

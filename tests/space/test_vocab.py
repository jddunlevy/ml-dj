import json
from pathlib import Path

import pytest

from mldj.space.vocab import build_vocabulary, canonical_tag, normalize_tag

GOLD = json.loads(
    (Path(__file__).parent.parent.parent / "fixtures" / "tag-vocab-gold.json").read_text(
        encoding="utf-8"
    )
)


# --- normalize_tag ---------------------------------------------------------------------


def test_case_and_whitespace_are_normalized():
    assert normalize_tag("  Dream  Pop ") == normalize_tag("dream pop")
    assert normalize_tag("SHOEGAZE") == "shoegaze"


def test_hyphen_and_space_and_run_together_forms_collapse():
    assert normalize_tag("hip hop") == normalize_tag("hip-hop") == normalize_tag("hiphop")
    assert normalize_tag("lo-fi") == normalize_tag("lofi") == normalize_tag("lo fi")


def test_underscores_collapse_too():
    assert normalize_tag("hip_hop") == normalize_tag("hip hop")


def test_diacritics_are_stripped():
    assert normalize_tag("björk") == normalize_tag("bjork")
    assert normalize_tag("Sigur Rós") == normalize_tag("sigur ros")


def test_punctuation_is_dropped():
    assert normalize_tag("post-rock!") == normalize_tag("post rock")
    assert normalize_tag("drum'n'bass") == "drumnbass"


def test_non_latin_scripts_survive_rather_than_normalizing_to_nothing():
    # Stripping to [a-z0-9] would erase these entirely and silently merge every one of
    # them into a single empty term.
    assert normalize_tag("ロック") != ""
    assert normalize_tag("ロック") != normalize_tag("поп")


def test_an_all_punctuation_tag_normalizes_to_empty():
    assert normalize_tag("---") == ""
    assert normalize_tag("") == ""


# --- canonical_tag: the curated variant map --------------------------------------------


def test_curated_variants_map_to_one_canonical_form():
    assert canonical_tag("r&b") == canonical_tag("rnb") == canonical_tag("rhythm and blues")
    assert canonical_tag("dnb") == canonical_tag("drum and bass") == canonical_tag("drum & bass")


def test_common_plurals_are_mapped_explicitly_not_stemmed():
    assert canonical_tag("female vocalists") == canonical_tag("female vocalist")


def test_decade_spellings_collapse():
    assert canonical_tag("1980s") == canonical_tag("80s") == canonical_tag("eighties")


def test_chill_and_mellow_are_not_collapsed():
    # Deciding these mean the same thing is the space's job. Hard-coding it would pre-empt
    # the result the whole project exists to test.
    assert canonical_tag("chill") != canonical_tag("mellow")


def test_chill_and_chillout_stay_distinct():
    # Derivational, not orthographic. No stemming.
    assert canonical_tag("chill") != canonical_tag("chillout")


@pytest.mark.parametrize(
    "group", GOLD["variant_groups"], ids=[g["hint"] for g in GOLD["variant_groups"]]
)
def test_every_gold_variant_group_collapses_to_one_term(group):
    canonicals = {canonical_tag(m) for m in group["members"]}
    assert len(canonicals) == 1, f"{group['hint']}: {group['members']} -> {canonicals}"


@pytest.mark.parametrize(
    "case", GOLD["near_misses"], ids=[" vs ".join(n["pair"]) for n in GOLD["near_misses"]]
)
def test_near_miss_pairs_stay_distinct(case):
    a, b = case["pair"]
    assert canonical_tag(a) != canonical_tag(b), f"{case['why']}: {a} / {b}"


# --- build_vocabulary ------------------------------------------------------------------


def test_vocabulary_sums_counts_across_spellings():
    vocab = build_vocabulary({"hip hop": 3, "hip-hop": 4, "hiphop": 1}, min_count=5)
    assert vocab.terms == (canonical_tag("hip hop"),)
    assert vocab.id("HIP-HOP") == 0


def test_vocabulary_drops_tags_below_min_count():
    vocab = build_vocabulary({"common": 10, "hapax": 1}, min_count=5)
    assert canonical_tag("common") in vocab.index
    assert canonical_tag("hapax") not in vocab.index
    assert vocab.dropped == 1


def test_vocabulary_drops_tags_that_normalize_to_nothing():
    vocab = build_vocabulary({"---": 99, "rock": 99}, min_count=5)
    assert vocab.terms == ("rock",)


def test_vocabulary_ids_are_stable_for_the_same_input():
    counts = {"rock": 10, "pop": 20, "jazz": 10, "ambient": 30}
    assert build_vocabulary(counts).terms == build_vocabulary(dict(reversed(counts.items()))).terms


def test_vocabulary_ids_are_contiguous_from_zero():
    vocab = build_vocabulary({"rock": 9, "pop": 9, "jazz": 9}, min_count=5)
    assert sorted(vocab.index.values()) == [0, 1, 2]


def test_vocabulary_id_of_an_unknown_tag_is_none():
    assert build_vocabulary({"rock": 9}, min_count=5).id("nonsense") is None


def test_vocabulary_records_the_most_common_original_spelling_for_display():
    # The canonical form is squashed ("malevocalist"), which is fine as an identifier and
    # poor to read. The display form keeps the export and the gold-set reports legible.
    vocab = build_vocabulary({"Hip-Hop": 10, "hiphop": 2}, min_count=5)
    assert vocab.display[canonical_tag("hip hop")] == "Hip-Hop"


def test_vocabulary_length_matches_its_terms():
    vocab = build_vocabulary({"rock": 9, "pop": 9}, min_count=5)
    assert len(vocab) == 2


# --- artist spread: a tag attested by one artist teaches nothing -----------------------


def test_tag_artist_spread_counts_distinct_artists_per_tag():
    from mldj.match import track_key
    from mldj.space.vocab import tag_artist_spread

    reps = {
        track_key("Alpha", "one"): ("Alpha", "one"),
        track_key("Alpha", "two"): ("Alpha", "two"),
        track_key("Beta", "three"): ("Beta", "three"),
    }
    track_tags = {
        track_key("Alpha", "one"): [("mellow", 9), ("alphacore", 9)],
        track_key("Alpha", "two"): [("alphacore", 9)],
        track_key("Beta", "three"): [("mellow", 9)],
    }
    spread = tag_artist_spread(track_tags, reps)
    assert spread[canonical_tag("mellow")] == 2
    assert spread[canonical_tag("alphacore")] == 1  # two tracks, but one artist


def test_min_artists_drops_a_tag_only_one_artist_carries():
    # Last.fm users tag tracks with artist names, and such a tag co-occurs with exactly
    # that artist's tracks - perfect specificity, no generalizable meaning, and it would
    # dominate the SVD. The same is true of a genre only one artist attests.
    spread = {canonical_tag("mellow"): 5, canonical_tag("weezer"): 1}
    counts = {"mellow": 40, "weezer": 40}
    vocab = build_vocabulary(counts, min_count=5, artist_spread=spread, min_artists=2)
    assert canonical_tag("mellow") in vocab.index
    assert canonical_tag("weezer") not in vocab.index
    assert vocab.dropped_by_spread == 1


def test_min_artists_of_one_keeps_everything():
    spread = {canonical_tag("mellow"): 5, canonical_tag("weezer"): 1}
    vocab = build_vocabulary(
        {"mellow": 40, "weezer": 40}, min_count=5, artist_spread=spread, min_artists=1
    )
    assert len(vocab) == 2
    assert vocab.dropped_by_spread == 0


def test_spread_filter_is_skipped_when_no_spread_is_given():
    vocab = build_vocabulary({"mellow": 40, "weezer": 40}, min_count=5, min_artists=3)
    assert len(vocab) == 2  # nothing to filter on, so nothing is dropped
    assert vocab.dropped_by_spread == 0


def test_a_tag_missing_from_the_spread_map_is_treated_as_unattested():
    vocab = build_vocabulary(
        {"mellow": 40}, min_count=5, artist_spread={}, min_artists=2
    )
    assert len(vocab) == 0
    assert vocab.dropped_by_spread == 1


def test_the_two_drop_reasons_are_reported_separately():
    spread = {canonical_tag("mellow"): 5, canonical_tag("weezer"): 1, canonical_tag("rare"): 9}
    vocab = build_vocabulary(
        {"mellow": 40, "weezer": 40, "rare": 1}, min_count=5,
        artist_spread=spread, min_artists=2,
    )
    assert vocab.dropped == 1  # rare, below min_count
    assert vocab.dropped_by_spread == 1  # weezer, one artist
    assert len(vocab) == 1


# Non-descriptive tags. min_reach cannot catch these: `best` has a reach of 7673 and
# `seattle` 6927, so plenty of people used them - they fail a different test, which is
# whether they say anything about the music. A min_reach high enough to remove them
# (8000) costs 19 of the 61 scorable gold pairs, dropping 196 terms to be rid of 12.


def test_a_bare_year_is_not_a_description_of_music():
    vocab = build_vocabulary({"2013": 40, "shoegaze": 40}, min_count=5)
    assert vocab.terms == ("shoegaze",)
    assert vocab.dropped_as_nondescriptive == 1


def test_every_plausible_release_year_is_caught_by_the_rule_not_a_list():
    counts = {str(y): 40 for y in (1969, 1984, 1999, 2004, 2013, 2026)}
    assert len(build_vocabulary(counts, min_count=5)) == 0


def test_a_decade_survives_because_it_describes_a_sound():
    # 80s and 90s are deliberate, curated terms - VARIANTS folds "eighties" and "1980s"
    # onto them. The year rule must not take them with it.
    vocab = build_vocabulary({"80s": 40, "90s": 40, "10s": 40}, min_count=5)
    assert set(vocab.terms) == {"80s", "90s", "10s"}


def test_a_number_that_is_not_a_year_survives():
    vocab = build_vocabulary({"1989": 40, "808": 40, "27": 40}, min_count=5)
    assert "808" in vocab.terms and "27" in vocab.terms


def test_approval_and_collection_tags_are_dropped():
    counts = {"best": 40, "loved": 40, "personal favourites": 40, "77davez-all-tracks": 40}
    assert len(build_vocabulary(counts, min_count=5)) == 0


def test_love_survives_because_it_names_a_band_and_a_theme():
    # CLAUDE.md flags `Love` among four terms that look like artist names but are ordinary
    # words doing real work. It is a theme, not a rating, and must not be swept up with
    # `loved` and `best`.
    vocab = build_vocabulary({"love": 40}, min_count=5)
    assert vocab.terms == ("love",)


def test_a_genre_that_merely_contains_a_stopword_survives():
    # Substring matching would take `lovesong` and `bestof` with it. The stoplist is exact.
    vocab = build_vocabulary({"lovesongs": 40, "lovemetal": 40}, min_count=5)
    assert len(vocab) == 2


def test_nondescriptive_drops_are_counted_separately_from_the_other_reasons():
    vocab = build_vocabulary(
        {"2013": 40, "rare": 1, "shoegaze": 40}, min_count=5
    )
    assert vocab.dropped == 1  # rare
    assert vocab.dropped_as_nondescriptive == 1  # 2013
    assert vocab.terms == ("shoegaze",)

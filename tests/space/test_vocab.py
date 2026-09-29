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

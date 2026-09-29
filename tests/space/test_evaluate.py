"""Level-1 evaluation, against a space whose similarities are chosen by hand.

Four terms on a circle, so every pairwise cosine is known in advance:

    neara  = (1, 0)
    nearb  = (0.98, 0.20)   cos(neara) ~ 0.98   -> a synonym-scale score
    mid     = (0.71, 0.71)   cos(neara) ~ 0.71   -> a related-scale score
    far     = (0, 1)         cos(neara) = 0      -> an unrelated-scale score
    opposed = (-1, 0)        cos(neara) = -1
"""

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from mldj.space.evaluate import (
    GRADED,
    LABELS,
    MIN_PAIRS_PER_LABEL,
    GoldPair,
    evaluate_space,
    expand_grid,
    load_gold,
    render_evaluation,
    sweep,
)
from mldj.space.space import TagSpace

REAL_GOLD_PATH = Path(__file__).parent.parent.parent / "fixtures" / "tag-pairs-gold.json"

TERMS = ("neara", "nearb", "mid", "far", "opposed")
VECTORS = np.array(
    [
        [1.0, 0.0],
        [0.98, 0.20],
        [0.71, 0.71],
        [0.0, 1.0],
        [-1.0, 0.0],
    ]
)
SPACE = TagSpace(terms=TERMS, vectors=VECTORS, meta={}, display={t: t for t in TERMS})


def pair(label: str, a: str, b: str) -> GoldPair:
    return GoldPair(a=a, b=b, label=label, why="test")


def ordered_gold() -> list[GoldPair]:
    """Synonyms score ~0.98, related ~0.71, unrelated 0.0 - the correct ordering."""
    return [
        pair("synonym", "neara", "nearb"),
        pair("synonym", "nearb", "neara"),
        pair("related", "neara", "mid"),
        pair("related", "nearb", "mid"),
        pair("unrelated", "neara", "far"),
        pair("unrelated", "nearb", "far"),
        pair("antonym", "neara", "opposed"),
        pair("complementary", "mid", "far"),
    ]


# --- the committed gold set's own contract ---------------------------------------------


def test_gold_set_has_every_label_and_the_minimum_counts():
    gold = load_gold(REAL_GOLD_PATH)
    assert len(gold) >= 60
    for label in LABELS:
        found = [p for p in gold if p.label == label]
        assert len(found) >= MIN_PAIRS_PER_LABEL, f"{label} has only {len(found)} pairs"


def test_gold_set_includes_the_complementary_class_the_spec_names_as_a_trap():
    gold = load_gold(REAL_GOLD_PATH)
    complementary = [p for p in gold if p.label == "complementary"]
    joined = {f"{p.a}|{p.b}" for p in complementary}
    assert "male vocalists|female vocalists" in joined


def test_gold_set_uses_only_known_labels():
    assert {p.label for p in load_gold(REAL_GOLD_PATH)} <= set(LABELS)


def test_every_gold_pair_carries_a_reason():
    assert all(p.why for p in load_gold(REAL_GOLD_PATH))


def test_gold_set_has_no_duplicate_pairs():
    gold = load_gold(REAL_GOLD_PATH)
    keys = {frozenset((p.a.lower(), p.b.lower())) for p in gold}
    assert len(keys) == len(gold)


# --- the graded ordering ---------------------------------------------------------------


def test_synonyms_outscore_related_pairs():
    result = evaluate_space(SPACE, ordered_gold())
    assert result.mean("synonym") > result.mean("related")


def test_related_pairs_outscore_unrelated_pairs():
    result = evaluate_space(SPACE, ordered_gold())
    assert result.mean("related") > result.mean("unrelated")


def test_ranking_correct_is_true_for_a_well_ordered_space():
    assert evaluate_space(SPACE, ordered_gold()).ranking_correct is True


def test_ranking_correct_is_false_when_the_ordering_inverts():
    inverted = [
        pair("synonym", "neara", "far"),  # scores 0.0
        pair("synonym", "nearb", "far"),
        pair("related", "neara", "mid"),  # scores 0.71
        pair("unrelated", "neara", "nearb"),  # scores 0.98
    ]
    assert evaluate_space(SPACE, inverted).ranking_correct is False


def test_spearman_is_positive_when_the_ordering_holds():
    assert evaluate_space(SPACE, ordered_gold()).spearman > 0.8


def test_separations_are_reported():
    result = evaluate_space(SPACE, ordered_gold())
    assert result.synonym_minus_unrelated == pytest.approx(
        result.mean("synonym") - result.mean("unrelated")
    )
    assert result.related_minus_unrelated > 0


# --- antonyms and complementary pairs: recorded, not graded ---------------------------


def test_antonym_similarity_is_recorded_not_penalised():
    # An unaided space scoring antonyms high is the project's central problem, not a
    # measurement failure. Grading it would make the score improve as the space got worse
    # at the thing that matters.
    result = evaluate_space(SPACE, ordered_gold())
    assert result.antonym_mean == pytest.approx(-1.0)
    assert result.ranking_correct is True  # unaffected by the antonym score


def test_a_high_antonym_score_does_not_fail_the_ranking():
    # The realistic case: the space calls an antonym pair highly similar, exactly as an
    # unaided distributional space does with loud/quiet. The graded ordering must be
    # untouched by it, or improving the space would look like a regression.
    gold = [p for p in ordered_gold() if p.label != "antonym"]
    gold.append(pair("antonym", "neara", "nearb"))  # scores ~0.98
    result = evaluate_space(SPACE, gold)
    assert result.antonym_mean > 0.9
    assert result.ranking_correct is True


def test_antonyms_are_excluded_from_the_graded_labels():
    assert "antonym" not in GRADED
    assert "complementary" not in GRADED


def test_complementary_pairs_are_a_separate_class_in_the_result():
    result = evaluate_space(SPACE, ordered_gold())
    assert result.by_label["complementary"].scored == 1
    assert result.complementary_mean == pytest.approx(0.71 / np.hypot(0.71, 0.71))


# --- missing terms ---------------------------------------------------------------------


def test_a_gold_tag_missing_from_the_vocabulary_is_reported_not_skipped_silently():
    # Silently dropping pairs would let a shrinking vocabulary look like a better score.
    gold = ordered_gold() + [pair("synonym", "neara", "not in the space")]
    result = evaluate_space(SPACE, gold)
    assert "not in the space" in result.missing_terms
    assert result.by_label["synonym"].pairs == 3
    assert result.by_label["synonym"].scored == 2


def test_a_space_missing_everything_scores_zero_rather_than_raising():
    empty = TagSpace(terms=(), vectors=np.zeros((0, 2)), meta={}, display={})
    result = evaluate_space(empty, ordered_gold())
    assert result.mean("synonym") == 0.0
    assert result.ranking_correct is False
    assert len(result.missing_terms) == 5


# --- the sweep -------------------------------------------------------------------------


def test_expand_grid_is_the_cartesian_product_in_a_stable_order():
    points = expand_grid({"a": [1, 2], "b": ["x", "y"]})
    assert points == [
        {"a": 1, "b": "x"},
        {"a": 1, "b": "y"},
        {"a": 2, "b": "x"},
        {"a": 2, "b": "y"},
    ]


def test_sweep_returns_one_result_per_grid_point():
    def builder(**_: object) -> TagSpace:
        return SPACE

    results = sweep(builder, {"rank": [1, 2, 3], "min_count": [3, 5]}, ordered_gold())
    assert len(results) == 6
    assert all(isinstance(point, dict) for point, _ in results)


def test_sweep_passes_each_point_to_the_builder():
    seen: list[dict] = []

    def builder(**point: object) -> TagSpace:
        seen.append(point)
        return SPACE

    sweep(builder, {"rank": [10, 20]}, ordered_gold())
    assert seen == [{"rank": 10}, {"rank": 20}]


def test_evaluation_is_reproducible_for_the_same_space():
    first = evaluate_space(SPACE, ordered_gold())
    second = evaluate_space(SPACE, ordered_gold())
    assert first == second


# --- rendering -------------------------------------------------------------------------


def test_render_marks_the_recorded_labels_as_not_graded():
    text = render_evaluation(evaluate_space(SPACE, ordered_gold()))
    assert "recorded, not graded" in text
    assert "Phase 2 baseline" in text


def test_render_reports_missing_terms():
    gold = ordered_gold() + [pair("synonym", "neara", "absent tag")]
    text = render_evaluation(evaluate_space(SPACE, gold))
    assert "absent tag" in text


def test_load_gold_reads_the_committed_file() -> None:
    gold: Sequence[GoldPair] = load_gold(REAL_GOLD_PATH)
    raw = json.loads(REAL_GOLD_PATH.read_text(encoding="utf-8"))
    assert len(gold) == len(raw["pairs"])

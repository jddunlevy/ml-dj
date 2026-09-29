import json
from pathlib import Path

import pytest

from mldj.match import normalize_artist, normalize_title, same_track, track_key

GOLD = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "match-gold.json").read_text(encoding="utf-8")
)


def gold_ids() -> list[str]:
    return [f"{p['label']}:{p['why']}" for p in GOLD["pairs"]]


@pytest.mark.parametrize("pair", GOLD["pairs"], ids=gold_ids())
def test_matcher_agrees_with_the_gold_set(pair):
    a = track_key(pair["a"]["artist"], pair["a"]["title"])
    b = track_key(pair["b"]["artist"], pair["b"]["title"])
    expected = pair["label"] == "same"
    assert same_track(a, b) is expected, (
        f"{pair['why']}\n  {pair['a']} -> {a}\n  {pair['b']} -> {b}"
    )


def test_normalize_title_strips_a_recognised_qualifier():
    assert normalize_title("Blue Monday - 2016 Remaster") == "blue monday"


def test_normalize_title_keeps_an_unrecognised_parenthetical():
    # Stripping every bracket would over-match, and over-matching deflates novelty.
    assert normalize_title("(Don't Fear) The Reaper") == "dont fear the reaper"


def test_normalize_title_never_returns_empty():
    assert normalize_title("(Remastered)") != ""


def test_normalize_artist_drops_a_featured_credit():
    assert normalize_artist("Odell ft. Paper Lanterns") == "odell"


def test_normalize_artist_keeps_a_genuine_collaboration():
    assert normalize_artist("Simon & Garfunkel") == "simon and garfunkel"


def test_track_key_is_a_pair_of_normalized_strings():
    assert track_key("New Order", "Blue Monday - 2016 Remaster") == ("new order", "blue monday")

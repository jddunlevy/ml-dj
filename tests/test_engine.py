import json
from pathlib import Path

import numpy as np
import pytest

from mldj.engine import cosine_all, session_new, session_run, session_step, tag_vector
from mldj.space.space import EXCLUDED_TERMS, TagSpace, load_space

TRACE_PATH = Path("fixtures/engine-trace.json")
SPACE_PATH = Path("space.json")
SESSION_PATH = Path("fixtures/session-synthetic.json")


def a_space() -> TagSpace:
    # Deliberately un-normalized rows: tag_vector must unit them before summing, and rows of
    # different length are the only way to see that it did.
    return TagSpace(
        terms=("indie", "shoegaze", "loud"),
        vectors=np.array([[3.0, 0.0], [0.0, 5.0], [0.0, 0.0]]),
        meta={},
    )


def test_tag_vector_sums_unit_vectors_so_a_long_tag_list_does_not_win_on_count():
    # R/space.R normalizes each row before summing; the Python port must agree or every
    # cosine in the trace is off. A raw sum here would be [3, 5].
    assert tag_vector(a_space(), ["indie", "shoegaze"]).tolist() == [1.0, 1.0]


def test_tag_vector_ignores_tags_the_space_does_not_hold():
    # Last.fm routinely returns tags the vocabulary filtered out. Dropping them is correct;
    # raising would make an ordinary session fatal.
    assert tag_vector(a_space(), ["indie", "notaterm"]).tolist() == [1.0, 0.0]


def test_tag_vector_of_nothing_recognised_is_the_zero_vector():
    assert tag_vector(a_space(), ["notaterm"]).tolist() == [0.0, 0.0]


def test_a_zero_norm_term_contributes_nothing_rather_than_a_nan():
    assert tag_vector(a_space(), ["loud"]).tolist() == [0.0, 0.0]


def test_tag_vector_dedupes_a_repeated_canonical_term_like_r_s_intersect():
    # R's tag_vector uses intersect(tags, space$terms), and R's intersect returns unique
    # matches. Python must agree: a tag list with "indie" twice must score the same as the
    # list with the duplicate removed, not double-count it.
    space = a_space()
    assert tag_vector(space, ["indie", "indie", "shoegaze"]).tolist() == tag_vector(
        space, ["indie", "shoegaze"]
    ).tolist()


def test_tag_vector_dedupes_differently_spelled_tags_that_canonicalize_the_same():
    # The real-world shape: Last.fm returns distinct strings ("Hip-Hop", "hip hop") that
    # canonical_tag collapses onto one term. An inline space with a real-looking VARIANTS-
    # style canonicalization is not needed here - canonical_tag itself does the collapsing
    # (casefolding and punctuation-stripping), so "Indie" and "INDIE " both land on "indie".
    space = a_space()
    assert tag_vector(space, ["Indie", "INDIE ", "shoegaze"]).tolist() == tag_vector(
        space, ["indie", "shoegaze"]
    ).tolist()


def test_a_completed_track_adds_its_tags():
    state = session_step(
        session_new(a_space(), decay=0.5, w=2.0), {"outcome": "completed", "tags": ["indie"]}
    )
    assert state.v.tolist() == [2.0, 0.0]


def test_a_skipped_track_subtracts_its_tags_scaled_by_earliness():
    state = session_step(
        session_new(a_space(), decay=1.0, w=1.0),
        {"outcome": "skipped", "tags": ["indie"], "earliness": 0.25},
    )
    assert state.v.tolist() == [-0.25, 0.0]


def test_an_unknown_outcome_decays_without_updating():
    # An ambiguous record may not have been a skip, so it cannot found a negative claim.
    state = session_new(a_space(), decay=0.5)
    state.v[:] = [4.0, 0.0]
    stepped = session_step(state, {"outcome": "unknown", "tags": ["indie"]})
    assert stepped.v.tolist() == [2.0, 0.0]


def test_a_skip_with_no_earliness_raises_rather_than_assuming_a_full_penalty():
    with pytest.raises(ValueError, match="earliness"):
        session_step(session_new(a_space()), {"outcome": "skipped", "tags": ["indie"]})


def test_an_unrecognised_outcome_raises():
    with pytest.raises(ValueError, match="bogus"):
        session_step(session_new(a_space()), {"outcome": "bogus", "tags": []})


def test_earliness_is_clamped_to_the_unit_interval():
    state = session_step(
        session_new(a_space(), decay=1.0),
        {"outcome": "skipped", "tags": ["indie"], "earliness": 9.0},
    )
    assert state.v.tolist() == [-1.0, 0.0]


def test_session_step_leaves_the_input_state_untouched():
    # Per-step states have to be keepable: R's scrubber holds a list of them, and the spec's
    # deferred per-step ranking would need one. Mutating in place would alias them all.
    state = session_new(a_space(), decay=0.5, w=1.0)
    stepped = session_step(state, {"outcome": "completed", "tags": ["indie"]})
    assert state.v.tolist() == [0.0, 0.0]
    assert state.history == []
    assert stepped.v.tolist() == [1.0, 0.0]
    assert stepped is not state


def test_session_run_applies_every_event_in_order_and_records_history():
    events = [
        {"outcome": "completed", "tags": ["indie"]},
        {"outcome": "completed", "tags": ["shoegaze"]},
    ]
    state = session_run(session_new(a_space(), decay=0.5, w=1.0), events)
    # The first event has been decayed once; the second was added whole.
    assert state.v.tolist() == [0.5, 1.0]
    assert len(state.history) == 2


def test_cosine_all_is_descending_and_breaks_ties_in_the_space_term_order():
    # R sorts with a stable sort, so equal cosines keep the space's own ordering. np.argsort
    # promises nothing there, and TagSpace.neighbours breaks ties by term NAME instead - a
    # different rule. Copying that rule here would desynchronise the trace.
    #
    # Terms are deliberately out of alphabetical order ("b" before "a"). With identical
    # vectors, the space's positional order and alphabetical order agree only when the terms
    # happen to already be alphabetical - which would let the by-name rule this test is meant
    # to rule out pass right along with the correct one. Putting "b" first makes the two
    # rules disagree: the correct (positional) rule keeps ["b", "a"], the forbidden (by-name)
    # rule would produce ["a", "b"].
    space = TagSpace(terms=("b", "a"), vectors=np.array([[1.0, 0.0], [1.0, 0.0]]), meta={})
    assert [term for term, _ in cosine_all(space, np.array([1.0, 0.0]))] == ["b", "a"]


def test_cosine_all_scores_a_zero_vector_at_zero_everywhere_rather_than_nan():
    assert [score for _, score in cosine_all(a_space(), np.zeros(2))] == [0.0, 0.0, 0.0]


@pytest.mark.skipif(not SPACE_PATH.exists(), reason="space.json is gitignored")
def test_the_python_engine_reproduces_the_golden_trace_r_is_held_to():
    golden = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    space = load_space(SPACE_PATH, exclude=EXCLUDED_TERMS)

    # The trace records cosines, so it pins the algorithm AND the space it was taken against.
    # Without this check a rebuilt vocabulary reads as "the engine changed" and sends you
    # hunting in the wrong file.
    assert len(space.terms) == golden["space_terms"], (
        f"space.json has {len(space.terms)} terms, the trace was taken against "
        f"{golden['space_terms']} - regenerate with tools/build-engine-trace.R; "
        "the engine is not at fault"
    )

    events = json.loads(SESSION_PATH.read_text(encoding="utf-8"))["events"]
    state = session_new(space, decay=golden["decay"], w=golden["w"])
    for i, event in enumerate(events):
        state = session_step(state, event)
        top = cosine_all(space, state.v)[:5]
        expected = golden["steps"][i]
        assert [term for term, _ in top] == expected["terms"], f"step {i + 1} term order"
        assert [round(score, 6) for _, score in top] == pytest.approx(
            expected["cos"], abs=1e-6
        ), f"step {i + 1} cosines"

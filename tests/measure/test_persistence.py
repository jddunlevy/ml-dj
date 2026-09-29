import json

from fakes import FakeClock, FakeTransport, make_play
from mldj.lastfm import LastfmClient
from mldj.match import track_key
from mldj.measure.persistence import TagIndex, build_tag_index, post_skip_persistence
from mldj.transport import Response


def tag_index(**by_title: list[str]) -> TagIndex:
    """TagIndex keyed by title, with a fixed artist - enough for the Jaccard tests."""
    return TagIndex(
        {track_key("Odell", title): frozenset(tags) for title, tags in by_title.items()}
    )


EMPTY_TAGS = TagIndex({})


def test_a_repeat_artist_after_a_skip_counts_as_persistence():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("Odell", "Low Ceiling", "completed", started_at_ms=1000),
    ]
    arm = post_skip_persistence(plays, EMPTY_TAGS).after_skip
    assert (arm.transitions, arm.same_artist, arm.artist_rate) == (1, 1, 1.0)


def test_a_different_artist_after_a_skip_does_not():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("New Order", "Blue Monday", "completed", started_at_ms=1000),
    ]
    arm = post_skip_persistence(plays, EMPTY_TAGS).after_skip
    assert (arm.transitions, arm.same_artist, arm.artist_rate) == (1, 0, 0.0)


def test_artist_comparison_is_normalized():
    # "Odell ft. X" and "Odell" are the same artist persisting.
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("Odell ft. Paper Lanterns", "Low Ceiling", "completed", started_at_ms=1000),
    ]
    assert post_skip_persistence(plays, EMPTY_TAGS).after_skip.same_artist == 1


def test_transitions_never_span_two_sessions():
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0, session="s1"),
        make_play("Odell", "B", "completed", started_at_ms=1000, session="s1"),
        make_play("Odell", "C", "completed", started_at_ms=2000, session="s2"),
    ]
    result = post_skip_persistence(plays, EMPTY_TAGS)
    assert result.after_skip.transitions == 1
    # B -> C would be a completion transition if sessions were wrongly joined.
    assert result.after_completion.transitions == 0


def test_a_transition_touching_an_unknown_play_is_excluded_and_counted():
    # 'unknown' means the record is ambiguous, so neither the transition into it nor the
    # one out of it can be read as evidence either way.
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0),
        make_play("Odell", "B", "unknown", started_at_ms=1000),
        make_play("Odell", "C", "completed", started_at_ms=2000),
    ]
    result = post_skip_persistence(plays, EMPTY_TAGS)
    assert result.excluded_unknown == 2
    assert result.after_skip.transitions == 0
    assert result.after_completion.transitions == 0


def test_the_completion_arm_is_computed_separately():
    plays = [
        make_play("Odell", "A", "completed", started_at_ms=0),
        make_play("Odell", "B", "skipped", started_at_ms=1000),
        make_play("New Order", "C", "completed", started_at_ms=2000),
    ]
    result = post_skip_persistence(plays, EMPTY_TAGS)
    assert (result.after_completion.transitions, result.after_completion.same_artist) == (1, 1)
    assert (result.after_skip.transitions, result.after_skip.same_artist) == (1, 0)


def test_artist_delta_is_completion_minus_skip():
    # The finding is the contrast. A delta near zero says the DJ does not back off after a
    # skip, which is the "it isn't listening" claim quantified.
    plays = [
        make_play("Odell", "A", "completed", started_at_ms=0),
        make_play("Odell", "B", "skipped", started_at_ms=1000),
        make_play("New Order", "C", "completed", started_at_ms=2000),
    ]
    result = post_skip_persistence(plays, EMPTY_TAGS)
    assert result.after_completion.artist_rate == 1.0
    assert result.after_skip.artist_rate == 0.0
    assert result.artist_delta == 1.0


def test_tag_jaccard_is_the_mean_overlap_of_the_two_tag_sets():
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0),
        make_play("Odell", "B", "completed", started_at_ms=1000),
    ]
    tags = tag_index(A=["mellow", "dream pop"], B=["mellow", "shoegaze"])
    arm = post_skip_persistence(plays, tags).after_skip
    assert arm.tagged_transitions == 1
    assert round(arm.mean_tag_jaccard, 4) == round(1 / 3, 4)  # {mellow} / 3 distinct


def test_tag_jaccard_ignores_transitions_where_either_side_is_untagged():
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0),
        make_play("Odell", "Untagged", "completed", started_at_ms=1000),
    ]
    tags = tag_index(A=["mellow"])
    arm = post_skip_persistence(plays, tags).after_skip
    assert arm.transitions == 1
    assert arm.tagged_transitions == 0
    assert arm.mean_tag_jaccard == 0.0


def test_tagged_transitions_reports_the_usable_denominator():
    # Thin Last.fm coverage means this can be far below `transitions`, and beat 6's
    # tag-coverage caveat needs the real number.
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0),
        make_play("Odell", "B", "skipped", started_at_ms=1000),
        make_play("Odell", "Untagged", "completed", started_at_ms=2000),
    ]
    tags = tag_index(A=["mellow"], B=["mellow"])
    arm = post_skip_persistence(plays, tags).after_skip
    assert (arm.transitions, arm.tagged_transitions) == (2, 1)


def test_no_transitions_yields_zero_rates_not_a_division_error():
    result = post_skip_persistence([make_play("Odell", "A", "skipped")], EMPTY_TAGS)
    assert result.after_skip.transitions == 0
    assert result.after_skip.artist_rate == 0.0
    assert result.artist_delta == 0.0


def test_build_tag_index_fetches_each_distinct_track_once():
    body = json.dumps(
        {"toptags": {"tag": [{"name": "mellow", "count": 90}, {"name": "dream pop", "count": 50}]}}
    ).encode()
    transport = FakeTransport([Response(200, body)])
    client = LastfmClient(transport, FakeClock(), api_key="k")
    plays = [
        make_play("Odell", "Static Bloom", started_at_ms=0),
        make_play("Odell", "Static Bloom", started_at_ms=1000),  # same track, no second call
    ]
    index = build_tag_index(client, plays, cache_dir=None)
    assert len(transport.requests) == 1
    assert index.tags("Odell", "Static Bloom") == frozenset({"mellow", "dream pop"})


def test_build_tag_index_keeps_only_the_top_n_tags():
    tags = [{"name": f"tag{i}", "count": 100 - i} for i in range(10)]
    body = json.dumps({"toptags": {"tag": tags}}).encode()
    client = LastfmClient(FakeTransport([Response(200, body)]), FakeClock(), api_key="k")
    index = build_tag_index(
        client, [make_play("Odell", "Static Bloom")], top_n=3, cache_dir=None
    )
    assert index.tags("Odell", "Static Bloom") == frozenset({"tag0", "tag1", "tag2"})


def test_build_tag_index_refuses_tracks_outside_the_track_tier():
    # Phase 1 can give any track a vector by inheritance. Feeding those here would have the
    # metric measure the backoff: two tracks inheriting one artist's tags overlap at 1.0 by
    # construction, whatever the DJ did.
    body = json.dumps({"toptags": {"tag": [{"name": "mellow", "count": 90}]}}).encode()
    transport = FakeTransport([Response(200, body)])
    client = LastfmClient(transport, FakeClock(), api_key="k")
    plays = [
        make_play("Odell", "has own tags", started_at_ms=0),
        make_play("Odell", "inherited only", started_at_ms=1000),
    ]
    index = build_tag_index(
        client,
        plays,
        cache_dir=None,
        track_tier_only={track_key("Odell", "has own tags")},
    )
    assert index.tags("Odell", "has own tags") == frozenset({"mellow"})
    assert index.tags("Odell", "inherited only") == frozenset()
    # Only one request: the excluded track is never even fetched.
    assert len(transport.requests) == 1


def test_a_transition_into_a_non_track_tier_track_is_not_counted_as_tagged():
    plays = [
        make_play("Odell", "A", "skipped", started_at_ms=0),
        make_play("Odell", "B", "completed", started_at_ms=1000),
    ]
    # B is not track-tier, so it has no tags and the transition is untagged - reported as
    # such rather than scored at a spurious 1.0 overlap.
    tags = TagIndex({track_key("Odell", "A"): frozenset({"mellow"})})
    arm = post_skip_persistence(plays, tags).after_skip
    assert arm.transitions == 1
    assert arm.tagged_transitions == 0

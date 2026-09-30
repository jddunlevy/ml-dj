from mldj.export import earliness_of, session_events
from mldj.skips import Play


def _play(outcome: str, listened_ms: int, duration_ms: int = 200_000) -> Play:
    return Play(
        track_id="t1", title="Space Song", artist="Beach House",
        duration_ms=duration_ms, started_at_ms=1_000, ended_at_ms=2_000,
        listened_ms=listened_ms, outcome=outcome, session="dj-x", label="dj", reason="",
    )


def test_earliness_is_one_for_an_instant_skip():
    assert earliness_of(_play("skipped", 0)) == 1.0


def test_earliness_is_zero_for_a_completed_track():
    assert earliness_of(_play("completed", 200_000)) == 0.0


def test_earliness_scales_with_how_far_in_the_skip_landed():
    assert earliness_of(_play("skipped", 50_000)) == 0.75


def test_earliness_never_goes_negative_when_listened_exceeds_duration():
    # A track played past its reported duration must not produce a negative weight.
    assert earliness_of(_play("completed", 260_000)) == 0.0


def test_events_carry_canonical_tags_not_raw_lastfm_strings():
    events = session_events([_play("skipped", 0)], lambda a, t: ["Dream Pop", "shoe-gaze"])
    assert events[0]["tags"] == ["dreampop", "shoegaze"]


def test_unknown_outcome_survives_into_the_event():
    events = session_events([_play("unknown", 0)], lambda a, t: [])
    assert events[0]["outcome"] == "unknown"


def test_novel_is_true_when_the_track_is_absent_from_history():
    events = session_events([_play("completed", 200_000)], lambda a, t: [], was_heard=None)
    assert events[0]["novel"] is True


def test_novel_is_false_when_history_has_heard_it():
    events = session_events(
        [_play("completed", 200_000)], lambda a, t: [], was_heard=lambda a, t: True
    )
    assert events[0]["novel"] is False


def test_each_event_carries_the_normalized_join_key():
    # Pairs with the key on each candidate: R flags the DJ's actual pick by comparing these,
    # never by comparing raw Spotify strings against Last.fm ones.
    from mldj.match import track_key

    play = Play(
        track_id="t1", title="Blue Monday - 2016 Remaster", artist="New Order",
        duration_ms=200_000, started_at_ms=1_000, ended_at_ms=2_000,
        listened_ms=200_000, outcome="completed", session="dj-x", label="dj", reason="",
    )
    events = session_events([play], lambda a, t: ["dreampop"])
    assert events[0]["key"] == list(track_key("New Order", "Blue Monday"))
    # The raw strings are untouched - the key is for joining, the strings are for display.
    assert events[0]["title"] == "Blue Monday - 2016 Remaster"

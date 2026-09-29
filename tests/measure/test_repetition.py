from fakes import make_play
from mldj.measure.repetition import repetition_rate

DAY_MS = 86_400_000


def test_replaying_a_track_skipped_earlier_in_the_session_counts():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0, session="s1"),
        make_play("New Order", "Blue Monday", "completed", started_at_ms=1000, session="s1"),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=2000, session="s1"),
    ]
    result = repetition_rate(plays)
    assert result.replays_of_skipped == 1
    assert (result.within_session, result.cross_session) == (1, 0)
    assert result.plays == 3
    assert round(result.rate, 4) == round(1 / 3, 4)


def test_replaying_a_track_skipped_in_an_earlier_session_counts_as_cross_session():
    # This is beat 1's hook: "it plays something you skipped yesterday".
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0, session="s1"),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=DAY_MS, session="s2"),
    ]
    result = repetition_rate(plays)
    assert result.replays_of_skipped == 1
    assert (result.within_session, result.cross_session) == (0, 1)


def test_a_skip_does_not_count_as_a_replay_of_itself():
    # The skip map must be consulted before the current play is recorded into it.
    plays = [make_play("Odell", "Static Bloom", "skipped", started_at_ms=0)]
    assert repetition_rate(plays).replays_of_skipped == 0


def test_a_second_skip_of_the_same_track_is_a_replay():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=1000),
    ]
    assert repetition_rate(plays).replays_of_skipped == 1


def test_a_skip_older_than_the_window_does_not_count():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0, session="s1"),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=20 * DAY_MS, session="s2"),
    ]
    assert repetition_rate(plays, window_days=14).replays_of_skipped == 0
    assert repetition_rate(plays, window_days=30).replays_of_skipped == 1


def test_a_completed_track_replayed_is_not_a_replay_of_a_skip():
    plays = [
        make_play("Odell", "Static Bloom", "completed", started_at_ms=0),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=1000),
    ]
    assert repetition_rate(plays).replays_of_skipped == 0


def test_an_unknown_outcome_never_seeds_a_skip():
    # An ambiguous record may not have been a skip, so it cannot found a repetition claim.
    plays = [
        make_play("Odell", "Static Bloom", "unknown", started_at_ms=0),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=1000),
    ]
    result = repetition_rate(plays)
    assert result.replays_of_skipped == 0
    assert result.plays == 2  # but it still occupies the denominator


def test_a_remaster_replayed_matches_the_skipped_original():
    plays = [
        make_play("New Order", "Blue Monday", "skipped", started_at_ms=0),
        make_play("New Order", "Blue Monday - 2016 Remaster", "completed", started_at_ms=1000),
    ]
    assert repetition_rate(plays).replays_of_skipped == 1


def test_examples_report_the_prior_skip_count():
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=1000),
        make_play("Odell", "Static Bloom", "completed", started_at_ms=2000),
    ]
    result = repetition_rate(plays)
    assert result.examples[-1] == ("Odell", "Static Bloom", 2)


def test_plays_are_ordered_by_time_not_by_input_order():
    plays = [
        make_play("Odell", "Static Bloom", "completed", started_at_ms=2000),
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
    ]
    assert repetition_rate(plays).replays_of_skipped == 1


def test_no_plays_yields_a_zero_rate_not_a_division_error():
    result = repetition_rate([])
    assert (result.plays, result.replays_of_skipped, result.rate) == (0, 0, 0.0)

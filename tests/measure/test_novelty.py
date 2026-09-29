from fakes import make_play
from mldj.measure.novelty import build_history, novelty_rate
from mldj.scrobbles import Scrobble


def history(*pairs):
    return build_history(
        Scrobble(uts=i, artist=a, title=t, album="") for i, (a, t) in enumerate(pairs)
    )


def test_a_track_in_history_is_not_novel():
    seen = history(("New Order", "Blue Monday"))
    result = novelty_rate([make_play("New Order", "Blue Monday")], seen)
    assert (result.plays, result.novel_plays) == (1, 0)
    assert result.play_rate == 0.0


def test_a_track_absent_from_history_is_novel():
    seen = history(("New Order", "Blue Monday"))
    result = novelty_rate([make_play("Odell", "Static Bloom")], seen)
    assert (result.plays, result.novel_plays) == (1, 1)
    assert result.play_rate == 1.0
    assert result.novel_examples == [("Odell", "Static Bloom")]


def test_a_remaster_matches_its_history_entry():
    # The matcher's whole job. Without it this play would be counted as never heard.
    result = novelty_rate(
        [make_play("New Order", "Blue Monday - 2016 Remaster")],
        history(("New Order", "Blue Monday")),
    )
    assert result.novel_plays == 0


def test_play_rate_and_track_rate_differ_when_a_novel_track_repeats():
    # A DJ replaying one novel track three times must not triple-count as exploration.
    plays = [make_play("Odell", "Static Bloom", started_at_ms=i * 1000) for i in range(3)]
    plays.append(make_play("New Order", "Blue Monday", started_at_ms=9_000))
    result = novelty_rate(plays, history(("New Order", "Blue Monday")))
    assert (result.plays, result.novel_plays) == (4, 3)
    assert result.play_rate == 0.75
    assert (result.distinct_tracks, result.novel_tracks) == (2, 1)
    assert result.track_rate == 0.5


def test_an_unknown_outcome_still_counts_as_a_play():
    # Novelty is about what the DJ *played*; how the play ended is irrelevant here, which
    # is why this measure differs from persistence and repetition.
    result = novelty_rate([make_play("Odell", "Static Bloom", "unknown")], history())
    assert result.plays == 1
    assert result.excluded_unknown == 0


def test_empty_history_makes_everything_novel():
    result = novelty_rate([make_play("Odell", "Static Bloom")], history())
    assert result.play_rate == 1.0
    assert result.track_rate == 1.0


def test_no_plays_yields_zero_rates_not_a_division_error():
    result = novelty_rate([], history(("New Order", "Blue Monday")))
    assert (result.plays, result.play_rate, result.track_rate) == (0, 0.0, 0.0)


def test_a_zero_duration_play_is_excluded():
    result = novelty_rate([make_play("x", "y", duration_ms=0)], history())
    assert result.plays == 0


def test_novel_examples_are_capped_and_deduplicated():
    plays = [make_play("Odell", f"Track {i}", started_at_ms=i * 1000) for i in range(5)]
    plays += [make_play("Odell", "Track 0", started_at_ms=99_000)]
    result = novelty_rate(plays, history(), examples=2)
    assert len(result.novel_examples) == 2
    assert result.novel_tracks == 5  # the repeat does not add a sixth


def test_novel_examples_are_in_first_played_order():
    plays = [
        make_play("Odell", "Second", started_at_ms=1),
        make_play("Odell", "First", started_at_ms=0),
    ]
    result = novelty_rate(plays, history())
    assert result.novel_examples == [("Odell", "Second"), ("Odell", "First")]

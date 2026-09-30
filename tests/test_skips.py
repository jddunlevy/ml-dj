from pathlib import Path

from mldj.events import read_events
from mldj.skips import Play, derive_plays

FIXTURE = Path(__file__).parent.parent / "fixtures" / "session-dj-sample.jsonl"


def sample_plays() -> list[Play]:
    return derive_plays(read_events(FIXTURE))


def test_every_track_run_becomes_one_play_and_ads_are_excluded():
    plays = sample_plays()
    assert [p.track_id for p in plays] == ["a1", "b2", "c3", "d4", "e5", "f6"]


def test_a_track_played_to_the_end_is_completed():
    play = sample_plays()[0]
    assert play.outcome == "completed"
    assert play.listened_ms == 180000
    assert play.reason == ""


def test_an_early_skip_is_detected_with_its_fraction():
    play = sample_plays()[1]
    assert play.outcome == "skipped"
    assert play.listened_ms == 6000
    assert round(play.listened_fraction, 3) == 0.025


def test_a_late_skip_is_still_a_skip():
    # Skip weighting in Phase 3 needs the fraction, so late skips must not be silently dropped.
    play = sample_plays()[2]
    assert play.outcome == "skipped"
    assert play.listened_ms == 151000
    assert round(play.listened_fraction, 3) == 0.755


def test_a_track_interrupted_by_an_ad_is_unknown_not_skipped():
    play = sample_plays()[3]
    assert play.outcome == "unknown"
    assert "non-track" in play.reason


def test_a_track_spanning_a_capture_gap_is_unknown():
    play = sample_plays()[4]
    assert play.outcome == "unknown"
    assert "gap" in play.reason


def test_the_final_truncated_track_is_unknown_not_skipped():
    # Ctrl-C is not a skip. Counting it as one would inflate the headline skip rate.
    play = sample_plays()[5]
    assert play.outcome == "unknown"
    assert "session ended" in play.reason


def test_every_play_carries_its_session_and_label():
    plays = sample_plays()
    assert {p.session for p in plays} == {"20250930T010000Z"}
    assert {p.label for p in plays} == {"dj"}


def test_a_stale_last_poll_makes_the_transition_unknown():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 1000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {
            "t": 60_000, "type": "poll", "kind": "track", "id": "y", "title": "U", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 60_000,
        },
        {"t": 61_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "stale" in first.reason


def test_progress_moving_backwards_makes_the_play_unknown():
    # A seek back or a restart means interpolated progress is not listening time.
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 30000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 100000, "is_playing": True, "fetched_at": 0,
        },
        {
            "t": 30_000, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 2000, "is_playing": True, "fetched_at": 30_000,
        },
        {
            "t": 31_000, "type": "poll", "kind": "track", "id": "y", "title": "U", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 31_000,
        },
        {"t": 32_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "backwards" in first.reason


def test_playback_going_idle_is_unknown_not_a_skip():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 30000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {"t": 30_000, "type": "idle"},
        {"t": 31_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "stopped" in first.reason


def test_a_zero_duration_run_produces_no_play():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 1000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 0, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {"t": 1_000, "type": "session_end", "reason": "stopped"},
    ]
    assert derive_plays(events) == []


# Crossfade. Spotify starts the next track before the current one ends, so capture sees the
# change early and the outgoing track looks short by the crossfade length. Measured on a real
# session (dj-20260930T142116Z), the shortfalls of everything then classed as `skipped` fell
# into two populations with a 173-second gap between them:
#
#   6135 15232 15656 16623 17120 22422 29055  |  202310 223334 228197 236453 246353 297719
#
# The left cluster is the crossfade; the right is the next button. Any threshold inside that
# gap classifies the session identically, so the exact value is not delicate - which is the
# only reason it is safe to pick one at all.


def _session(*polls: dict, interval_ms: int = 1000) -> list[dict]:
    head = {"t": 0, "type": "session_start", "label": "dj", "interval_ms": interval_ms,
            "session": "s1"}
    return [head, *polls]


def _poll(t: int, track: str, progress_ms: int, duration_ms: int = 200_000) -> dict:
    return {"t": t, "type": "poll", "kind": "track", "id": track, "title": track,
            "artist": "A", "duration_ms": duration_ms, "progress_ms": progress_ms,
            "is_playing": True, "fetched_at": t}


def test_a_track_cut_short_by_a_crossfade_is_completed_not_skipped():
    # 184s of a 200s track: 92%, the shape every crossfaded completion in the real session had.
    plays = derive_plays(_session(
        _poll(0, "a", 0), _poll(184_000, "a", 184_000), _poll(185_000, "b", 0),
    ))
    assert plays[0].outcome == "completed"
    assert round(plays[0].listened_fraction, 2) == 0.93


def test_the_completion_fraction_is_a_floor_not_a_replacement_for_the_grace():
    # A short track is the case a fractional rule alone gets wrong: 85% of a 40s interlude is
    # 6 seconds short, which is well inside a crossfade. The absolute grace still applies.
    plays = derive_plays(_session(
        _poll(0, "a", 0, duration_ms=40_000), _poll(38_000, "a", 38_000, duration_ms=40_000),
        _poll(39_000, "b", 0, duration_ms=40_000),
    ))
    assert plays[0].outcome == "completed"


def test_a_genuine_early_skip_is_untouched_by_the_crossfade_allowance():
    plays = derive_plays(_session(
        _poll(0, "a", 0), _poll(20_000, "a", 20_000), _poll(21_000, "b", 0),
    ))
    assert plays[0].outcome == "skipped"
    assert round(plays[0].listened_fraction, 3) == 0.105


def test_the_completion_fraction_is_tunable_so_a_listener_without_crossfade_can_tighten_it():
    events = _session(_poll(0, "a", 0), _poll(184_000, "a", 184_000), _poll(185_000, "b", 0))
    assert derive_plays(events, completion_fraction=0.99)[0].outcome == "skipped"


def test_an_ambiguous_run_stays_unknown_however_complete_it_looks():
    # The crossfade allowance must not promote an ambiguous record to a positive claim. A
    # backwards seek is still unknown at 93% played.
    plays = derive_plays(_session(
        _poll(0, "a", 0), _poll(100_000, "a", 100_000), _poll(101_000, "a", 10_000),
        _poll(184_000, "a", 184_000), _poll(185_000, "b", 0),
    ))
    assert plays[0].outcome == "unknown"

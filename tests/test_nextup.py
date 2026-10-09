"""The bridge from a session vector to a real queue write.

The cooldown tests are the load-bearing ones. Artist-tier tags make every track by an artist
score identically, so without a cooldown the top pick is systematically the artist who just
played - measured on the real 142116Z session at 2 of 3 positions. A demo that answers a skip
by queueing more of the same artist argues against this project's own thesis.
"""

import json

import numpy as np
import pytest

from fakes import FakeTransport
from mldj.library import ScorableTrack
from mldj.nextup import (
    Pick,
    choose_next,
    deliver,
    recent_artists,
)
from mldj.playback import PlaybackError
from mldj.space.space import TagSpace
from mldj.transport import Response


def token() -> str:
    return "tok"


def a_space() -> TagSpace:
    """Two orthogonal terms, so a tag list maps to a vector a test can reason about."""
    return TagSpace(
        terms=("indie", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
        meta={},
    )


def track(uri, artist, title, tags=("indie",), novel=False) -> ScorableTrack:
    return ScorableTrack(uri, artist, title, tuple(tags), "track", novel)


def event(artist, title, outcome="completed", tags=("indie",), earliness=None):
    e = {
        "artist": artist,
        "title": title,
        "key": [artist.casefold(), title.casefold()],
        "tags": list(tags),
        "tier": "track",
        "outcome": outcome,
        "novel": False,
    }
    if outcome == "skipped":
        e["earliness"] = 0.9 if earliness is None else earliness
    return e


# ---------------------------------------------------------------- recent_artists


def test_recent_artists_is_casefolded_so_capitalisation_cannot_defeat_the_cooldown():
    events = [event("Paper Lanterns", "Ceiling Fan")]
    assert recent_artists(events, 5) == {"paper lanterns"}


def test_recent_artists_looks_back_only_the_cooldown_window():
    events = [event("A", "1"), event("B", "2"), event("C", "3")]
    assert recent_artists(events, 2) == {"b", "c"}


def test_a_cooldown_of_zero_cools_nothing():
    assert recent_artists([event("A", "1")], 0) == set()


def test_each_credited_artist_is_cooled_separately():
    """Capture records the whole Spotify credit - "Marla Quinn, Theo Vance" - while the
    library row is "Marla Quinn". Comparing the strings whole lets a multi-artist credit walk
    straight through artist rotation, which is how the engine came to queue the track that was
    playing at that moment. Observed live on 2026-10-08."""
    events = [event("Marla Quinn, Theo Vance", "Glass Harbour")]

    cooled = recent_artists(events, 5)

    assert "marla quinn" in cooled
    assert "theo vance" in cooled
    assert "marla quinn, theo vance" in cooled  # the whole credit still matches itself


def test_an_ampersand_credit_is_split_too():
    cooled = recent_artists([event("Birch & Holloway", "x")], 5)
    assert cooled >= {"birch", "holloway", "birch & holloway"}


def test_a_featured_credit_is_split():
    cooled = recent_artists([event("Nadia Croft feat. Rell", "x")], 5)
    assert "nadia croft" in cooled
    assert "rell" in cooled


def test_splitting_does_not_invent_empty_artists():
    assert "" not in recent_artists([event("A,, B", "x")], 5)


def test_choose_next_will_not_queue_a_co_credited_artist_who_just_played():
    """The whole bug, end to end: the library row names one artist, the session names two."""
    pool = [
        track("spotify:track:1", "Marla Quinn", "Glass Harbour", tags=("indie",)),
        track("spotify:track:2", "Someone Else", "Another Song", tags=("indie",)),
    ]
    events = [event("Marla Quinn, Theo Vance", "Glass Harbour", tags=("indie",))]

    pick = choose_next(a_space(), events, pool, cooldown=5, min_score=0.0)

    assert pick is not None
    assert pick.artist == "Someone Else"


# ---------------------------------------------------------------- choose_next


def test_choose_next_returns_the_top_scoring_track_in_the_pool():
    pool = [
        track("spotify:track:1", "Far", "Low", tags=("shoegaze",)),
        track("spotify:track:2", "Near", "High", tags=("indie",)),
    ]
    pick = choose_next(a_space(), [event("Seed", "S", tags=("indie",))], pool, min_score=0.0)

    assert pick is not None
    assert pick.uri == "spotify:track:2"
    assert pick.pool_size == 2


def test_choose_next_will_not_queue_the_artist_who_just_played():
    """The finding this module exists for. Without the cooldown the answer is 'Same'."""
    pool = [
        track("spotify:track:same", "Same", "Another", tags=("indie",)),
        track("spotify:track:other", "Other", "Different", tags=("indie",)),
    ]
    events = [event("Same", "First", tags=("indie",))]

    pick = choose_next(a_space(), events, pool, cooldown=5, min_score=0.0)

    assert pick is not None
    assert pick.artist == "Other"


def test_an_artist_older_than_the_cooldown_window_is_eligible_again():
    pool = [track("spotify:track:1", "Old", "Track", tags=("indie",))]
    events = [event("Old", "Earlier"), event("B", "2"), event("C", "3")]

    assert choose_next(a_space(), events, pool, cooldown=2, min_score=0.0) is not None


def test_choose_next_never_returns_a_track_the_session_already_played():
    pool = [track("spotify:track:1", "Same", "Played", tags=("indie",))]
    events = [event("Same", "Played", tags=("indie",))]

    assert choose_next(a_space(), events, pool, cooldown=0, min_score=0.0) is None


def test_choose_next_declines_when_no_candidate_clears_the_confidence_floor():
    """A decayed vector scoring 0.06 is the engine performing confidence it does not have.
    Declining is the honest output, and on stage it is the better moment."""
    pool = [track("spotify:track:1", "Far", "Away", tags=("shoegaze",))]
    events = [event("Seed", "S", tags=("indie",))]

    assert choose_next(a_space(), events, pool, min_score=0.25) is None


def test_choose_next_returns_none_on_an_empty_pool():
    assert choose_next(a_space(), [event("A", "1")], [], min_score=0.0) is None


def test_choose_next_returns_none_when_the_cooldown_empties_the_pool():
    pool = [track("spotify:track:1", "Only", "Track", tags=("indie",))]
    events = [event("Only", "Other", tags=("indie",))]

    assert choose_next(a_space(), events, pool, cooldown=5, min_score=0.0) is None


# ---------------------------------------------------------------- deliver


def a_pick(uri="spotify:track:1") -> Pick:
    return Pick(uri=uri, artist="Night Cartography", title="Slow Transit", score=0.69,
                rank=7, novel=False, pool_size=4154)


def test_deliver_posts_the_pick_to_the_queue_and_records_it(tmp_path):
    state = tmp_path / "queued.json"
    transport = FakeTransport([Response(204, b"")])

    result = deliver(transport, token, a_pick(), state_path=state)

    assert result.written is True
    assert result.reason == "queued"
    method, url, _ = transport.requests[0]
    assert method == "POST_JSON"
    assert "me/player/queue" in url
    assert json.loads(state.read_text("utf-8"))["uri"] == "spotify:track:1"


def test_a_dry_run_makes_no_call_at_all(tmp_path):
    """Opt-in, and a test rather than a promise - the same guard playlist.py leans on."""
    transport = FakeTransport([])

    result = deliver(transport, token, a_pick(), dry_run=True, state_path=tmp_path / "q.json")

    assert result.written is False
    assert result.reason == "dry-run"
    assert transport.requests == []


def test_deliver_refuses_to_queue_the_same_pick_twice(tmp_path):
    """The queue is append-only with no remove. On stage, a second keystroke is permanent."""
    state = tmp_path / "queued.json"
    transport = FakeTransport([Response(204, b"")])
    deliver(transport, token, a_pick(), state_path=state)

    again = FakeTransport([])
    result = deliver(again, token, a_pick(), state_path=state)

    assert result.written is False
    assert result.reason == "duplicate"
    assert again.requests == []


def test_force_overrides_the_duplicate_guard(tmp_path):
    state = tmp_path / "queued.json"
    deliver(FakeTransport([Response(204, b"")]), token, a_pick(), state_path=state)

    transport = FakeTransport([Response(204, b"")])
    result = deliver(transport, token, a_pick(), state_path=state, force=True)

    assert result.written is True
    assert len(transport.requests) == 1


def test_a_different_pick_is_not_a_duplicate(tmp_path):
    state = tmp_path / "queued.json"
    deliver(FakeTransport([Response(204, b"")]), token, a_pick("spotify:track:1"),
            state_path=state)

    transport = FakeTransport([Response(204, b"")])
    result = deliver(transport, token, a_pick("spotify:track:2"), state_path=state)

    assert result.written is True


def test_deliver_lets_a_no_active_device_error_surface(tmp_path):
    """No fallback here. A 404 means the demo's premise is missing and silence would hide it."""
    transport = FakeTransport([Response(404, b'{"error":{"reason":"NO_ACTIVE_DEVICE"}}')])

    with pytest.raises(PlaybackError):
        deliver(transport, token, a_pick(), state_path=tmp_path / "q.json")


def test_a_failed_write_is_not_recorded_as_written(tmp_path):
    """Otherwise the duplicate guard blocks the retry of a write that never happened."""
    state = tmp_path / "queued.json"
    transport = FakeTransport([Response(404, b"{}")])

    with pytest.raises(PlaybackError):
        deliver(transport, token, a_pick(), state_path=state)

    assert not state.exists()

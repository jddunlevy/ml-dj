import json

import numpy as np
import pytest

from fakes import FakeTransport
from mldj.library import ScorableTrack
from mldj.playlist import (
    ADD_CHUNK,
    PlaylistError,
    Ranked,
    add_tracks,
    create_playlist,
    current_user_id,
    exclude_played,
    playlist_description,
    publish_playlist,
    rank_library,
    thin_by_artist,
)
from mldj.space.space import TagSpace
from mldj.transport import Response


def a_space() -> TagSpace:
    return TagSpace(
        terms=("indie", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
        meta={},
    )


def track(uri: str, artist: str, title: str, tags=("indie",), novel=False) -> ScorableTrack:
    return ScorableTrack(uri, artist, title, tuple(tags), "track", novel)


def test_a_track_played_in_the_session_is_excluded_from_the_pool():
    # A session-adaptive playlist that opens with the track you just skipped is self-evidently
    # broken.
    tracks = [track("spotify:track:1", "X", "A"), track("spotify:track:2", "Y", "B")]
    events = [{"key": ["x", "a"]}]
    assert [t.title for t in exclude_played(tracks, events)] == ["B"]


def test_exclusion_joins_on_the_normalized_key_so_a_remaster_suffix_cannot_slip_through():
    # Note the key literals keep their spaces: normalize_artist("New Order") is "new order",
    # NOT "neworder". canonical_tag strips spaces for TAGS ("New Wave" -> "newwave") but the
    # track-key normalizers do not. Getting this wrong writes a test that fails whatever the
    # implementation does.
    tracks = [track("spotify:track:1", "New Order", "Blue Monday - 2016 Remaster")]
    events = [{"key": ["new order", "blue monday"]}]
    assert exclude_played(tracks, events) == []


def test_ranking_orders_by_cosine_against_the_session_vector():
    tracks = [
        track("spotify:track:1", "X", "Shoegazey", tags=("shoegaze",)),
        track("spotify:track:2", "Y", "Indieish", tags=("indie",)),
    ]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["Indieish", "Shoegazey"]
    assert [r.rank for r in ranked] == [1, 2]


def test_epsilon_lifts_a_novel_track_and_zero_epsilon_leaves_the_order_alone():
    tracks = [
        track("spotify:track:1", "X", "Known", tags=("indie",), novel=False),
        track("spotify:track:2", "Y", "New", tags=("shoegaze",), novel=True),
    ]
    v = np.array([1.0, 0.4])
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=0.0)] == ["Known", "New"]
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=1.0)] == ["New", "Known"]


def test_a_zero_session_vector_scores_everything_at_zero_rather_than_nan():
    ranked = rank_library(a_space(), np.zeros(2), [track("spotify:track:1", "X", "A")])
    assert ranked[0].score == 0.0


def test_ties_keep_the_pool_order_so_a_rerun_produces_the_same_playlist():
    # Strengthened fixture: titles and URIs are deliberately scrambled relative to both pool
    # order and each other, so this can only pass if the implementation preserves the POOL's
    # own order among ties. A tie-break that sorted by title ("Apple","Banana","Cherry") or by
    # uri ("...2","...5","...9") would each produce a DIFFERENT order from the pool's own
    # ("Banana","Apple","Cherry") - so either forbidden rule is caught, not just one of them.
    tracks = [
        track("spotify:track:9", "X", "Banana"),
        track("spotify:track:2", "X", "Apple"),
        track("spotify:track:5", "X", "Cherry"),
    ]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["Banana", "Apple", "Cherry"]


def test_thinning_caps_tracks_per_artist():
    # Artist-tier tags are identical across an artist's tracks, so they all score alike and a
    # stable sort keeps the block together. A 30-track playlist from six artists is the bug
    # the prototype's top_by_artist already found, wearing a different hat.
    ranked = [
        Ranked(1, "spotify:track:1", "X", "A", 0.9, False),
        Ranked(2, "spotify:track:2", "X", "B", 0.9, False),
        Ranked(3, "spotify:track:3", "X", "C", 0.9, False),
        Ranked(4, "spotify:track:4", "Y", "D", 0.5, False),
    ]
    thinned = thin_by_artist(ranked, limit=10, per_artist=2)
    assert [r.title for r in thinned] == ["A", "B", "D"]
    # Ranks must be the TRUE ranks from the full pool, not renumbered: dropping rank 3 (C)
    # must leave a gap, since the gap is the tie structure made visible. A test that checks
    # titles alone cannot tell a correct skip-and-keep from a silent renumbering to [1, 2, 3].
    assert [r.rank for r in thinned] == [1, 2, 4]


def test_thinning_returns_what_exists_rather_than_padding_to_the_limit():
    ranked = [Ranked(1, "spotify:track:1", "X", "A", 0.9, False)]
    thinned = thin_by_artist(ranked, limit=30, per_artist=2)
    assert len(thinned) == 1
    assert thinned[0].rank == 1


def test_thinning_stops_at_the_limit():
    ranked = [
        Ranked(i + 1, f"spotify:track:{i}", f"A{i}", f"T{i}", 1.0 - i / 10, False)
        for i in range(5)
    ]
    thinned = thin_by_artist(ranked, limit=3, per_artist=1)
    assert len(thinned) == 3
    # Every artist here is distinct, so per_artist=1 never itself turns a row away - this
    # isolates the limit from the per-artist cap, rather than letting the two coincide and
    # leaving it ambiguous which one did the work.
    assert [r.rank for r in thinned] == [1, 2, 3]


def ok(payload: dict) -> Response:
    return Response(200, json.dumps(payload).encode())


def test_create_playlist_posts_a_private_playlist_and_returns_its_id():
    transport = FakeTransport([ok({"id": "pl1"})])
    pid = create_playlist(transport, lambda: "tok", "me", "ml-dj - s1", "provenance")
    assert pid == "pl1"
    method, url, payload = transport.requests[0]
    assert (method, url) == ("POST_JSON", "https://api.spotify.com/v1/users/me/playlists")
    assert payload == {"name": "ml-dj - s1", "public": False, "description": "provenance"}


def test_add_chunk_is_pinned_to_spotifys_documented_ceiling():
    # ADD_CHUNK is a load-bearing external constraint, not a tunable: Spotify's playlist-items
    # add endpoint rejects a request over 100 URIs. Pin the literal so the constant cannot drift
    # without a test noticing - asserting it against itself (as the chunking test below used to)
    # would pass for any value and catch nothing.
    assert ADD_CHUNK == 100


def test_add_tracks_chunks_at_the_api_limit():
    # Sizes are hardcoded, not derived from ADD_CHUNK: deriving the input and the expected chunk
    # sizes from the same imported constant makes this pass for ANY value of ADD_CHUNK, which is
    # exactly how a reviewer's ADD_CHUNK = 50 slipped through all 19 tests before this fix.
    uris = [f"spotify:track:{i}" for i in range(105)]
    transport = FakeTransport([ok({"snapshot_id": "a"}), ok({"snapshot_id": "b"})])
    assert add_tracks(transport, lambda: "tok", "pl1", uris) == 105
    assert len(transport.requests) == 2
    assert len(transport.requests[0][2]["uris"]) == 100
    assert len(transport.requests[1][2]["uris"]) == 5


def test_add_tracks_makes_no_request_for_an_empty_list():
    transport = FakeTransport([])
    assert add_tracks(transport, lambda: "tok", "pl1", []) == 0
    assert transport.requests == []


def test_a_401_refreshes_once_and_retries():
    transport = FakeTransport([Response(401, b""), ok({"id": "pl1"})])
    refreshed = []
    pid = create_playlist(
        transport, lambda: "tok", "me", "n", "d",
        on_unauthorized=lambda: refreshed.append(True),
    )
    assert pid == "pl1"
    assert refreshed == [True]


def test_a_second_401_raises_rather_than_looping():
    transport = FakeTransport([Response(401, b""), Response(401, b"")])
    with pytest.raises(PlaylistError, match="401"):
        create_playlist(
            transport, lambda: "tok", "me", "n", "d", on_unauthorized=lambda: None
        )


def test_a_403_names_the_scope_because_forbidden_alone_sends_you_to_the_wrong_place():
    transport = FakeTransport([Response(403, b'{"error":{"message":"Forbidden"}}')])
    with pytest.raises(PlaylistError, match="playlist-modify-private"):
        create_playlist(transport, lambda: "tok", "me", "n", "d")


def test_current_user_id_reads_the_profile():
    transport = FakeTransport([ok({"id": "me"})])
    assert current_user_id(transport, lambda: "tok") == "me"
    assert transport.requests[0][1] == "https://api.spotify.com/v1/me"


def test_a_dry_run_makes_no_request_at_all_and_returns_no_playlist_id():
    # The guard the spec leans on when it makes --dry-run opt-in: the worst case of a mistaken
    # real run is a stray private playlist, and the worst case of a dry run is nothing.
    transport = FakeTransport([])
    result = publish_playlist(
        transport, lambda: "tok",
        name="n", description="d", uris=["spotify:track:1"], dry_run=True,
    )
    assert result is None
    assert transport.requests == []


def test_publishing_for_real_reads_the_profile_creates_the_playlist_and_adds_the_tracks():
    transport = FakeTransport([ok({"id": "me"}), ok({"id": "pl1"}), ok({"snapshot_id": "s"})])
    result = publish_playlist(
        transport, lambda: "tok",
        name="n", description="d", uris=["spotify:track:1"], dry_run=False,
    )
    assert result == "pl1"
    assert [r[0] for r in transport.requests] == ["GET", "POST_JSON", "POST_JSON"]


def test_the_description_records_what_produced_the_playlist():
    # A playlist that cannot say which space produced it is not reproducible, and the space is
    # rebuilt often enough for that to matter: the 2026-09-30 stoplist moved the vocabulary
    # from 371 terms to 323 and shifted every cosine.
    text = playlist_description(
        "dj-20260930T142116Z", 1504, 0.85, 1.0, 0.0,
        {"vocabulary_size": 323, "built_utc": "2026-09-30T10:19:00+00:00"},
    )
    for fragment in ("dj-20260930T142116Z", "1504", "0.85", "323", "2026-09-30"):
        assert fragment in text
    # w and epsilon are asserted as labelled substrings, not bare numbers: w=1.0 and
    # vocabulary_size=323 both contain digits that recur elsewhere in the string, and
    # epsilon=0.0 is easy to match by accident against some other "0". "w 1.0" and
    # "epsilon 0.0" are how playlist_description actually labels them, so these can only pass
    # if both fields are genuinely present with their values.
    assert "w 1.0" in text
    assert "epsilon 0.0" in text

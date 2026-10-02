import json

import pytest

from fakes import FakeTransport
from mldj.library import (
    SAVED_URL,
    TOP_URL,
    LibraryCoverage,
    LibraryTrack,
    fetch_library,
    read_library,
    render_coverage,
    tag_library,
    write_library,
)
from mldj.match import track_key
from mldj.transport import Response


def ok(payload: dict) -> Response:
    return Response(200, json.dumps(payload).encode())


def saved(name: str, artist: str, uri: str) -> dict:
    # /v1/me/tracks wraps each row in `track`; /v1/me/top/tracks does not. The shapes differ
    # and a reader that assumes one silently returns nothing for the other.
    return {"track": {"uri": uri, "name": name, "artists": [{"name": artist}]}}


def top(name: str, artist: str, uri: str) -> dict:
    return {"uri": uri, "name": name, "artists": [{"name": artist}]}


def test_fetch_library_follows_pagination_to_the_end():
    # The saved endpoint is genuinely two pages: "B" exists only on the second page, reachable
    # only by following the first page's `next` link. The top endpoint is a single, distinct
    # page. A reader that fetches exactly one page per endpoint consumes "B" from the wrong
    # endpoint (coincidentally still producing a title match) but leaves "C" unfetched and the
    # request trail wrong - which the request assertion below catches even if titles happened
    # to line up.
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": "https://api/saved-page-2"}),
        ok({"items": [saved("B", "X", "spotify:track:2")], "next": None}),
        ok({"items": [top("C", "Z", "spotify:track:3")], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert [t.title for t in tracks] == ["A", "B", "C"]
    assert [(method, url) for method, url, _headers in transport.requests] == [
        ("GET", SAVED_URL),
        ("GET", "https://api/saved-page-2"),
        ("GET", TOP_URL),
    ]


def test_fetch_library_reads_both_the_saved_and_the_top_endpoints():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("B", "Y", "spotify:track:2")], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert {t.title for t in tracks} == {"A", "B"}


def test_fetch_library_deduplicates_on_uri_because_a_top_track_is_usually_also_saved():
    # Same uri, but a different title and artist on each row - the shape of a retitled
    # remaster. Only a dedupe keyed on uri (not title) collapses these to one row, and the
    # survivor must be the first-seen (saved-endpoint) one.
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("A (Remastered)", "X Band", "spotify:track:1")], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert len(tracks) == 1
    assert tracks[0] == LibraryTrack("spotify:track:1", "X", "A")


def test_fetch_library_skips_rows_that_are_not_playable_spotify_tracks():
    # Local files and podcast episodes both appear in a saved-tracks page and neither can be
    # added to a playlist by URI.
    transport = FakeTransport([
        ok({"items": [
            {"track": {"uri": "spotify:local:x", "name": "L", "artists": [{"name": "X"}]}},
            {"track": None},
            saved("A", "X", "spotify:track:1"),
        ], "next": None}),
        ok({"items": [], "next": None}),
    ])
    assert [t.uri for t in fetch_library(transport, lambda: "tok")] == ["spotify:track:1"]


def test_fetch_library_sends_the_bearer_token():
    transport = FakeTransport([
        ok({"items": [], "next": None}),
        ok({"items": [], "next": None}),
    ])
    fetch_library(transport, lambda: "tok")
    _method, _url, headers = transport.requests[0]
    assert headers["Authorization"] == "Bearer tok"


def test_fetch_library_calls_access_token_fresh_for_every_request():
    # access_token is Callable[[], str] precisely because a long session outlives a one-hour
    # token. A regression to "read once, reuse" would send the same bearer on every request;
    # this fails that by returning a different token each call and checking they all differ.
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": "https://api/saved-page-2"}),
        ok({"items": [saved("B", "X", "spotify:track:2")], "next": None}),
        ok({"items": [top("C", "Z", "spotify:track:3")], "next": None}),
    ])
    tokens = iter(["tok1", "tok2", "tok3"])
    fetch_library(transport, lambda: next(tokens))
    bearers = [headers["Authorization"] for _method, _url, headers in transport.requests]
    assert bearers == ["Bearer tok1", "Bearer tok2", "Bearer tok3"]


def test_fetch_library_raises_rather_than_returning_a_partial_library_on_a_bad_page():
    # A non-200 mid-pagination must raise, not silently truncate the library - a silently
    # shrunk candidate pool would make recommendations look worse for no visible reason.
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": "https://api/saved-page-2"}),
        Response(500, b"internal server error"),
    ])
    with pytest.raises(RuntimeError, match="500"):
        fetch_library(transport, lambda: "tok")


def test_the_library_round_trips_through_its_cache_file(tmp_path):
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    path = tmp_path / "library.json"
    write_library(path, tracks)
    assert read_library(path) == tracks


def test_tag_library_finds_tags_through_the_normalized_key_not_the_raw_string():
    # The cache was filled from Last.fm's strings; the library carries Spotify's. "Blue Monday
    # - 2016 Remaster" and "Blue Monday" are one track, and only track_key knows that. A raw
    # string lookup here would report a well-tagged library as untagged.
    tracks = [LibraryTrack("spotify:track:1", "New Order", "Blue Monday - 2016 Remaster")]
    scorable, coverage = tag_library(
        tracks, {track_key("New Order", "Blue Monday"): ["newwave"]}, {}
    )
    assert [t.tags for t in scorable] == [("newwave",)]
    assert coverage.track_tier == 1


def test_tag_library_backs_off_to_the_artist_tier_and_records_the_tier():
    tracks = [LibraryTrack("spotify:track:1", "New Order", "Temptation")]
    scorable, coverage = tag_library(tracks, {}, {"new order": ["newwave"]})
    assert scorable[0].tier == "artist"
    assert coverage.artist_tier == 1


def test_an_untaggable_track_is_excluded_and_counted_rather_than_scored_at_zero():
    # A zero vector entered at rank 0 invents a rank for a track nothing is known about, and
    # inflates the denominator of "ranked Nth of M".
    tracks = [LibraryTrack("spotify:track:1", "Nobody", "Untagged")]
    scorable, coverage = tag_library(tracks, {}, {})
    assert scorable == []
    assert coverage.untagged == 1


def test_tag_library_canonicalizes_tags_so_they_match_the_space_terms():
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    tagged = {track_key("X", "A"): ["New Wave", "", "Post-Punk"]}
    scorable, _ = tag_library(tracks, tagged, {})
    assert scorable[0].tags == ("newwave", "postpunk")


def test_novelty_comes_from_the_supplied_history_and_defaults_to_not_novel():
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    tagged = {track_key("X", "A"): ["rock"]}
    heard, _ = tag_library(tracks, tagged, {}, was_heard=lambda a, t: True)
    unheard, _ = tag_library(tracks, tagged, {}, was_heard=lambda a, t: False)
    default, _ = tag_library(tracks, tagged, {})
    assert (heard[0].novel, unheard[0].novel, default[0].novel) == (False, True, False)


def test_coverage_reports_the_scorable_share_of_the_library():
    coverage = LibraryCoverage(tracks=4, track_tier=1, artist_tier=2, untagged=1)
    assert coverage.scorable == 3
    assert coverage.coverage == 0.75


def test_coverage_of_an_empty_library_is_zero_rather_than_a_division_error():
    assert LibraryCoverage(0, 0, 0, 0).coverage == 0.0


def test_render_coverage_names_every_tier_so_a_thin_pool_is_attributable():
    text = render_coverage(LibraryCoverage(tracks=4, track_tier=1, artist_tier=2, untagged=1))
    assert "4" in text and "track 1" in text and "artist 2" in text and "75.0%" in text

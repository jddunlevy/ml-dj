import json

from fakes import FakeTransport
from mldj.library import LibraryTrack, fetch_library, read_library, write_library
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
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": "https://api/next"}),
        ok({"items": [saved("B", "X", "spotify:track:2")], "next": None}),
        ok({"items": [], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert [t.title for t in tracks] == ["A", "B"]


def test_fetch_library_reads_both_the_saved_and_the_top_endpoints():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("B", "Y", "spotify:track:2")], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert {t.title for t in tracks} == {"A", "B"}


def test_fetch_library_deduplicates_on_uri_because_a_top_track_is_usually_also_saved():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("A", "X", "spotify:track:1")], "next": None}),
    ])
    assert len(fetch_library(transport, lambda: "tok")) == 1


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


def test_the_library_round_trips_through_its_cache_file(tmp_path):
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    path = tmp_path / "library.json"
    write_library(path, tracks)
    assert read_library(path) == tracks

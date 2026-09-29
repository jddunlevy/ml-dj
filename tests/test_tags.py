import json
from pathlib import Path

from fakes import FakeClock, FakeTransport
from mldj.lastfm import LastfmClient
from mldj.scrobbles import Scrobble
from mldj.tags import coverage_only, pull_all, summarize
from mldj.transport import Response

FIXTURES = Path(__file__).parent.parent / "fixtures"
TOPTAGS = (FIXTURES / "lastfm-toptags.json").read_bytes()
ARTISTTAGS = (FIXTURES / "lastfm-artisttags.json").read_bytes()
EMPTY = json.dumps({"toptags": {"tag": []}}).encode()


def scrobble(artist, title, uts=1, album=""):
    return Scrobble(uts=uts, artist=artist, title=title, album=album)


def client(responses):
    return LastfmClient(FakeTransport(responses), FakeClock(), api_key="k")


# --- summarize: the pure arithmetic, independent of any fetching -----------------------


def test_summarize_reports_track_coverage():
    scrobbles = [scrobble("A", "one"), scrobble("A", "two")]
    summary = summarize(
        scrobbles,
        track_tags={("a", "one"): [("mellow", 9)], ("a", "two"): []},
        artist_tags={},
    )
    assert (summary.distinct_tracks, summary.track_tagged, summary.track_untagged) == (2, 1, 1)
    assert summary.track_coverage == 0.5


def test_summarize_weights_coverage_by_plays():
    # The tracks actually listened to matter more than the long tail of one-play tracks.
    scrobbles = [scrobble("A", "hit", uts=i) for i in range(9)] + [scrobble("A", "obscure", uts=99)]
    summary = summarize(
        scrobbles,
        track_tags={("a", "hit"): [("mellow", 9)], ("a", "obscure"): []},
        artist_tags={},
    )
    assert summary.track_coverage == 0.5
    assert summary.play_weighted_coverage == 0.9


def test_summarize_counts_album_siblings_that_rescue_an_untagged_track():
    scrobbles = [
        scrobble("A", "tagged", album="Record"),
        scrobble("A", "bare", album="Record"),
    ]
    summary = summarize(
        scrobbles,
        track_tags={("a", "tagged"): [("mellow", 9)], ("a", "bare"): []},
        artist_tags={},
    )
    assert summary.album_rescued == 1
    assert summary.coverage_after_album == 1.0


def test_summarize_never_pools_across_an_empty_album_string():
    # An absent album is not an album; pooling on it would join everything by that artist.
    scrobbles = [scrobble("A", "tagged", album=""), scrobble("A", "bare", album="")]
    summary = summarize(
        scrobbles,
        track_tags={("a", "tagged"): [("mellow", 9)], ("a", "bare"): []},
        artist_tags={},
    )
    assert summary.album_rescued == 0
    assert summary.coverage_after_album == 0.5


def test_summarize_never_pools_across_two_different_albums():
    scrobbles = [
        scrobble("A", "tagged", album="One"),
        scrobble("A", "bare", album="Two"),
    ]
    summary = summarize(
        scrobbles,
        track_tags={("a", "tagged"): [("mellow", 9)], ("a", "bare"): []},
        artist_tags={},
    )
    assert summary.album_rescued == 0


def test_summarize_reports_artist_coverage_and_distinct_tags():
    scrobbles = [scrobble("A", "one"), scrobble("B", "two")]
    summary = summarize(
        scrobbles,
        track_tags={("a", "one"): [("mellow", 9), ("dream pop", 4)], ("b", "two"): []},
        artist_tags={"a": [("shoegaze", 7)], "b": []},
    )
    assert (summary.distinct_artists, summary.artist_tagged) == (2, 1)
    assert summary.artist_coverage == 0.5
    assert summary.distinct_tags == 2  # track-tier tags only


def test_summarize_handles_an_empty_corpus_without_dividing_by_zero():
    summary = summarize([], track_tags={}, artist_tags={})
    assert (summary.track_coverage, summary.play_weighted_coverage) == (0.0, 0.0)
    assert summary.artist_coverage == 0.0


# --- pull_all and coverage_only --------------------------------------------------------


def test_pull_all_reports_track_and_artist_coverage(tmp_path):
    scrobbles = [scrobble("New Order", "Blue Monday"), scrobble("Nobody", "Nothing")]
    transport = FakeTransport(
        [
            Response(200, TOPTAGS),  # Blue Monday
            Response(200, EMPTY),  # Nothing
            Response(200, ARTISTTAGS),  # New Order
            Response(200, EMPTY),  # Nobody
        ]
    )
    summary = pull_all(
        LastfmClient(transport, FakeClock(), api_key="k"),
        scrobbles,
        tags_dir=tmp_path / "tags",
        artist_tags_dir=tmp_path / "artist-tags",
    )
    assert (summary.distinct_tracks, summary.track_tagged) == (2, 1)
    assert (summary.distinct_artists, summary.artist_tagged) == (2, 1)
    assert len(transport.requests) == 4


def test_pull_all_counts_a_failure_and_continues(tmp_path):
    scrobbles = [scrobble("Bad", "One"), scrobble("Good", "Two")]
    transport = FakeTransport(
        [
            Response(500, b"boom"),  # Bad - One, retried then given up on
            Response(500, b"boom"),
            Response(500, b"boom"),
            Response(500, b"boom"),
            Response(200, TOPTAGS),  # Good - Two still gets fetched
            Response(200, EMPTY),  # Bad the artist
            Response(200, ARTISTTAGS),  # Good the artist
        ]
    )
    summary = pull_all(
        LastfmClient(transport, FakeClock(), api_key="k"),
        scrobbles,
        tags_dir=tmp_path / "tags",
        artist_tags_dir=tmp_path / "artist-tags",
    )
    assert summary.failures == 1
    assert summary.track_tagged == 1  # the run did not stop at the failure


def test_pull_all_is_resumable_from_cache_with_no_requests(tmp_path):
    scrobbles = [scrobble("New Order", "Blue Monday")]
    dirs = dict(tags_dir=tmp_path / "tags", artist_tags_dir=tmp_path / "artist-tags")
    first = FakeTransport([Response(200, TOPTAGS), Response(200, ARTISTTAGS)])
    pull_all(LastfmClient(first, FakeClock(), api_key="k"), scrobbles, **dirs)

    again = FakeTransport([])  # any request would raise
    summary = pull_all(LastfmClient(again, FakeClock(), api_key="k"), scrobbles, **dirs)
    assert again.requests == []
    assert summary.track_tagged == 1


def test_pull_all_reports_progress(tmp_path):
    seen = []
    pull_all(
        LastfmClient(FakeTransport([Response(200, TOPTAGS), Response(200, ARTISTTAGS)]),
                     FakeClock(), api_key="k"),
        [scrobble("New Order", "Blue Monday")],
        tags_dir=tmp_path / "tags",
        artist_tags_dir=tmp_path / "artist-tags",
        on_progress=lambda stage, done, total: seen.append((stage, done, total)),
    )
    assert ("tracks", 1, 1) in seen
    assert ("artists", 1, 1) in seen


def test_coverage_only_makes_no_requests(tmp_path):
    scrobbles = [scrobble("New Order", "Blue Monday"), scrobble("Nobody", "Nothing")]
    dirs = dict(tags_dir=tmp_path / "tags", artist_tags_dir=tmp_path / "artist-tags")
    pull_all(
        LastfmClient(
            FakeTransport([Response(200, TOPTAGS), Response(200, EMPTY),
                           Response(200, ARTISTTAGS), Response(200, EMPTY)]),
            FakeClock(), api_key="k",
        ),
        scrobbles, **dirs,
    )
    summary = coverage_only(scrobbles, **dirs)
    assert (summary.distinct_tracks, summary.track_tagged) == (2, 1)
    assert summary.artist_tagged == 1


def test_coverage_only_treats_an_absent_cache_entry_as_untagged(tmp_path):
    summary = coverage_only(
        [scrobble("Never", "Fetched")],
        tags_dir=tmp_path / "tags",
        artist_tags_dir=tmp_path / "artist-tags",
    )
    assert (summary.track_tagged, summary.track_untagged) == (0, 1)


def test_summarize_reports_how_many_tracks_were_fetched():
    scrobbles = [scrobble("A", "one"), scrobble("A", "two")]
    summary = summarize(scrobbles, track_tags={("a", "one"): [("mellow", 9)]}, artist_tags={})
    assert summary.track_fetched == 1
    assert summary.distinct_tracks == 2


def test_coverage_only_separates_not_yet_fetched_from_untagged(tmp_path):
    # Mid-pull, an absent entry still counts as untagged in the coverage figure, but
    # track_fetched is what makes that figure readable.
    dirs = dict(tags_dir=tmp_path / "tags", artist_tags_dir=tmp_path / "artist-tags")
    pull_all(
        LastfmClient(FakeTransport([Response(200, TOPTAGS), Response(200, ARTISTTAGS)]),
                     FakeClock(), api_key="k"),
        [scrobble("New Order", "Blue Monday")], **dirs,
    )
    summary = coverage_only(
        [scrobble("New Order", "Blue Monday"), scrobble("Never", "Fetched")], **dirs
    )
    assert summary.distinct_tracks == 2
    assert summary.track_fetched == 1
    assert summary.track_tagged == 1
    assert summary.track_coverage == 0.5

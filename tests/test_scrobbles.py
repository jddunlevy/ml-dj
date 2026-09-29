import json
from pathlib import Path

from fakes import FakeClock, FakeTransport
from mldj.lastfm import LastfmClient
from mldj.scrobbles import Scrobble, ingest, parse_recent_tracks_page, read_scrobbles
from mldj.transport import Response

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAGE = json.loads((FIXTURES / "lastfm-recenttracks-page.json").read_text(encoding="utf-8"))

DAY = 86_400


def page_body(tracks, total_pages, page=1):
    return json.dumps(
        {
            "recenttracks": {
                "@attr": {"page": str(page), "totalPages": str(total_pages)},
                "track": tracks,
            }
        }
    ).encode()


def row(artist, title, uts, album=""):
    return {
        "artist": {"#text": artist},
        "album": {"#text": album},
        "name": title,
        "date": {"uts": str(uts)},
    }


def client(responses):
    return LastfmClient(FakeTransport(responses), FakeClock(), api_key="k")


def test_parse_skips_the_now_playing_entry_which_has_no_timestamp():
    # The now-playing row would otherwise become a scrobble with no date.
    rows, total_pages = parse_recent_tracks_page(PAGE)
    assert [r.title for r in rows] == ["Blue Monday", "Static Bloom"]
    assert total_pages == 3


def test_parse_reads_artist_title_album_and_uts():
    rows, _ = parse_recent_tracks_page(PAGE)
    assert rows[0] == Scrobble(
        uts=1759190400,
        artist="New Order",
        title="Blue Monday",
        album="Power, Corruption & Lies",
    )


def test_parse_tolerates_a_single_track_object_instead_of_a_list():
    # Last.fm collapses a one-element array to a bare object.
    payload = {"recenttracks": {"@attr": {"totalPages": "1"}, "track": row("A", "T", 10)}}
    rows, _ = parse_recent_tracks_page(payload)
    assert [r.title for r in rows] == ["T"]


def test_parse_returns_nothing_for_an_empty_page():
    payload = {"recenttracks": {"@attr": {"totalPages": "1"}, "track": []}}
    assert parse_recent_tracks_page(payload) == ([], 1)


def test_ingest_walks_every_page_and_writes_jsonl(tmp_path):
    transport = FakeTransport(
        [
            Response(200, page_body([row("New Order", "Blue Monday", 300)], 2, page=1)),
            Response(200, page_body([row("Odell", "Static Bloom", 200)], 2, page=2)),
        ]
    )
    path = tmp_path / "scrobbles.jsonl"
    summary = ingest(
        LastfmClient(transport, FakeClock(), api_key="k"), "listener", to_uts=1_000, path=path
    )
    assert summary.pages == 2
    assert summary.written == 2
    assert [s.title for s in read_scrobbles(path)] == ["Blue Monday", "Static Bloom"]


def test_ingest_pins_the_to_parameter_so_pages_cannot_shift(tmp_path):
    # New scrobbles arriving mid-ingest would otherwise duplicate or drop rows.
    transport = FakeTransport([Response(200, page_body([row("A", "T", 5)], 1))])
    lastfm = LastfmClient(transport, FakeClock(), api_key="k")
    ingest(lastfm, "listener", 999, path=tmp_path / "s.jsonl")
    _, url, _ = transport.requests[0]
    assert "to=999" in url


def test_ingest_is_idempotent_when_rerun(tmp_path):
    path = tmp_path / "s.jsonl"
    summary = None
    for _ in range(2):
        summary = ingest(
            client([Response(200, page_body([row("A", "T", 5)], 1))]), "listener", 999, path=path
        )
    assert summary is not None
    assert summary.written == 0
    assert summary.duplicates == 1
    assert len(read_scrobbles(path)) == 1


def test_ingest_counts_distinct_tracks_not_just_scrobbles(tmp_path):
    # Spec open question 4: the matrix is built from distinct tracks, not scrobbles.
    tracks = [
        row("New Order", "Blue Monday", 300),
        row("New Order", "Blue Monday - 2016 Remaster", 250),
        row("Odell", "Static Bloom", 200),
    ]
    summary = ingest(
        client([Response(200, page_body(tracks, 1))]), "listener", 999, path=tmp_path / "s.jsonl"
    )
    assert summary.written == 3
    assert summary.distinct_tracks == 2  # the remaster is the same song
    assert (summary.oldest_uts, summary.newest_uts) == (200, 300)


def test_ingest_reports_a_coverage_gap_when_the_history_is_stale(tmp_path):
    # Scrobbling silently stopped for 67 days in this project's real history. A track heard
    # inside such a gap is absent, so novelty would count it as never-heard and come out
    # overstated. The gap has to be reported, not discovered later.
    now = 100 * DAY
    summary = ingest(
        client([Response(200, page_body([row("A", "T", now - 67 * DAY)], 1))]),
        "listener",
        to_uts=now,
        path=tmp_path / "s.jsonl",
    )
    assert summary.gap_days == 67
    assert summary.stale is True


def test_ingest_reports_no_gap_for_a_current_history(tmp_path):
    now = 100 * DAY
    summary = ingest(
        client([Response(200, page_body([row("A", "T", now - 3600)], 1))]),
        "listener",
        to_uts=now,
        path=tmp_path / "s.jsonl",
    )
    assert summary.gap_days == 0
    assert summary.stale is False


def test_ingest_respects_max_pages(tmp_path):
    summary = ingest(
        client([Response(200, page_body([row("A", "T", 5)], 10))]),
        "listener",
        999,
        path=tmp_path / "s.jsonl",
        max_pages=1,
    )
    assert summary.pages == 1

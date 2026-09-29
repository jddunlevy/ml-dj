import json
from pathlib import Path

from mldj.nowplaying import NowPlaying, interpolate_progress, parse_now_playing

FIXTURES = Path(__file__).parent.parent / "fixtures"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parses_a_track_and_joins_every_artist():
    np = parse_now_playing(fixture("nowplaying-track.json"), fetched_at=1_000)
    assert np == NowPlaying(
        kind="track",
        id="2aBcDeFgHiJkLmNoPqRsTu",
        title="Ceiling Fan",
        artist="Paper Lanterns, Odell",
        duration_ms=213000,
        progress_ms=45000,
        is_playing=True,
        fetched_at=1_000,
    )


def test_parses_an_ad_as_a_zero_duration_placeholder():
    np = parse_now_playing(fixture("nowplaying-ad.json"), fetched_at=2_000)
    assert np is not None
    assert (np.kind, np.id, np.duration_ms, np.progress_ms) == ("ad", "ad", 0, 8000)


def test_parses_an_episode_using_the_show_name_as_the_artist():
    np = parse_now_playing(fixture("nowplaying-episode.json"), fetched_at=3_000)
    assert np is not None
    assert (np.kind, np.artist, np.duration_ms) == ("episode", "A Podcast About Tags", 1800000)


def test_returns_none_for_an_empty_body():
    # Spotify answers 204 with no body when nothing is playing.
    assert parse_now_playing(None, fetched_at=0) is None


def test_returns_none_when_the_item_is_missing():
    assert parse_now_playing({"currently_playing_type": "track", "item": None}, 0) is None


def test_returns_none_for_an_unknown_playing_type():
    assert parse_now_playing({"currently_playing_type": "unknown", "item": {}}, 0) is None


def test_interpolate_advances_progress_while_playing():
    np = NowPlaying("track", "x", "t", "a", 213000, 45000, True, fetched_at=10_000)
    assert interpolate_progress(np, now=12_500) == 47500


def test_interpolate_holds_progress_while_paused():
    np = NowPlaying("track", "x", "t", "a", 213000, 45000, False, fetched_at=10_000)
    assert interpolate_progress(np, now=99_000) == 45000


def test_interpolate_never_runs_past_the_duration():
    np = NowPlaying("track", "x", "t", "a", 213000, 210000, True, fetched_at=10_000)
    assert interpolate_progress(np, now=100_000) == 213000

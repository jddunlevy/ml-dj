"""Live refresh: re-derive the prototype's inputs as a capture log grows.

The point of these tests is that `live` decides *when* to do work, and does none of the
deriving itself. Skip detection, tagging and the candidate pool stay in the modules that
already own them - this module only notices that the log got longer.
"""

from pathlib import Path

import pytest

from mldj.live import Refresh, new_artists, newest_log, refresh, target_log


def _event(artist: str, title: str = "t", outcome: str = "completed") -> dict:
    return {"artist": artist, "title": title, "outcome": outcome, "tags": ["rock"]}


def test_newest_log_picks_the_most_recently_modified(tmp_path: Path) -> None:
    old = tmp_path / "dj-old.jsonl"
    new = tmp_path / "dj-new.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    import os

    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))

    assert newest_log(tmp_path) == new


def test_newest_log_is_none_when_there_are_no_logs(tmp_path: Path) -> None:
    assert newest_log(tmp_path) is None


def test_new_artists_is_empty_when_nothing_was_added() -> None:
    events = [_event("Kate Bush"), _event("James")]
    assert new_artists(events, events) == set()


def test_new_artists_reports_only_artists_not_seen_before() -> None:
    previous = [_event("Kate Bush")]
    current = [_event("Kate Bush"), _event("James"), _event("Kate Bush", "Cloudbusting")]
    assert new_artists(previous, current) == {"James"}


def test_new_artists_treats_no_previous_run_as_everything_being_new() -> None:
    current = [_event("Kate Bush"), _event("James")]
    assert new_artists(None, current) == {"Kate Bush", "James"}


def test_refresh_writes_both_files_on_the_first_run(tmp_path: Path) -> None:
    events = [_event("Kate Bush")]
    out = refresh(
        log=tmp_path / "dj.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: events,
        build_pool=lambda _e: [{"artist": "Peter Gabriel", "title": "Solsbury Hill"}],
        previous=None,
    )

    assert out == Refresh(events=events, session_written=True, candidates_written=True)
    assert (tmp_path / "live" / "session.json").exists()
    assert (tmp_path / "live" / "candidates.json").exists()


def test_refresh_skips_every_write_when_the_log_has_not_grown(tmp_path: Path) -> None:
    events = [_event("Kate Bush")]
    calls: list[str] = []

    out = refresh(
        log=tmp_path / "dj.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: events,
        build_pool=lambda _e: calls.append("pool") or [],
        previous=events,
    )

    assert out.session_written is False
    assert out.candidates_written is False
    assert calls == [], "the pool costs Last.fm calls and must not be rebuilt for nothing"
    assert not (tmp_path / "live" / "session.json").exists()


def test_refresh_rewrites_the_session_but_not_the_pool_for_a_familiar_artist(
    tmp_path: Path,
) -> None:
    """A second track by an artist already in the pool needs no new candidates.

    This is the whole reason the two files refresh on different triggers: the session is a
    local file write, the pool is a few dozen Last.fm round trips.
    """
    previous = [_event("Kate Bush")]
    current = [_event("Kate Bush"), _event("Kate Bush", "Cloudbusting")]
    calls: list[str] = []

    out = refresh(
        log=tmp_path / "dj.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: current,
        build_pool=lambda _e: calls.append("pool") or [],
        previous=previous,
    )

    assert out.session_written is True
    assert out.candidates_written is False
    assert calls == []


def test_refresh_rebuilds_the_pool_when_a_new_artist_appears(tmp_path: Path) -> None:
    previous = [_event("Kate Bush")]
    current = [_event("Kate Bush"), _event("James")]

    out = refresh(
        log=tmp_path / "dj.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: current,
        build_pool=lambda _e: [{"artist": "New Order", "title": "Ceremony"}],
        previous=previous,
    )

    assert out.session_written is True
    assert out.candidates_written is True


def test_refresh_writes_to_stable_names_so_shiny_can_watch_one_path(tmp_path: Path) -> None:
    """Shiny watches a fixed path. A session-stamped filename would mean the app had to be
    restarted every time a new capture began, which is the thing live mode exists to avoid.
    """
    refresh(
        log=tmp_path / "dj-20260930T142116Z.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: [_event("Kate Bush")],
        build_pool=lambda _e: [],
        previous=None,
    )

    names = sorted(p.name for p in (tmp_path / "live").iterdir())
    assert names == ["candidates.json", "session.json"]


def test_refresh_keeps_the_session_payload_shape_the_prototype_reads(tmp_path: Path) -> None:
    import json

    refresh(
        log=tmp_path / "dj-20260930T142116Z.jsonl",
        out_dir=tmp_path / "live",
        build_events=lambda _p: [_event("Kate Bush")],
        build_pool=lambda _e: [],
        previous=None,
    )

    payload = json.loads((tmp_path / "live" / "session.json").read_text(encoding="utf-8"))
    assert payload["session"] == "dj-20260930T142116Z"
    assert payload["label"] == "dj"
    assert len(payload["events"]) == 1


def test_refresh_raises_when_the_log_cannot_be_derived(tmp_path: Path) -> None:
    def explode(_p: Path) -> list[dict]:
        raise ValueError("malformed log")

    with pytest.raises(ValueError):
        refresh(
            log=tmp_path / "dj.jsonl",
            out_dir=tmp_path / "live",
            build_events=explode,
            build_pool=lambda _e: [],
            previous=None,
        )


# Pinning. `newest_log` is right while a capture is running, but it follows whatever was
# written last - so restarting a capture silently moves the app off a session you were still
# looking at. `--log` overrides it.


def test_target_log_follows_the_newest_when_nothing_is_pinned(tmp_path: Path) -> None:
    import os

    old, new = tmp_path / "dj-old.jsonl", tmp_path / "dj-new.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))

    assert target_log(tmp_path, None) == new


def test_target_log_returns_the_pinned_log_even_when_a_newer_one_exists(tmp_path: Path) -> None:
    import os

    pinned, newer = tmp_path / "dj-pinned.jsonl", tmp_path / "dj-newer.jsonl"
    pinned.write_text("{}\n", encoding="utf-8")
    newer.write_text("{}\n", encoding="utf-8")
    os.utime(pinned, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))

    assert target_log(tmp_path, pinned) == pinned


def test_target_log_raises_rather_than_silently_falling_back(tmp_path: Path) -> None:
    # Quietly following the newest log after a typo is exactly the surprise --log exists to
    # prevent, so a missing pin is an error.
    with pytest.raises(FileNotFoundError):
        target_log(tmp_path, tmp_path / "does-not-exist.jsonl")

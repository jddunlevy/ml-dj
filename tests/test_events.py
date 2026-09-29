from mldj.events import (
    EventWriter,
    gap_event,
    poll_event,
    read_events,
    session_end_event,
    session_id,
    session_path,
    session_start_event,
)
from mldj.nowplaying import NowPlaying


def test_session_id_is_a_sortable_utc_stamp():
    # 1759190400 epoch seconds is 2025-09-30T00:00:00Z exactly.
    assert session_id(1_759_190_400_000) == "20250930T000000Z"


def test_session_path_names_the_file_by_label_and_id(tmp_path):
    assert session_path("dj", "20250930T000000Z", tmp_path).name == "dj-20250930T000000Z.jsonl"


def test_writer_appends_one_json_object_per_line_and_read_events_round_trips(tmp_path):
    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        writer.write({"t": 1, "type": "a"})
        writer.write({"t": 2, "type": "b"})
    assert list(read_events(path)) == [{"t": 1, "type": "a"}, {"t": 2, "type": "b"}]


def test_writer_appends_rather_than_truncating(tmp_path):
    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        writer.write({"t": 1, "type": "a"})
    with EventWriter(path) as writer:
        writer.write({"t": 2, "type": "b"})
    assert [e["t"] for e in read_events(path)] == [1, 2]


def test_writer_flushes_every_line_so_a_ctrl_c_loses_nothing(tmp_path):
    # Capture runs for hours and ends with Ctrl-C; an unflushed tail is lost listening.
    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        writer.write({"t": 1, "type": "a"})
        assert list(read_events(path)) == [{"t": 1, "type": "a"}]


def test_read_events_skips_blank_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"t":1}\n\n{"t":2}\n', encoding="utf-8")
    assert [e["t"] for e in read_events(path)] == [1, 2]


def test_poll_event_carries_everything_needed_to_re_derive_a_play():
    np = NowPlaying("track", "id1", "Ceiling Fan", "Paper Lanterns", 213000, 45000, True, 900)
    assert poll_event(np, now_ms=1_000) == {
        "t": 1_000,
        "type": "poll",
        "kind": "track",
        "id": "id1",
        "title": "Ceiling Fan",
        "artist": "Paper Lanterns",
        "duration_ms": 213000,
        "progress_ms": 45000,
        "is_playing": True,
        "fetched_at": 900,
    }


def test_poll_event_for_nothing_playing_is_an_idle_event():
    assert poll_event(None, now_ms=1_000) == {"t": 1_000, "type": "idle"}


def test_session_start_records_the_interval_so_analysis_can_judge_staleness():
    event = session_start_event(1_000, "dj", 1000, "20250930T000000Z")
    assert event == {
        "t": 1_000,
        "type": "session_start",
        "label": "dj",
        "interval_ms": 1000,
        "session": "20250930T000000Z",
    }


def test_gap_and_end_events():
    assert gap_event(5, "rate-limited", 3000) == {
        "t": 5,
        "type": "gap",
        "reason": "rate-limited",
        "retry_ms": 3000,
    }
    assert session_end_event(9, "stopped") == {"t": 9, "type": "session_end", "reason": "stopped"}

import json
from pathlib import Path

from fakes import make_play
from mldj.measure.novelty import build_history
from mldj.measure.persistence import TagIndex
from mldj.measure.report import build_report, diagnostics, render_markdown, write_report
from mldj.scrobbles import Scrobble

FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "session-dj-sample.jsonl"
DAY = 86_400
EMPTY_TAGS = TagIndex({})


def write_session(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def poll(t, track_id, interval_ms=1000):
    return {
        "t": t, "type": "poll", "kind": "track", "id": track_id, "title": track_id,
        "artist": "A", "duration_ms": 200_000, "progress_ms": 0, "is_playing": True,
        "fetched_at": t,
    }


def start(interval_ms=1000):
    return {
        "t": 0, "type": "session_start", "label": "dj",
        "interval_ms": interval_ms, "session": "s1",
    }


def test_diagnostics_counts_polls_gaps_and_rate_limits():
    diag = diagnostics([FIXTURE])
    assert diag.polls == 19  # 18 track polls plus the ad poll
    assert diag.gaps == 1
    assert diag.rate_limited == 1
    assert diag.sessions == 1


def test_diagnostics_reports_the_declared_interval_from_session_start():
    assert diagnostics([FIXTURE]).declared_interval_ms == 30000


def test_diagnostics_counts_unknown_plays_by_reason():
    diag = diagnostics([FIXTURE])
    assert diag.unknown_plays == 3
    assert sum(diag.unknown_reasons.values()) == 3
    assert any("gap" in reason for reason in diag.unknown_reasons)


def test_verdict_flags_a_collapsed_fast_skip(tmp_path):
    # Changes at 0, 1000 and 2500 ms give gaps of 1000 and 1500 at a 1000 ms interval:
    # the shortest is one interval, so that burst was collapsed into a single poll.
    events = [start(1000), poll(0, "a"), poll(1000, "b"), poll(2500, "c")]
    diag = diagnostics([write_session(tmp_path / "s.jsonl", events)])
    assert diag.min_track_gap_ms == 1000
    assert "too slow" in diag.interval_verdict


def test_verdict_flags_rate_limiting(tmp_path):
    events = [
        start(1000),
        poll(0, "a"),
        {"t": 1000, "type": "gap", "reason": "rate-limited", "retry_ms": 3000},
        poll(100_000, "b"),
    ]
    diag = diagnostics([write_session(tmp_path / "s.jsonl", events)])
    assert diag.rate_limited == 1
    assert "too fast" in diag.interval_verdict


def test_verdict_is_adequate_when_neither_holds(tmp_path):
    events = [start(1000), poll(0, "a"), poll(50_000, "b"), poll(150_000, "c")]
    diag = diagnostics([write_session(tmp_path / "s.jsonl", events)])
    assert diag.interval_verdict.startswith("adequate")


def test_verdict_reports_both_problems_when_both_hold(tmp_path):
    events = [
        start(1000),
        poll(0, "a"),
        {"t": 500, "type": "gap", "reason": "rate-limited", "retry_ms": 3000},
        poll(1000, "b"),
        poll(2000, "c"),
    ]
    diag = diagnostics([write_session(tmp_path / "s.jsonl", events)])
    assert "too slow" in diag.interval_verdict
    assert "too fast" in diag.interval_verdict


def test_verdict_is_undetermined_without_enough_track_changes(tmp_path):
    events = [start(1000), poll(0, "a")]
    diag = diagnostics([write_session(tmp_path / "s.jsonl", events)])
    assert "undetermined" in diag.interval_verdict


def sample_report(**kwargs):
    plays = [
        make_play("Odell", "Static Bloom", "skipped", started_at_ms=0),
        make_play("Odell", "Low Ceiling", "completed", started_at_ms=1000),
        make_play("New Order", "Blue Monday", "unknown", started_at_ms=2000, reason="capture gap"),
    ]
    history = build_history([Scrobble(uts=1, artist="New Order", title="Blue Monday", album="")])
    defaults = dict(
        plays=plays,
        history=history,
        tags=EMPTY_TAGS,
        diag=diagnostics([FIXTURE]),
        now_uts=100 * DAY,
        history_newest_uts=100 * DAY - 67 * DAY,
    )
    return build_report(**{**defaults, **kwargs})


def test_build_report_is_json_serialisable():
    json.dumps(sample_report())  # raises TypeError if anything is a dataclass or a set


def test_build_report_includes_both_novelty_rates():
    novelty = sample_report()["novelty"]
    assert "play_rate" in novelty and "track_rate" in novelty


def test_build_report_reports_unknown_plays_by_reason():
    report = sample_report()
    assert report["diagnostics"]["unknown_reasons"]
    assert report["plays"]["unknown"] == 1


def test_build_report_quotes_repetition_at_several_windows():
    windows = sample_report()["repetition"]
    assert sorted(int(k) for k in windows) == [1, 7, 14]


def test_build_report_carries_the_scrobble_gap_caveat():
    report = sample_report()
    assert report["history"]["gap_days"] == 67
    assert report["history"]["novelty_is_upper_bound"] is True


def test_build_report_marks_novelty_exact_when_history_is_current():
    report = sample_report(history_newest_uts=100 * DAY - 3600)
    assert report["history"]["gap_days"] == 0
    assert report["history"]["novelty_is_upper_bound"] is False


def test_render_markdown_states_the_matcher_assumption():
    text = render_markdown(sample_report())
    assert "the song, not the recording" in text


def test_render_markdown_leads_with_the_caveats():
    text = render_markdown(sample_report())
    assert text.index("What must be true") < text.index("Novelty")


def test_render_markdown_shows_both_novelty_rates_and_the_persistence_delta():
    text = render_markdown(sample_report())
    assert "per play" in text and "per track" in text
    assert "delta" in text.lower()


def test_write_report_writes_both_files(tmp_path):
    report = sample_report()
    paths = write_report(report, out_dir=tmp_path, stamp="2026-09-29")
    assert {p.name for p in paths} == {"phase0-2026-09-29.json", "phase0-2026-09-29.md"}
    assert json.loads((tmp_path / "phase0-2026-09-29.json").read_text(encoding="utf-8"))
    assert (tmp_path / "phase0-2026-09-29.md").read_text(encoding="utf-8").startswith("#")

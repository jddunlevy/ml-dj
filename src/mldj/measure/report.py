"""Assemble the three measurements into one artifact, and settle the poll interval.

Two jobs beyond arithmetic.

**Justify the poll interval by measurement.** CLAUDE.md requires the chosen value be
defended with data rather than assumed. `min_track_gap_ms` is the shortest observed spacing
between consecutive track changes: if it sits at or below two poll intervals, changes are
landing inside the polling resolution and fast skips are being collapsed, so the interval is
too slow. Any 429 says the opposite - too fast. Both can be true at once, in which case both
are reported rather than one being picked.

**Surface the report's own weaknesses first.** Beat 6 is graded on honesty, not on clean
numbers, so the Markdown leads with what must be true: the share of plays too ambiguous to
classify and why, how many transitions actually had tags on both sides, the matcher's stated
assumption, the scrobble gap, and both novelty rates rather than the flattering one.

reports/ is gitignored. These numbers belong in the deck and the vault, not the public repo.
"""

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from mldj.events import read_events
from mldj.measure.novelty import HistoryIndex, NoveltyResult, novelty_rate
from mldj.measure.persistence import PersistenceResult, TagIndex, post_skip_persistence
from mldj.measure.repetition import repetition_rate
from mldj.skips import Play, derive_plays

REPORTS_DIR = Path("reports")
GOLD_PATH = Path("fixtures/match-gold.json")
DEFAULT_WINDOWS = (1, 7, 14)
SECONDS_PER_DAY = 86_400
STALE_AFTER_DAYS = 2


class Diagnostics:
    """Capture-health counters, and the poll-interval verdict derived from them."""

    def __init__(
        self,
        *,
        sessions: int,
        labels: dict[str, int],
        polls: int,
        idle: int,
        gaps: int,
        rate_limited: int,
        unknown_plays: int,
        unknown_reasons: dict[str, int],
        track_gaps_ms: list[int],
        declared_interval_ms: int,
        capture_ms: int,
    ) -> None:
        self.sessions = sessions
        self.labels = labels
        self.polls = polls
        self.idle = idle
        self.gaps = gaps
        self.rate_limited = rate_limited
        self.unknown_plays = unknown_plays
        self.unknown_reasons = unknown_reasons
        self.declared_interval_ms = declared_interval_ms
        self.capture_ms = capture_ms
        ordered = sorted(track_gaps_ms)
        self.min_track_gap_ms = ordered[0] if ordered else 0
        self.p05_track_gap_ms = ordered[int(0.05 * (len(ordered) - 1))] if ordered else 0
        self.interval_verdict = self._verdict(bool(ordered))

    def _verdict(self, have_gaps: bool) -> str:
        problems: list[str] = []
        if have_gaps and self.min_track_gap_ms <= 2 * self.declared_interval_ms:
            problems.append(
                f"too slow: fast skips are being collapsed - shortest observed gap between "
                f"track changes was {self.min_track_gap_ms} ms at a "
                f"{self.declared_interval_ms} ms poll interval"
            )
        if self.rate_limited:
            problems.append(
                f"too fast: rate limits hit - {self.rate_limited} of {self.polls + self.gaps} "
                f"requests returned 429, and every 429 is a hole in the record"
            )
        if problems:
            return "; ".join(problems)
        if not have_gaps:
            return "undetermined: not enough track changes captured to judge the interval"
        return (
            f"adequate: shortest gap between track changes {self.min_track_gap_ms} ms and 5th "
            f"percentile {self.p05_track_gap_ms} ms, both clear of the "
            f"{self.declared_interval_ms} ms interval, with no 429s"
        )

    def as_dict(self) -> dict:
        return {
            "sessions": self.sessions,
            "labels": self.labels,
            "polls": self.polls,
            "idle": self.idle,
            "gaps": self.gaps,
            "rate_limited": self.rate_limited,
            "unknown_plays": self.unknown_plays,
            "unknown_reasons": self.unknown_reasons,
            "min_track_gap_ms": self.min_track_gap_ms,
            "p05_track_gap_ms": self.p05_track_gap_ms,
            "declared_interval_ms": self.declared_interval_ms,
            "capture_hours": round(self.capture_ms / 3_600_000, 2),
            "interval_verdict": self.interval_verdict,
        }


def diagnostics(paths: Iterable[Path]) -> Diagnostics:
    """Walk raw session logs for capture health and observed track-change spacing."""
    sessions = polls = idle = gaps = rate_limited = 0
    declared = 0
    capture_ms = 0
    labels: Counter[str] = Counter()
    unknown_reasons: Counter[str] = Counter()
    unknown_plays = 0
    track_gaps: list[int] = []

    for path in paths:
        events = list(read_events(path))
        change_times: list[int] = []
        current_id: str | None = None
        first_t = last_t = None

        for event in events:
            kind = event.get("type")
            t = int(event.get("t", 0))
            first_t = t if first_t is None else first_t
            last_t = t
            if kind == "session_start":
                sessions += 1
                declared = max(declared, int(event.get("interval_ms") or 0))
                labels[str(event.get("label") or "")] += 1
            elif kind == "idle":
                idle += 1
            elif kind == "gap":
                gaps += 1
                if event.get("reason") == "rate-limited":
                    rate_limited += 1
            elif kind == "poll":
                polls += 1
                if event.get("kind") == "track" and event.get("id") != current_id:
                    current_id = str(event.get("id"))
                    change_times.append(t)

        if first_t is not None and last_t is not None:
            capture_ms += last_t - first_t
        track_gaps += [b - a for a, b in zip(change_times, change_times[1:], strict=False)]

        for play in derive_plays(events):
            if play.outcome == "unknown":
                unknown_plays += 1
                unknown_reasons[play.reason] += 1

    return Diagnostics(
        sessions=sessions,
        labels=dict(labels),
        polls=polls,
        idle=idle,
        gaps=gaps,
        rate_limited=rate_limited,
        unknown_plays=unknown_plays,
        unknown_reasons=dict(unknown_reasons),
        track_gaps_ms=track_gaps,
        declared_interval_ms=declared,
        capture_ms=capture_ms,
    )


def _matcher_assumption(gold_path: Path = GOLD_PATH) -> str:
    if not gold_path.exists():
        return "(fixtures/match-gold.json not found)"
    return str(json.loads(gold_path.read_text(encoding="utf-8")).get("assumption", ""))


def _novelty_dict(result: NoveltyResult) -> dict:
    return {
        "plays": result.plays,
        "novel_plays": result.novel_plays,
        "play_rate": round(result.play_rate, 4),
        "distinct_tracks": result.distinct_tracks,
        "novel_tracks": result.novel_tracks,
        "track_rate": round(result.track_rate, 4),
        "novel_examples": [list(pair) for pair in result.novel_examples],
    }


def _persistence_dict(result: PersistenceResult) -> dict:
    def arm(a):
        return {
            "transitions": a.transitions,
            "same_artist": a.same_artist,
            "artist_rate": round(a.artist_rate, 4),
            "mean_tag_jaccard": round(a.mean_tag_jaccard, 4),
            "tagged_transitions": a.tagged_transitions,
        }

    return {
        "after_skip": arm(result.after_skip),
        "after_completion": arm(result.after_completion),
        "artist_delta": round(result.artist_delta, 4),
        "tag_delta": round(result.tag_delta, 4),
        "excluded_unknown": result.excluded_unknown,
    }


def build_report(
    *,
    plays: Sequence[Play],
    history: HistoryIndex,
    tags: TagIndex,
    diag: Diagnostics,
    now_uts: int,
    history_newest_uts: int | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    examples: int = 20,
) -> dict:
    """Every Phase 0 number as one JSON-serialisable dict."""
    gap_days = 0
    if history_newest_uts is not None:
        gap_days = max(0, (now_uts - history_newest_uts) // SECONDS_PER_DAY)

    outcomes = Counter(p.outcome for p in plays)

    repetition: dict[str, dict] = {}
    for window in windows:
        result = repetition_rate(plays, window_days=window)
        repetition[str(window)] = {
            "plays": result.plays,
            "replays_of_skipped": result.replays_of_skipped,
            "within_session": result.within_session,
            "cross_session": result.cross_session,
            "rate": round(result.rate, 4),
            "examples": [list(e) for e in result.examples[:examples]],
        }

    return {
        "generated_utc": datetime.fromtimestamp(now_uts, UTC).isoformat(),
        "plays": {
            "total": len(plays),
            "completed": outcomes.get("completed", 0),
            "skipped": outcomes.get("skipped", 0),
            "unknown": outcomes.get("unknown", 0),
        },
        "history": {
            "distinct_tracks": len(history),
            "gap_days": gap_days,
            # The honest form is a stated upper bound, never a silently narrowed denominator.
            "novelty_is_upper_bound": gap_days > STALE_AFTER_DAYS,
        },
        "matcher_assumption": _matcher_assumption(),
        "novelty": _novelty_dict(novelty_rate(plays, history, examples)),
        "persistence": _persistence_dict(post_skip_persistence(plays, tags)),
        "repetition": repetition,
        "diagnostics": diag.as_dict(),
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(report: dict) -> str:
    n, p, d, h = (
        report["novelty"],
        report["persistence"],
        report["diagnostics"],
        report["history"],
    )
    plays = report["plays"]
    skip_arm, done_arm = p["after_skip"], p["after_completion"]

    lines = [
        "# Phase 0 — baseline measurement of Spotify's AI DJ",
        "",
        f"Generated {report['generated_utc']}. "
        f"{d['sessions']} captured sessions, {d['capture_hours']} hours, "
        f"labels {d['labels']}.",
        "",
        "## What must be true",
        "",
        "Read this before the numbers below, not after.",
        "",
        f"- **{plays['unknown']} of {plays['total']} plays could not be classified** "
        f"({_pct(plays['unknown'] / plays['total']) if plays['total'] else 'n/a'}). "
        "A transition spanning a capture gap, an ad, an idle, a backwards seek or the end of "
        "a session is recorded as `unknown` rather than guessed at, because calling an "
        "ambiguous transition a skip would inflate the skip rate and flatter this argument. "
        f"By reason: {d['unknown_reasons'] or 'none'}.",
    ]

    if h["novelty_is_upper_bound"]:
        lines.append(
            f"- **Novelty is an upper bound.** The scrobble history has a {h['gap_days']}-day "
            "gap, so a track first heard inside it is absent and reads as never-heard. The "
            "error makes the DJ look *better* at exploration than it is. Any track in the "
            "novel-examples list below that is actually familiar fell inside the gap."
        )
    else:
        lines.append(
            f"- The scrobble history is current ({h['gap_days']} days behind), so novelty is "
            "not inflated by missing history."
        )

    lines += [
        f"- **Tag coverage limits the tag half of persistence.** Only "
        f"{skip_arm['tagged_transitions']} of {skip_arm['transitions']} post-skip transitions "
        f"had Last.fm tags on both sides, and {done_arm['tagged_transitions']} of "
        f"{done_arm['transitions']} post-completion. The artist figures need no tags and are "
        "the robust ones.",
        f"- **Matcher assumption.** {report['matcher_assumption']}",
        f"- **Poll interval: {d['interval_verdict']}**",
        "",
        "## Novelty — the exploration deficit",
        "",
        f"- **{_pct(n['play_rate'])} per play** — {n['novel_plays']} of {n['plays']} plays were "
        "tracks never previously scrobbled.",
        f"- **{_pct(n['track_rate'])} per track** — {n['novel_tracks']} of "
        f"{n['distinct_tracks']} distinct tracks. This is the fairer figure: replaying one "
        "novel track is not repeated exploration.",
        "",
        "Novel examples, to be read by eye — anything recognisable here is a matcher miss or "
        "fell in the history gap:",
        "",
    ]
    lines += [f"  - {a} — {t}" for a, t in n["novel_examples"][:10]] or ["  - (none)"]

    lines += [
        "",
        "## Post-skip persistence — is it listening?",
        "",
        "The absolute rate means nothing; the contrast does.",
        "",
        "| | transitions | same artist | mean tag overlap |",
        "|---|---|---|---|",
        f"| after a **skip** | {skip_arm['transitions']} | {_pct(skip_arm['artist_rate'])} | "
        f"{skip_arm['mean_tag_jaccard']} |",
        f"| after a **completion** | {done_arm['transitions']} | "
        f"{_pct(done_arm['artist_rate'])} | {done_arm['mean_tag_jaccard']} |",
        "",
        f"**Artist delta: {p['artist_delta']:+.4f}** (completion minus skip). A positive delta "
        "means the DJ backs off the artist after a skip. A delta near zero means a skip — the "
        "strongest signal a listener can send — changes nothing observable.",
        f"Tag delta: {p['tag_delta']:+.4f}. "
        f"{p['excluded_unknown']} transitions excluded as ambiguous.",
        "",
        "## Repetition — replaying what you already rejected",
        "",
        "| window | replays of skipped | within session | across sessions | rate |",
        "|---|---|---|---|---|",
    ]
    for window, r in report["repetition"].items():
        lines.append(
            f"| {window}d | {r['replays_of_skipped']} | {r['within_session']} | "
            f"{r['cross_session']} | {_pct(r['rate'])} |"
        )
    lines += [
        "",
        "The across-sessions column is what beat 1's hook rests on: a track skipped on an "
        "earlier day, played again.",
        "",
        "## Capture health",
        "",
        f"- {d['polls']} polls, {d['idle']} idle, {d['gaps']} gaps "
        f"({d['rate_limited']} rate-limited)",
        f"- declared interval {d['declared_interval_ms']} ms; shortest observed gap between "
        f"track changes {d['min_track_gap_ms']} ms, 5th percentile {d['p05_track_gap_ms']} ms",
        f"- verdict: {d['interval_verdict']}",
        "",
    ]
    return "\n".join(lines)


def write_report(
    report: dict, out_dir: Path = REPORTS_DIR, stamp: str | None = None
) -> list[Path]:
    stamp = stamp or report["generated_utc"][:10]
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"phase0-{stamp}.json"
    md_path = out_dir / f"phase0-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return [json_path, md_path]


def _run(args: argparse.Namespace) -> int:
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.lastfm import LastfmClient
    from mldj.measure.novelty import build_history
    from mldj.measure.persistence import build_tag_index
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.skips import load_plays, session_files
    from mldj.transport import UrllibTransport

    paths = session_files(label=args.label)
    if not paths:
        raise SystemExit(
            "no captured sessions in data/sessions/ - run `mldj capture --label dj` first"
        )
    plays = load_plays(paths)
    diag = diagnostics(paths)

    if args.diagnostics_only:
        print(json.dumps(diag.as_dict(), indent=2))
        return 0

    scrobbles = read_scrobbles(SCROBBLES_PATH)
    if not scrobbles:
        raise SystemExit("no history in data/scrobbles.jsonl - run `mldj ingest` first")
    history = build_history(scrobbles)

    clock = SystemClock()
    tags = TagIndex({})
    if not args.no_tags:
        env = load_env()
        client = LastfmClient(UrllibTransport(), clock, require(env, "LASTFM_API_KEY"))
        print(f"fetching tags for the tracks in {len(paths)} sessions...")
        tags = build_tag_index(client, plays)

    report = build_report(
        plays=plays,
        history=history,
        tags=tags,
        diag=diag,
        now_uts=clock.now_ms() // 1000,
        history_newest_uts=max(s.uts for s in scrobbles),
    )
    for path in write_report(report):
        print(f"wrote {path}")
    print()
    print(f"poll interval verdict: {diag.interval_verdict}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("report", help="compute the Phase 0 numbers into reports/")
    parser.add_argument("--label", default=None, help="only sessions with this label, e.g. dj")
    parser.add_argument(
        "--diagnostics-only", action="store_true", help="capture health and the interval verdict"
    )
    parser.add_argument(
        "--no-tags", action="store_true", help="skip Last.fm tag pulls; artist figures only"
    )
    parser.set_defaults(handler=_run)

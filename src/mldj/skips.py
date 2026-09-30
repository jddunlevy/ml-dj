"""Turn a raw poll log into Play records with completed / skipped / unknown outcomes.

The spec's rule is "the track changed, and the outgoing track's interpolated progress
fell well short of its duration". GRACE_MS is "well short": a poll can land up to one
interval before the true end, so a track within GRACE_MS of its duration counts as
finished.

The important half of this module is what it refuses to decide. A transition is `unknown`,
never `skipped`, when the record is ambiguous:

  - a capture gap (429 or HTTP error) fell inside the run
  - an ad or podcast interrupted
  - playback went idle rather than advancing to another track
  - the last poll before the change is more than two intervals stale
  - progress moved backwards, meaning a seek or a restart
  - the session ended mid-track, i.e. Ctrl-C

Counting any of those as a skip would inflate the skip rate, and an inflated skip rate
flatters the pitch's own argument. A forward seek is the one error left uncaught: it
makes a track look more completed than it was, which undercounts skips. That is the
conservative direction, so it is accepted rather than guessed at.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from mldj.events import SESSIONS_DIR, read_events
from mldj.nowplaying import NowPlaying, interpolate_progress

GRACE_MS = 3000

# Crossfade makes the end of a track unobservable. Spotify starts the next one before the
# current finishes, so capture sees the change early and a natural completion looks short by
# the crossfade length. Measured on dj-20260930T142116Z, the shortfalls of everything the
# absolute grace alone called `skipped` split into two populations 173 seconds apart - 6-29s
# on one side, 202-298s on the other. The left cluster is the crossfade, the right is the
# next button, and nothing at all sits between them.
#
# This is a fractional floor rather than a bigger GRACE_MS because the two rules fail on
# opposite ends of the duration range: an absolute grace wide enough for a crossfade swallows
# most of a 40-second interlude, and a fraction alone leaves that same interlude a "skip" six
# seconds from the end. Both apply; either one is enough to call a track completed.
#
# It moves the headline skip rate DOWN, which flatters the DJ rather than this project's
# argument - the safe direction for a threshold that had to be chosen rather than derived.
# A listener with crossfade off should tighten it; `mldj report --completion-fraction` does.
COMPLETION_FRACTION = 0.85
SEEK_TOLERANCE_MS = 2000
ASSUMED_INTERVAL_MS = 1000  # only used if a log has no session_start


@dataclass(frozen=True)
class Play:
    track_id: str
    title: str
    artist: str
    duration_ms: int
    started_at_ms: int
    ended_at_ms: int
    listened_ms: int
    outcome: str  # 'completed' | 'skipped' | 'unknown'
    session: str
    label: str
    reason: str  # why unknown; empty for completed and skipped

    @property
    def listened_fraction(self) -> float:
        return self.listened_ms / self.duration_ms if self.duration_ms else 0.0


def _listened_at(poll: dict, now_ms: int) -> int:
    np = NowPlaying(
        kind=str(poll.get("kind") or "track"),
        id=str(poll.get("id") or ""),
        title=str(poll.get("title") or ""),
        artist=str(poll.get("artist") or ""),
        duration_ms=int(poll.get("duration_ms") or 0),
        progress_ms=int(poll.get("progress_ms") or 0),
        is_playing=bool(poll.get("is_playing")),
        fetched_at=int(poll.get("fetched_at") or poll["t"]),
    )
    return interpolate_progress(np, now_ms)


def _moved_backwards(run: list[dict]) -> bool:
    for prev, nxt in zip(run, run[1:], strict=False):
        previous = int(prev.get("progress_ms") or 0)
        following = int(nxt.get("progress_ms") or 0)
        if following + SEEK_TOLERANCE_MS < previous:
            return True
    return False


def _close_run(
    run: list[dict],
    ended_at_ms: int,
    interval_ms: int,
    session: str,
    label: str,
    grace_ms: int,
    completion_fraction: float,
    taint: str,
) -> Play | None:
    last = run[-1]
    duration_ms = int(last.get("duration_ms") or 0)
    if duration_ms <= 0:
        return None  # nothing measurable; ads and malformed runs land here

    listened_ms = _listened_at(last, ended_at_ms)

    reason = taint
    if not reason and ended_at_ms - int(last["t"]) > 2 * interval_ms:
        reason = "last poll too stale to place the change"
    if not reason and _moved_backwards(run):
        reason = "progress moved backwards (seek or restart)"

    # Order matters: an ambiguous run stays unknown however complete it looks. The
    # crossfade allowance decides between completed and skipped, never between unknown and
    # anything else, so it cannot promote a doubtful record into a positive claim.
    if reason:
        outcome = "unknown"
    elif listened_ms >= duration_ms - grace_ms:
        outcome = "completed"
    elif listened_ms >= duration_ms * completion_fraction:
        outcome = "completed"
    else:
        outcome = "skipped"

    return Play(
        track_id=str(last.get("id") or ""),
        title=str(last.get("title") or ""),
        artist=str(last.get("artist") or ""),
        duration_ms=duration_ms,
        started_at_ms=int(run[0]["t"]),
        ended_at_ms=ended_at_ms,
        listened_ms=listened_ms,
        outcome=outcome,
        session=session,
        label=label,
        reason=reason,
    )


def derive_plays(
    events: Iterable[dict],
    grace_ms: int = GRACE_MS,
    completion_fraction: float = COMPLETION_FRACTION,
) -> list[Play]:
    """Walk a session's events in order and emit one Play per contiguous track run."""
    plays: list[Play] = []
    interval_ms = ASSUMED_INTERVAL_MS
    session = ""
    label = ""
    run: list[dict] = []
    taint = ""

    def close(at_ms: int, successor_taint: str) -> None:
        nonlocal run, taint
        if run:
            play = _close_run(
                run, at_ms, interval_ms, session, label, grace_ms, completion_fraction,
                taint or successor_taint,
            )
            if play is not None:
                plays.append(play)
        run = []
        taint = ""

    for event in events:
        kind = event.get("type")
        if kind == "session_start":
            interval_ms = int(event.get("interval_ms") or interval_ms)
            session = str(event.get("session") or "")
            label = str(event.get("label") or "")
        elif kind == "gap":
            taint = "capture gap during playback"
        elif kind == "idle":
            close(int(event["t"]), "playback stopped")
        elif kind == "session_end":
            close(int(event["t"]), "session ended mid-track")
        elif kind == "poll":
            now = int(event["t"])
            if event.get("kind") != "track":
                close(now, "non-track playback intervened")
                continue
            if run and run[-1].get("id") != event.get("id"):
                close(now, "")
            run.append(event)

    # A log that stops without session_end - a killed process - still closes its last run.
    if run:
        close(int(run[-1]["t"]), "log ended without session_end")
    return plays


def session_files(root: Path = SESSIONS_DIR, label: str | None = None) -> list[Path]:
    pattern = f"{label}-*.jsonl" if label else "*.jsonl"
    return sorted(root.glob(pattern))


def load_plays(paths: Iterable[Path], grace_ms: int = GRACE_MS) -> list[Play]:
    """Every play across every given session, in chronological order."""

    def all_plays() -> Iterator[Play]:
        for path in paths:
            yield from derive_plays(read_events(path), grace_ms)

    return sorted(all_plays(), key=lambda p: p.started_at_ms)

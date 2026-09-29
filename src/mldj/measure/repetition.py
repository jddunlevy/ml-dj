"""Repetition: how often the DJ replays a track it has already seen you skip.

**This has to work across sessions.** Beat 1's hook is "you put the DJ on to work, and it
plays something you skipped yesterday" - a within-session-only measure cannot support that
claim at all. So the count is split: `within_session` is the more immediate failure,
`cross_session` is the one the hook rests on, and both are reported.

Two ordering rules that are easy to get wrong:

  - the skip map is consulted *before* the current play is written into it, or every
    skipped track counts as its own replay
  - plays are sorted by time, not taken in input order, because `load_plays` merges several
    session files

An `unknown` outcome never seeds a skip - an ambiguous record may not have been a skip, so
it cannot found a repetition claim - but it still occupies the denominator, because it was
a track the DJ chose to play.

`window_days` is a parameter rather than a constant because the right window is an empirical
question. The report quotes 1, 7 and 14 days instead of picking one.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from mldj.match import track_key
from mldj.skips import Play

MS_PER_DAY = 86_400_000
DEFAULT_WINDOW_DAYS = 14


@dataclass(frozen=True)
class RepetitionResult:
    plays: int
    replays_of_skipped: int
    within_session: int
    cross_session: int
    rate: float
    window_days: int
    examples: list[tuple[str, str, int]]  # artist, title, prior in-window skips


def repetition_rate(
    plays: Iterable[Play], window_days: int = DEFAULT_WINDOW_DAYS
) -> RepetitionResult:
    """Share of plays whose track had already been skipped within the window."""
    window_ms = window_days * MS_PER_DAY
    ordered = sorted((p for p in plays if p.duration_ms > 0), key=lambda p: p.started_at_ms)

    # track key -> the (timestamp, session) of each skip seen so far
    skips: dict[tuple[str, str], list[tuple[int, str]]] = {}
    replays = within = cross = 0
    examples: list[tuple[str, str, int]] = []

    for play in ordered:
        key = track_key(play.artist, play.title)

        # Consulted before recording, so a skip is never a replay of itself.
        prior = [
            (ts, session)
            for ts, session in skips.get(key, [])
            if play.started_at_ms - ts <= window_ms
        ]
        if prior:
            replays += 1
            # Classified by the stronger evidence: an immediate, same-session replay is the
            # more damning finding, so it wins when both kinds of prior skip exist.
            if any(session == play.session for _, session in prior):
                within += 1
            else:
                cross += 1
            examples.append((play.artist, play.title, len(prior)))

        if play.outcome == "skipped":
            skips.setdefault(key, []).append((play.started_at_ms, play.session))

    return RepetitionResult(
        plays=len(ordered),
        replays_of_skipped=replays,
        within_session=within,
        cross_session=cross,
        rate=replays / len(ordered) if ordered else 0.0,
        window_days=window_days,
        examples=examples,
    )

"""The captured-session event log. One JSON object per line, append-only.

Raw polls are logged verbatim rather than derived plays. Skip thresholds and the poll
interval will change as Phase 0 learns what the data looks like; re-deriving plays from
raw polls costs seconds, while re-capturing costs days of real listening. At a 1000 ms
interval a poll line is about 200 bytes, so an hour of listening is under 1 MB.

Every line is flushed. Capture ends with Ctrl-C, and a buffered tail would be lost
listening that cannot be recovered.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from mldj.nowplaying import NowPlaying

SESSIONS_DIR = Path("data/sessions")  # gitignored; captured listening never enters git


def session_id(now_ms: int) -> str:
    """A sortable UTC stamp, used in the filename and stamped on every session."""
    return datetime.fromtimestamp(now_ms / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")


def session_path(label: str, sid: str, root: Path = SESSIONS_DIR) -> Path:
    return root / f"{label}-{sid}.jsonl"


class EventWriter:
    """Append-only JSONL writer. Use as a context manager."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: TextIO | None = None

    def __enter__(self) -> "EventWriter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, event: dict[str, Any]) -> None:
        if self._fh is None:
            raise RuntimeError("EventWriter used outside its context manager")
        self._fh.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._fh.flush()


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                yield json.loads(line)


def session_start_event(now_ms: int, label: str, interval_ms: int, sid: str) -> dict[str, Any]:
    # interval_ms is recorded so the analysis can tell a real gap from normal poll spacing.
    return {
        "t": now_ms,
        "type": "session_start",
        "label": label,
        "interval_ms": interval_ms,
        "session": sid,
    }


def session_end_event(now_ms: int, reason: str) -> dict[str, Any]:
    return {"t": now_ms, "type": "session_end", "reason": reason}


def gap_event(now_ms: int, reason: str, retry_ms: int) -> dict[str, Any]:
    """A hole in the record. Transitions spanning one of these are never counted as skips."""
    return {"t": now_ms, "type": "gap", "reason": reason, "retry_ms": retry_ms}


def poll_event(np: NowPlaying | None, now_ms: int) -> dict[str, Any]:
    if np is None:
        return {"t": now_ms, "type": "idle"}
    return {
        "t": now_ms,
        "type": "poll",
        "kind": np.kind,
        "id": np.id,
        "title": np.title,
        "artist": np.artist,
        "duration_ms": np.duration_ms,
        "progress_ms": np.progress_ms,
        "is_playing": np.is_playing,
        "fetched_at": np.fetched_at,
    }

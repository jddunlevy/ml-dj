# Phase 0 — Baseline Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python tooling that captures real Spotify AI DJ sessions and measures novelty rate, post-skip persistence, and repetition against a 39,000-scrobble Last.fm history — the first-party evidence beat 3 of the pitch rests on.

**Architecture:** A stdlib-only Python package under `src/mldj/`. Capture polls Spotify's currently-playing endpoint and appends **raw poll events** to gitignored JSONL; every analysis is re-derived from those raw logs offline. Both boundaries that make tests slow or flaky — the network and the clock — are injected protocols with test doubles, so no test touches the wire and no test sleeps.

**Tech Stack:** Python >=3.12, stdlib only (`urllib`, `http.server`, `hashlib`, `secrets`, `json`, `argparse`, `unicodedata`, `re`). pytest 8 + ruff for dev. No third-party runtime dependencies.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from `CLAUDE.md` and `docs/superpowers/specs/2026-09-28-ml-dj-design.md`.

- **THIS REPO IS PUBLIC.** Before every commit, assume a stranger reads it. Never commit the Spotify client ID, the Last.fm API key, `.env.local`, or tokens. Never commit the scrobble corpus or captured session logs — they live in `data/`, which is gitignored. If you are about to `git add` something under `data/`, stop.
- **Dependencies:** stdlib only where practical. Phase 0 needs no third-party runtime deps. `numpy`/`scipy` arrive in Phase 1, not here. Justify anything else.
- **Tests:** `pytest`, TDD. Every network boundary takes an injected transport so tests never hit the wire. Same for the clock — no test sleeps.
- **Fixtures:** JSON/JSONL under `fixtures/`, anonymized, committed. These are the only listening data in git.
- **Commits:** conventional commits (`feat:`, `fix:`, `docs:`, `test:`), frequent and small.
- **Line width:** 100. Ruff lint selects `E`, `F`, `I`, `UP`, `B`.
- **All timestamps are integer epoch milliseconds, UTC.** This matches the Spotify API's units and `cd-player`'s lineage. `Clock.now_ms()` is the only source of current time; never call `time.time()` outside `clock.py`.
- **Spotify redirect URI must be exactly** `http://127.0.0.1:8888/callback`.
- **Spotify scope for Phase 0 is exactly** `user-read-currently-playing`. Phase 0 never writes playback state, so do not request more.
- **Spotify audio features are gone** for apps created after 2024-11-27. Do not call Audio Features, Audio Analysis, Recommendations, or Related Artists. This is a design input, not a workaround.
- **Last.fm does not record skips.** A skip is an absence in history and exists only in live capture.

## Why this order

**The capture tool is the long pole.** Collecting DJ sessions takes days of real listening that cannot be compressed by writing code faster. Tasks 1-5 exist to get `mldj capture --label dj` running and nothing else; everything from Task 6 on is built while sessions accumulate. Do not reorder Tasks 1-5 behind analysis work.

Two decisions are settled here so later tasks do not relitigate them:

1. **Capture logs raw polls, not derived events.** Skip thresholds and the poll interval will change as Phase 0 learns. Re-deriving plays from raw polls costs seconds; re-capturing costs days. At a 1000 ms interval a poll line is roughly 200 bytes, so an hour of listening is under 1 MB.
2. **Sessions are labeled by hand, not inferred.** `--label dj` is an explicit flag. This resolves spec open question 3 ("whether DJ sessions can be reliably distinguished from ordinary listening") by not requiring the inference at all — the operator knows what they put on.

---

## File Structure

```
src/mldj/
  __init__.py          package marker, version string
  __main__.py          `python -m mldj` entry
  cli.py               argparse dispatch; each module registers its own subcommand
  env.py               .env.local reader (no python-dotenv)
  clock.py             Clock protocol + SystemClock - the only place time is read
  transport.py         Transport protocol + UrllibTransport + Retry-After parsing
  nowplaying.py        NowPlaying, parse_now_playing, interpolate_progress
  auth.py              PKCE, loopback callback, token store and refresh
  events.py            event records + JSONL append/read
  capture.py           the poll loop; `mldj capture`
  skips.py             raw polls -> Play records with completed/skipped/unknown
  lastfm.py            Last.fm API client (getRecentTracks, getTopTags)
  scrobbles.py         paged, resumable scrobble ingest; `mldj ingest`
  match.py             Spotify<->Last.fm track key normalization and matching
  measure/
    __init__.py
    novelty.py         share of DJ-played tracks never previously scrobbled
    persistence.py     post-skip artist/tag persistence vs a post-completion baseline
    repetition.py      replays of already-skipped tracks, within and across sessions
    report.py          `mldj report` - writes reports/phase0-<date>.{md,json}

tests/
  fakes.py             FakeClock, FakeTransport - shared test doubles
  test_env.py  test_cli.py  test_nowplaying.py  test_transport.py
  test_auth.py  test_events.py  test_capture.py  test_skips.py
  test_match.py  test_lastfm.py  test_scrobbles.py
  measure/test_novelty.py  measure/test_persistence.py
  measure/test_repetition.py  measure/test_report.py

fixtures/
  nowplaying-track.json      nowplaying-ad.json      nowplaying-episode.json
  session-dj-sample.jsonl    match-gold.json
  lastfm-recenttracks-page.json   lastfm-toptags.json
  scrobbles-sample.jsonl
```

`tests/` has no `__init__.py`, so pytest's default import mode puts each test file's directory on `sys.path` and `from fakes import FakeClock` works. `pythonpath = ["src"]` in `pyproject.toml` already makes `import mldj` work without installing.

---

### Task 1: Package skeleton, env loading, CLI entry

Nothing runs until `python -m mldj` resolves and the two credentials can be read. This task is that, and only that.

**Files:**
- Create: `src/mldj/__init__.py`
- Create: `src/mldj/__main__.py`
- Create: `src/mldj/cli.py`
- Create: `src/mldj/env.py`
- Test: `tests/test_env.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `mldj.env.parse_env(text: str) -> dict[str, str]`
  - `mldj.env.load_env(path: Path = Path(".env.local")) -> dict[str, str]`
  - `mldj.env.require(env: dict[str, str], key: str) -> str` — raises `SystemExit` on missing or empty
  - `mldj.cli.build_parser() -> argparse.ArgumentParser` — later tasks add subparsers here
  - `mldj.cli.main(argv: Sequence[str] | None = None) -> int`

- [x] **Step 1: Create the virtual environment and install dev dependencies**

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

Expected: `Successfully installed mldj-0.1.0 ... pytest-8.x ... ruff-0.x`. Every later `pytest` and `ruff` command in this plan means `.venv/Scripts/python.exe -m pytest` / `-m ruff` unless the venv is already activated.

- [x] **Step 2: Write the failing tests**

Create `tests/test_env.py`:

```python
import pytest

from mldj.env import load_env, parse_env, require


def test_parse_env_reads_simple_pairs():
    assert parse_env("SPOTIFY_CLIENT_ID=abc123\n") == {"SPOTIFY_CLIENT_ID": "abc123"}


def test_parse_env_ignores_comments_and_blank_lines():
    text = "# this repo is public\n\nLASTFM_API_KEY=key\n"
    assert parse_env(text) == {"LASTFM_API_KEY": "key"}


def test_parse_env_strips_matched_quotes():
    assert parse_env('LASTFM_USER="jaxon"\n') == {"LASTFM_USER": "jaxon"}
    assert parse_env("LASTFM_USER='jaxon'\n") == {"LASTFM_USER": "jaxon"}


def test_parse_env_keeps_equals_signs_inside_the_value():
    assert parse_env("TOKEN=ab=cd\n") == {"TOKEN": "ab=cd"}


def test_parse_env_keeps_an_empty_value():
    assert parse_env("LASTFM_USER=\n") == {"LASTFM_USER": ""}


def test_load_env_returns_empty_dict_when_the_file_is_absent(tmp_path):
    assert load_env(tmp_path / "nope.local") == {}


def test_load_env_reads_a_real_file(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text("SPOTIFY_CLIENT_ID=xyz\n", encoding="utf-8")
    assert load_env(path) == {"SPOTIFY_CLIENT_ID": "xyz"}


def test_require_returns_a_present_value():
    assert require({"LASTFM_USER": "jaxon"}, "LASTFM_USER") == "jaxon"


def test_require_rejects_a_missing_key():
    with pytest.raises(SystemExit):
        require({}, "LASTFM_API_KEY")


def test_require_rejects_an_empty_value():
    # .env.local.example ships LASTFM_USER= with no value, so empty must fail too.
    with pytest.raises(SystemExit):
        require({"LASTFM_USER": ""}, "LASTFM_USER")
```

Create `tests/test_cli.py`:

```python
from mldj.cli import main


def test_main_with_no_command_exits_two_and_prints_usage(capsys):
    assert main([]) == 2
    assert "usage: mldj" in capsys.readouterr().out
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_env.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj'`

- [x] **Step 4: Write the package skeleton**

Create `src/mldj/__init__.py`:

```python
"""ml-dj - teardown and redesign of Spotify's AI DJ. Phase 0: baseline measurement."""

__version__ = "0.1.0"
```

Create `src/mldj/env.py`:

```python
"""Read .env.local without a third-party dependency.

This repo is public. .env.local is gitignored and holds the only two credentials the
project needs: a Spotify client ID and a Last.fm API key.
"""

from pathlib import Path

DEFAULT_ENV_PATH = Path(".env.local")


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and # comments and stripping matched quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Load .env.local if it exists. A missing file is not an error; require() reports it."""
    if not path.exists():
        return {}
    return parse_env(path.read_text(encoding="utf-8"))


def require(env: dict[str, str], key: str) -> str:
    """Fetch a credential, failing with an actionable message when it is missing or blank."""
    value = env.get(key, "")
    if not value:
        raise SystemExit(f"missing {key} - copy .env.local.example to .env.local and fill it in")
    return value
```

Create `src/mldj/cli.py`:

```python
"""mldj command line.

build_parser() owns the top-level parser; each feature module registers its own
subcommand so no single file has to know about all of them.
"""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mldj", description="ml-dj Phase 0 baseline tools")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if not args.command or handler is None:
        parser.print_usage()
        return 2
    return int(handler(args))
```

Create `src/mldj/__main__.py`:

```python
"""Entry point for `python -m mldj`, which is how the README invokes capture."""

import sys

from mldj.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_env.py tests/test_cli.py -v`
Expected: PASS — 11 passed

Run: `.venv/Scripts/python.exe -m mldj`
Expected: `usage: mldj [-h] <command> ...` and exit code 2

- [x] **Step 6: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/__init__.py src/mldj/__main__.py src/mldj/cli.py src/mldj/env.py
git add tests/test_env.py tests/test_cli.py
git commit -m "feat: package skeleton, .env.local reader, and CLI entry point"
```

---

### Task 2: NowPlaying parsing and progress interpolation

The skip detector's core primitive. Pure functions, no network, no clock — so this is all TDD and all fast. Ported from `cd-player`'s `spotify.ts` and `player-state.ts`; `artUrl` is deliberately dropped because Phase 0 renders nothing.

**Files:**
- Create: `src/mldj/nowplaying.py`
- Create: `fixtures/nowplaying-track.json`, `fixtures/nowplaying-ad.json`, `fixtures/nowplaying-episode.json`
- Test: `tests/test_nowplaying.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `mldj.nowplaying.NowPlaying` — frozen dataclass with fields, in order: `kind: str`, `id: str`, `title: str`, `artist: str`, `duration_ms: int`, `progress_ms: int`, `is_playing: bool`, `fetched_at: int`
  - `mldj.nowplaying.parse_now_playing(payload: object, fetched_at: int) -> NowPlaying | None`
  - `mldj.nowplaying.interpolate_progress(np: NowPlaying, now: int) -> int`
  - `mldj.nowplaying.ENDPOINT: str`

- [ ] **Step 1: Write the anonymized fixtures**

Create `fixtures/nowplaying-track.json` — shaped exactly like the real payload, with invented track data because this repo is public:

```json
{
  "timestamp": 1759190400000,
  "progress_ms": 45000,
  "is_playing": true,
  "currently_playing_type": "track",
  "item": {
    "id": "2aBcDeFgHiJkLmNoPqRsTu",
    "name": "Ceiling Fan",
    "duration_ms": 213000,
    "artists": [{ "name": "Paper Lanterns" }, { "name": "Odell" }],
    "album": { "name": "Quiet Rooms" }
  }
}
```

Create `fixtures/nowplaying-ad.json`:

```json
{
  "timestamp": 1759190500000,
  "progress_ms": 8000,
  "is_playing": true,
  "currently_playing_type": "ad",
  "item": null
}
```

Create `fixtures/nowplaying-episode.json`:

```json
{
  "timestamp": 1759190600000,
  "progress_ms": 120000,
  "is_playing": true,
  "currently_playing_type": "episode",
  "item": {
    "id": "3vWxYzAbCdEfGhIjKlMnOp",
    "name": "Episode 14 - Folksonomies",
    "duration_ms": 1800000,
    "show": { "name": "A Podcast About Tags" }
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_nowplaying.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nowplaying.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.nowplaying'`

- [ ] **Step 4: Write the implementation**

Create `src/mldj/nowplaying.py`:

```python
"""Parse Spotify currently-playing payloads and interpolate progress between polls.

Ported from cd-player's spotify.ts (parseNowPlaying) and player-state.ts
(interpolateProgress). artUrl is dropped: Phase 0 renders nothing.

interpolate_progress is the skip detector's core primitive. A skip is "the track
changed and the outgoing track's interpolated progress fell well short of its
duration", so the accuracy of that number is the accuracy of the whole measurement.
"""

from dataclasses import dataclass

ENDPOINT = "https://api.spotify.com/v1/me/player/currently-playing?additional_types=episode"


@dataclass(frozen=True)
class NowPlaying:
    kind: str  # 'track' | 'episode' | 'ad'
    id: str
    title: str
    artist: str
    duration_ms: int
    progress_ms: int
    is_playing: bool
    fetched_at: int  # epoch ms when this snapshot was taken


def parse_now_playing(payload: object, fetched_at: int) -> NowPlaying | None:
    """Return a NowPlaying, or None when the payload carries nothing playable."""
    if not isinstance(payload, dict):
        return None
    kind = payload.get("currently_playing_type")
    progress_ms = int(payload.get("progress_ms") or 0)
    is_playing = bool(payload.get("is_playing"))

    if kind == "ad":
        # Ads carry no item. They are logged so the analysis can exclude the transition
        # rather than mistake it for a skip.
        return NowPlaying("ad", "ad", "", "", 0, progress_ms, is_playing, fetched_at)

    item = payload.get("item")
    if not isinstance(item, dict) or kind not in ("track", "episode"):
        return None

    if kind == "track":
        artists = item.get("artists") or []
        artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict))
    else:
        artist = (item.get("show") or {}).get("name", "")

    return NowPlaying(
        kind=kind,
        id=item.get("id") or "",
        title=item.get("name") or "",
        artist=artist,
        duration_ms=int(item.get("duration_ms") or 0),
        progress_ms=progress_ms,
        is_playing=is_playing,
        fetched_at=fetched_at,
    )


def interpolate_progress(np: NowPlaying, now: int) -> int:
    """Where the track would be at `now`, given its last snapshot. Clamped to duration."""
    if not np.is_playing:
        return np.progress_ms
    return min(np.duration_ms, np.progress_ms + (now - np.fetched_at))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nowplaying.py -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/nowplaying.py tests/test_nowplaying.py
git add fixtures/nowplaying-track.json fixtures/nowplaying-ad.json fixtures/nowplaying-episode.json
git commit -m "feat: parse currently-playing payloads and interpolate progress"
```

---
### Task 3: The injected boundaries — transport and clock

Every network call and every read of the current time goes through these, so tests never hit the wire and never sleep. `UrllibTransport` must not raise for a 4xx/5xx: `urllib` throws `HTTPError` on those, and the capture loop needs to inspect a 429's `Retry-After` rather than catch an exception.

**Files:**
- Create: `src/mldj/transport.py`
- Create: `src/mldj/clock.py`
- Create: `tests/fakes.py`
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `mldj.transport.Response` — frozen dataclass: `status: int`, `body: bytes`, `headers: Mapping[str, str]`; methods `json() -> object` and `header(name: str) -> str | None` (case-insensitive)
  - `mldj.transport.Transport` — Protocol with `get(url, headers=None) -> Response` and `post(url, data, headers=None) -> Response`
  - `mldj.transport.UrllibTransport(timeout_s: float = 10.0)`
  - `mldj.transport.retry_after_ms(response: Response, default_ms: int = 10_000) -> int`
  - `mldj.transport.DEFAULT_RETRY_MS: int = 10_000`
  - `mldj.clock.Clock` — Protocol with `now_ms() -> int` and `sleep_ms(ms: int) -> None`
  - `mldj.clock.SystemClock`
  - `tests.fakes.FakeClock(start_ms: int = 0)` — `now_ms()`, `sleep_ms()`, `advance_ms()`, and a `sleeps: list[int]` record
  - `tests.fakes.FakeTransport(responses: list[Response] | None = None)` — `get`/`post`, a `requests` record, raises `AssertionError` when its script runs out

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transport.py`:

```python
import pytest

from mldj.transport import DEFAULT_RETRY_MS, Response, retry_after_ms

from fakes import FakeClock, FakeTransport


def test_response_json_decodes_the_body():
    assert Response(200, b'{"a": 1}').json() == {"a": 1}


def test_response_json_is_none_for_an_empty_body():
    # A 204 from currently-playing has no body at all.
    assert Response(204, b"").json() is None


def test_response_header_lookup_ignores_case():
    r = Response(429, b"", {"Retry-After": "3"})
    assert r.header("retry-after") == "3"
    assert r.header("RETRY-AFTER") == "3"
    assert r.header("missing") is None


def test_retry_after_converts_whole_seconds_to_milliseconds():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "3"})) == 3000


def test_retry_after_falls_back_when_the_header_is_absent():
    assert retry_after_ms(Response(429, b"", {})) == DEFAULT_RETRY_MS


def test_retry_after_falls_back_when_the_header_is_garbage():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "soon"})) == DEFAULT_RETRY_MS


def test_retry_after_never_returns_a_negative_wait():
    assert retry_after_ms(Response(429, b"", {"Retry-After": "-5"})) == 0


def test_fake_clock_advances_only_when_told_to():
    clock = FakeClock(start_ms=1_000)
    assert clock.now_ms() == 1_000
    clock.sleep_ms(250)
    assert clock.now_ms() == 1_250
    assert clock.sleeps == [250]


def test_fake_transport_replays_its_script_and_records_requests():
    transport = FakeTransport([Response(200, b"{}"), Response(204, b"")])
    assert transport.get("https://example.invalid/a").status == 200
    assert transport.get("https://example.invalid/b").status == 204
    assert [r[1] for r in transport.requests] == [
        "https://example.invalid/a",
        "https://example.invalid/b",
    ]


def test_fake_transport_fails_loudly_when_the_script_runs_out():
    transport = FakeTransport([])
    with pytest.raises(AssertionError):
        transport.get("https://example.invalid/a")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transport.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.transport'`

- [ ] **Step 3: Write the implementation**

Create `src/mldj/clock.py`:

```python
"""The time boundary. Injected everywhere so tests never sleep.

This is the only module allowed to call time.time() or time.sleep().
Every timestamp in the project is an integer epoch millisecond.
"""

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...

    def sleep_ms(self, ms: int) -> None: ...


class SystemClock:
    """The real clock. Tests use tests.fakes.FakeClock instead."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep_ms(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000)
```

Create `src/mldj/transport.py`:

```python
"""The HTTP boundary. Every network call goes through a Transport so tests never hit the wire.

UrllibTransport deliberately never raises for an HTTP status: urllib raises HTTPError on
4xx/5xx, but the capture loop needs to read a 429's Retry-After header, so statuses come
back as ordinary Responses. A transport-level failure (DNS, timeout, refused) surfaces as
status 0.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_RETRY_MS = 10_000


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> object:
        """Decode the body, or None when there is no body (e.g. a 204)."""
        return json.loads(self.body) if self.body else None

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup; HTTP header casing is not guaranteed."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response: ...

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


class UrllibTransport:
    """stdlib transport. No third-party HTTP client in Phase 0."""

    def __init__(self, timeout_s: float = 10.0) -> None:
        self._timeout_s = timeout_s

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        return self._send(request)

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        body = urllib.parse.urlencode(dict(data)).encode("utf-8")
        merged = {"Content-Type": "application/x-www-form-urlencoded", **dict(headers or {})}
        request = urllib.request.Request(url, data=body, headers=merged, method="POST")
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> Response:
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                return Response(response.status, response.read(), dict(response.headers))
        except urllib.error.HTTPError as err:
            # A 429 or 401 is information, not an exception; the caller decides what to do.
            return Response(err.code, err.read(), dict(err.headers))
        except urllib.error.URLError as err:
            return Response(0, str(err.reason).encode("utf-8"), {})


def retry_after_ms(response: Response, default_ms: int = DEFAULT_RETRY_MS) -> int:
    """Spotify sends Retry-After in whole seconds on a 429. Absent or malformed -> default."""
    raw = response.header("Retry-After")
    try:
        return max(0, int(float(raw))) * 1000  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default_ms
```

Create `tests/fakes.py`:

```python
"""Test doubles for the two injected boundaries. No test may use the real ones."""

from collections.abc import Mapping

from mldj.transport import Response


class FakeClock:
    """A clock that only moves when the code under test sleeps, or a test advances it."""

    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms
        self.sleeps: list[int] = []

    def now_ms(self) -> int:
        return self._now

    def sleep_ms(self, ms: int) -> None:
        self.sleeps.append(ms)
        self._now += max(0, ms)

    def advance_ms(self, ms: int) -> None:
        self._now += ms


class FakeTransport:
    """Replays a scripted list of Responses and records every request made."""

    def __init__(self, responses: list[Response] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[tuple[str, str, object]] = []

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        self.requests.append(("GET", url, headers))
        return self._next()

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        self.requests.append(("POST", url, data))
        return self._next()

    def _next(self) -> Response:
        if not self.responses:
            raise AssertionError("FakeTransport ran out of scripted responses")
        return self.responses.pop(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transport.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/clock.py src/mldj/transport.py tests/fakes.py tests/test_transport.py
git commit -m "feat: injected transport and clock boundaries with test doubles"
```

---

### Task 4: Spotify PKCE auth with a loopback callback

A Python port of `cd-player`'s `auth.ts`, with `localStorage` replaced by a gitignored JSON file and the browser redirect replaced by a one-shot loopback HTTP server. The pure pieces are TDD'd against RFC 7636's published test vector; the socket server gets a real localhost test on an ephemeral port, which is local I/O rather than the wire.

**Files:**
- Create: `src/mldj/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `mldj.transport.Transport`, `mldj.transport.Response`, `mldj.clock.Clock`
- Produces:
  - `mldj.auth.Tokens` — frozen dataclass: `access_token: str`, `refresh_token: str`, `expires_at: int`
  - `mldj.auth.random_verifier(length: int = 64) -> str`
  - `mldj.auth.code_challenge(verifier: str) -> str`
  - `mldj.auth.authorize_url(client_id: str, verifier: str) -> str`
  - `mldj.auth.parse_callback_code(path: str) -> str | None`
  - `mldj.auth.merge_token_response(prev: Tokens | None, payload: dict, now_ms: int) -> Tokens`
  - `mldj.auth.should_refresh(tokens: Tokens, now_ms: int) -> bool`
  - `mldj.auth.load_tokens(path: Path = TOKENS_PATH) -> Tokens | None`
  - `mldj.auth.save_tokens(tokens: Tokens, path: Path = TOKENS_PATH) -> None`
  - `mldj.auth.wait_for_code(port: int = 8888, max_requests: int = 5) -> str`
  - `mldj.auth.exchange_code(transport, clock, client_id, code, verifier) -> Tokens`
  - `mldj.auth.refresh_tokens(transport, clock, client_id, tokens) -> Tokens`
  - `mldj.auth.login(transport, clock, client_id, path=TOKENS_PATH) -> Tokens`
  - `mldj.auth.token_provider(transport, clock, client_id, path=TOKENS_PATH) -> Callable[[], str]`
  - `mldj.auth.REDIRECT_URI`, `mldj.auth.SCOPE`, `mldj.auth.TOKENS_PATH`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth.py`:

```python
import json
import threading
import urllib.request

import pytest

from mldj.auth import (
    REDIRECT_URI,
    SCOPE,
    Tokens,
    authorize_url,
    code_challenge,
    exchange_code,
    load_tokens,
    merge_token_response,
    parse_callback_code,
    random_verifier,
    refresh_tokens,
    save_tokens,
    should_refresh,
    token_provider,
    wait_for_code,
)
from mldj.transport import Response

from fakes import FakeClock, FakeTransport

# RFC 7636 appendix B publishes this verifier/challenge pair.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_code_challenge_matches_the_rfc_7636_test_vector():
    assert code_challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_random_verifier_is_the_right_length_and_alphabet():
    verifier = random_verifier()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert len(verifier) == 64
    assert set(verifier) <= allowed


def test_random_verifier_does_not_repeat():
    assert random_verifier() != random_verifier()


def test_authorize_url_requests_only_the_read_scope_and_the_exact_redirect():
    url = authorize_url("client-abc", RFC_VERIFIER)
    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert "code_challenge_method=S256" in url
    assert f"code_challenge={RFC_CHALLENGE}" in url
    assert "scope=user-read-currently-playing" in url
    assert SCOPE == "user-read-currently-playing"
    assert REDIRECT_URI == "http://127.0.0.1:8888/callback"
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback" in url


def test_parse_callback_code_extracts_the_code():
    assert parse_callback_code("/callback?code=abc123&state=x") == "abc123"


def test_parse_callback_code_returns_none_without_a_code():
    assert parse_callback_code("/favicon.ico") is None
    assert parse_callback_code("/callback?error=access_denied") is None


def test_merge_token_response_computes_an_absolute_expiry():
    tokens = merge_token_response(
        None, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}, now_ms=1_000
    )
    assert tokens == Tokens("a1", "r1", 1_000 + 3_600_000)


def test_merge_token_response_keeps_the_previous_refresh_token_when_none_is_returned():
    # Spotify's refresh response often omits refresh_token; losing it would force re-login.
    prev = Tokens("old", "keep-me", 0)
    tokens = merge_token_response(prev, {"access_token": "a2", "expires_in": 60}, now_ms=5_000)
    assert tokens.refresh_token == "keep-me"


def test_should_refresh_uses_a_sixty_second_margin():
    tokens = Tokens("a", "r", expires_at=100_000)
    assert should_refresh(tokens, now_ms=39_000) is False
    assert should_refresh(tokens, now_ms=40_000) is True


def test_tokens_round_trip_through_disk(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("a1", "r1", 123), path)
    assert load_tokens(path) == Tokens("a1", "r1", 123)


def test_load_tokens_returns_none_when_no_file_exists(tmp_path):
    assert load_tokens(tmp_path / "absent.json") is None


def test_exchange_code_posts_the_verifier_and_saves_nothing_itself():
    payload = json.dumps({"access_token": "a1", "refresh_token": "r1", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    tokens = exchange_code(transport, FakeClock(7_000), "client-abc", "code-1", RFC_VERIFIER)
    method, url, data = transport.requests[0]
    assert (method, url) == ("POST", "https://accounts.spotify.com/api/token")
    assert data["grant_type"] == "authorization_code"
    assert data["code_verifier"] == RFC_VERIFIER
    assert data["redirect_uri"] == REDIRECT_URI
    assert tokens == Tokens("a1", "r1", 7_000 + 3_600_000)


def test_exchange_code_raises_on_a_rejected_exchange():
    transport = FakeTransport([Response(400, b'{"error":"invalid_grant"}')])
    with pytest.raises(SystemExit):
        exchange_code(transport, FakeClock(), "client-abc", "bad", RFC_VERIFIER)


def test_refresh_tokens_sends_the_refresh_grant():
    payload = json.dumps({"access_token": "a2", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    refreshed = refresh_tokens(
        transport, FakeClock(1_000), "client-abc", Tokens("a1", "r1", 0)
    )
    _, _, data = transport.requests[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "r1"
    assert refreshed == Tokens("a2", "r1", 1_000 + 3_600_000)


def test_token_provider_returns_a_live_token_without_calling_the_network(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("still-good", "r1", expires_at=10_000_000), path)
    transport = FakeTransport([])  # any request would raise
    provide = token_provider(transport, FakeClock(1_000), "client-abc", path)
    assert provide() == "still-good"


def test_token_provider_refreshes_and_persists_an_expiring_token(tmp_path):
    path = tmp_path / "tokens.json"
    save_tokens(Tokens("stale", "r1", expires_at=100_000), path)
    payload = json.dumps({"access_token": "fresh", "expires_in": 3600})
    transport = FakeTransport([Response(200, payload.encode())])
    provide = token_provider(transport, FakeClock(99_000), "client-abc", path)
    assert provide() == "fresh"
    assert load_tokens(path).access_token == "fresh"


def test_wait_for_code_captures_the_code_from_a_real_loopback_request():
    # Local sockets only - this is not the wire. Port 0 lets the OS pick a free port so the
    # test never collides with a real capture session holding 8888.
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    captured: list[str] = []
    thread = threading.Thread(target=lambda: captured.append(wait_for_code(port=port)))
    thread.start()
    # The server binds inside wait_for_code; retry briefly until the socket is listening.
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=xyz789", timeout=1)
            break
        except OSError:
            continue
    thread.join(timeout=5)
    assert captured == ["xyz789"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.auth'`

- [ ] **Step 3: Write the implementation**

Create `src/mldj/auth.py`:

```python
"""Spotify PKCE auth for a local script. Ported from cd-player's auth.ts.

Two things change in the port: localStorage becomes a gitignored JSON file under data/,
and the browser redirect becomes a one-shot loopback HTTP server on the exact redirect
URI Spotify has registered.

Phase 0 only reads what is playing, so SCOPE is the single read scope. Do not widen it;
user-modify-playback-state belongs to Phase 4.
"""

import base64
import dataclasses
import hashlib
import http.server
import json
import secrets
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mldj.clock import Clock
from mldj.transport import Transport

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing"
VERIFIER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
REFRESH_MARGIN_MS = 60_000
TOKENS_PATH = Path("data/.spotify-tokens.json")  # data/ is gitignored; this repo is public


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: int  # epoch ms


def random_verifier(length: int = 64) -> str:
    return "".join(secrets.choice(VERIFIER_ALPHABET) for _ in range(length))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(client_id: str, verifier: str) -> str:
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge(verifier),
        }
    )
    return f"{AUTH_URL}?{params}"


def parse_callback_code(path: str) -> str | None:
    query = urllib.parse.urlparse(path).query
    values = urllib.parse.parse_qs(query).get("code")
    return values[0] if values else None


def merge_token_response(prev: Tokens | None, payload: dict, now_ms: int) -> Tokens:
    """Spotify's refresh response often omits refresh_token; keep the one we already hold."""
    return Tokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token") or (prev.refresh_token if prev else ""),
        expires_at=now_ms + int(payload["expires_in"]) * 1000,
    )


def should_refresh(tokens: Tokens, now_ms: int) -> bool:
    return now_ms >= tokens.expires_at - REFRESH_MARGIN_MS


def load_tokens(path: Path = TOKENS_PATH) -> Tokens | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Tokens(raw["access_token"], raw["refresh_token"], int(raw["expires_at"]))


def save_tokens(tokens: Tokens, path: Path = TOKENS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(tokens)), encoding="utf-8")


def wait_for_code(port: int = 8888, max_requests: int = 5) -> str:
    """Serve loopback requests until one carries a ?code=, then return it.

    A browser may request /favicon.ico alongside the callback, so this serves up to
    max_requests rather than exactly one.
    """
    captured: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming, not ours
            code = parse_callback_code(self.path)
            if code:
                captured.append(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = b"<p>ml-dj is authorized. You can close this tab.</p>"
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass  # keep the capture console quiet

    with http.server.HTTPServer(("127.0.0.1", port), Handler) as server:
        for _ in range(max_requests):
            server.handle_request()
            if captured:
                break
    if not captured:
        raise SystemExit("the Spotify callback carried no ?code= - authorization failed")
    return captured[0]


def _request_tokens(
    transport: Transport, clock: Clock, prev: Tokens | None, data: dict[str, str]
) -> Tokens:
    response = transport.post(TOKEN_URL, data)
    if response.status != 200:
        raise SystemExit(
            f"Spotify token endpoint returned {response.status}: "
            f"{response.body.decode('utf-8', 'replace')[:200]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit("Spotify token endpoint returned an unreadable body")
    return merge_token_response(prev, payload, clock.now_ms())


def exchange_code(
    transport: Transport, clock: Clock, client_id: str, code: str, verifier: str
) -> Tokens:
    return _request_tokens(
        transport,
        clock,
        None,
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )


def refresh_tokens(
    transport: Transport, clock: Clock, client_id: str, tokens: Tokens
) -> Tokens:
    return _request_tokens(
        transport,
        clock,
        tokens,
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
        },
    )


def login(
    transport: Transport, clock: Clock, client_id: str, path: Path = TOKENS_PATH
) -> Tokens:
    """Interactive one-time authorization. Opens a browser and waits on the loopback."""
    verifier = random_verifier()
    url = authorize_url(client_id, verifier)
    print("Opening Spotify authorization. If no browser opens, visit:\n" + url)
    webbrowser.open(url)
    code = wait_for_code()
    tokens = exchange_code(transport, clock, client_id, code, verifier)
    save_tokens(tokens, path)
    return tokens


def token_provider(
    transport: Transport, clock: Clock, client_id: str, path: Path = TOKENS_PATH
) -> Callable[[], str]:
    """Return a callable that always hands back a live access token.

    The capture loop calls this on every poll, so refresh has to be transparent: a
    multi-hour session outlives a one-hour token.
    """

    def provide() -> str:
        tokens = load_tokens(path)
        if tokens is None:
            tokens = login(transport, clock, client_id, path)
        if should_refresh(tokens, clock.now_ms()):
            tokens = refresh_tokens(transport, clock, client_id, tokens)
            save_tokens(tokens, path)
        return tokens.access_token

    return provide
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auth.py -v`
Expected: PASS — 17 passed

- [ ] **Step 5: Verify against the real Spotify app, once**

This is the step that confirms the credential and redirect URI are right before a listening session depends on them.

```bash
cp .env.local.example .env.local
# Fill SPOTIFY_CLIENT_ID. Reuse the one from C:\Users\jaxon\Code\cd-player\.env.local,
# and confirm http://127.0.0.1:8888/callback is registered on that app.
.venv/Scripts/python.exe -c "from mldj.auth import login; from mldj.transport import UrllibTransport; from mldj.clock import SystemClock; from mldj.env import load_env, require; print(login(UrllibTransport(), SystemClock(), require(load_env(), 'SPOTIFY_CLIENT_ID')).access_token[:12])"
```

Expected: a browser opens, Spotify asks to authorize, the tab shows "ml-dj is authorized", and the first 12 characters of an access token print. `data/.spotify-tokens.json` now exists.

If Spotify shows `INVALID_CLIENT: Invalid redirect URI`, the app's registered URI does not match `http://127.0.0.1:8888/callback` exactly — fix it in the Spotify dashboard, not in the code.

- [ ] **Step 6: Confirm no secret is staged, then commit**

```bash
git status --porcelain
# data/ and .env.local must NOT appear. If they do, stop and fix .gitignore.
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/auth.py tests/test_auth.py
git commit -m "feat: Spotify PKCE auth with a loopback callback and transparent refresh"
```

---

### Task 5: The capture loop — sessions start accumulating here

The long pole ships at the end of this task. Everything after it is analysis built while real sessions pile up, so do not move on until `mldj capture --label dj` has recorded a genuine session.

**Poll interval.** The default is 1000 ms, against `cd-player`'s 5000 ms, which collapses fast skips and multi-skip bursts. At 1 request/second the loop makes 60 requests/minute, comfortably inside Spotify's rough 180/minute allowance, leaving headroom for the token refresh. 1000 ms is a **hypothesis**; Task 12 measures whether it was fast enough and is where the value gets justified or changed.

**Files:**
- Create: `src/mldj/events.py`
- Create: `src/mldj/capture.py`
- Modify: `src/mldj/cli.py` — register the `capture` subcommand
- Test: `tests/test_events.py`, `tests/test_capture.py`

**Interfaces:**
- Consumes: `mldj.nowplaying.{NowPlaying, parse_now_playing, ENDPOINT}`, `mldj.transport.{Transport, retry_after_ms, DEFAULT_RETRY_MS}`, `mldj.clock.Clock`, `mldj.auth.token_provider`, `mldj.env.{load_env, require}`, `mldj.cli.build_parser`
- Produces:
  - `mldj.events.SESSIONS_DIR: Path`
  - `mldj.events.session_id(now_ms: int) -> str` — `"%Y%m%dT%H%M%SZ"` in UTC
  - `mldj.events.session_path(label: str, sid: str, root: Path = SESSIONS_DIR) -> Path`
  - `mldj.events.EventWriter(path: Path)` — a context manager with `write(event: dict) -> None`
  - `mldj.events.read_events(path: Path) -> Iterator[dict]`
  - `mldj.events.session_start_event(now_ms, label, interval_ms, sid) -> dict`
  - `mldj.events.session_end_event(now_ms, reason) -> dict`
  - `mldj.events.gap_event(now_ms, reason, retry_ms) -> dict`
  - `mldj.events.poll_event(np: NowPlaying | None, now_ms: int) -> dict`
  - `mldj.capture.DEFAULT_INTERVAL_MS: int = 1000`
  - `mldj.capture.run_capture(*, transport, clock, access_token, writer, label, sid, interval_ms, should_stop) -> None`
  - `mldj.capture.register(subparsers) -> None`

- [ ] **Step 1: Write the failing tests for the event log**

Create `tests/test_events.py`:

```python
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
    assert session_id(1_759_190_400_000) == "20250930T010000Z"


def test_session_path_names_the_file_by_label_and_id(tmp_path):
    assert session_path("dj", "20250930T010000Z", tmp_path).name == "dj-20250930T010000Z.jsonl"


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
    event = session_start_event(1_000, "dj", 1000, "20250930T010000Z")
    assert event == {
        "t": 1_000,
        "type": "session_start",
        "label": "dj",
        "interval_ms": 1000,
        "session": "20250930T010000Z",
    }


def test_gap_and_end_events():
    assert gap_event(5, "rate-limited", 3000) == {
        "t": 5,
        "type": "gap",
        "reason": "rate-limited",
        "retry_ms": 3000,
    }
    assert session_end_event(9, "stopped") == {"t": 9, "type": "session_end", "reason": "stopped"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.events'`

- [ ] **Step 3: Write the event log**

Create `src/mldj/events.py`:

```python
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
    # interval_ms is recorded so the analysis can tell a real gap from a normal poll spacing.
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
```

- [ ] **Step 4: Run the event tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_events.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Write the failing tests for the loop**

Create `tests/test_capture.py`:

```python
import json

from mldj.capture import run_capture
from mldj.events import EventWriter, read_events
from mldj.transport import Response

from fakes import FakeClock, FakeTransport

TRACK_BODY = json.dumps(
    {
        "progress_ms": 45000,
        "is_playing": True,
        "currently_playing_type": "track",
        "item": {
            "id": "id1",
            "name": "Ceiling Fan",
            "duration_ms": 213000,
            "artists": [{"name": "Paper Lanterns"}],
        },
    }
).encode()


def stop_after(n: int):
    """A should_stop predicate that allows exactly n iterations."""
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > n

    return should_stop


def capture_to(tmp_path, transport, clock, should_stop, interval_ms=1000):
    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        run_capture(
            transport=transport,
            clock=clock,
            access_token=lambda: "tok",
            writer=writer,
            label="dj",
            sid="20250930T010000Z",
            interval_ms=interval_ms,
            should_stop=should_stop,
        )
    return list(read_events(path))


def test_capture_writes_start_polls_and_end(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY), Response(200, TRACK_BODY)])
    events = capture_to(tmp_path, transport, FakeClock(1_000), stop_after(2))
    assert [e["type"] for e in events] == ["session_start", "poll", "poll", "session_end"]
    assert events[0]["interval_ms"] == 1000
    assert events[1]["id"] == "id1"
    assert events[-1]["reason"] == "stopped"


def test_capture_sleeps_the_interval_between_polls_and_never_really_waits(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY)] * 3)
    clock = FakeClock(1_000)
    capture_to(tmp_path, transport, clock, stop_after(3))
    assert clock.sleeps == [1000, 1000, 1000]


def test_capture_sends_a_bearer_token_on_every_poll(tmp_path):
    transport = FakeTransport([Response(200, TRACK_BODY)])
    capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    _, url, headers = transport.requests[0]
    assert "me/player/currently-playing" in url
    assert headers["Authorization"] == "Bearer tok"


def test_capture_records_a_204_as_idle(tmp_path):
    transport = FakeTransport([Response(204, b"")])
    events = capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    assert [e["type"] for e in events] == ["session_start", "idle", "session_end"]


def test_capture_honours_retry_after_on_a_429_and_logs_a_gap(tmp_path):
    transport = FakeTransport(
        [Response(429, b"", {"Retry-After": "3"}), Response(200, TRACK_BODY)]
    )
    clock = FakeClock(1_000)
    events = capture_to(tmp_path, transport, clock, stop_after(2))
    types = [e["type"] for e in events]
    assert types == ["session_start", "gap", "poll", "session_end"]
    gap = events[1]
    assert (gap["reason"], gap["retry_ms"]) == ("rate-limited", 3000)
    assert clock.sleeps == [3000, 1000]


def test_capture_logs_a_gap_for_any_other_http_failure(tmp_path):
    transport = FakeTransport([Response(500, b"boom")])
    events = capture_to(tmp_path, transport, FakeClock(), stop_after(1))
    assert events[1]["type"] == "gap"
    assert events[1]["reason"] == "http-500"


def test_capture_writes_session_end_even_when_the_loop_raises(tmp_path):
    # Ctrl-C during a real session must still close the log cleanly.
    class Boom(FakeTransport):
        def get(self, url, headers=None):
            raise KeyboardInterrupt

    path = tmp_path / "s.jsonl"
    with EventWriter(path) as writer:
        try:
            run_capture(
                transport=Boom(),
                clock=FakeClock(),
                access_token=lambda: "tok",
                writer=writer,
                label="dj",
                sid="sid",
                interval_ms=1000,
                should_stop=stop_after(1),
            )
        except KeyboardInterrupt:
            pass
    events = list(read_events(path))
    assert events[-1]["type"] == "session_end"
    assert events[-1]["reason"] == "interrupted"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capture.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.capture'`

- [ ] **Step 7: Write the loop and wire up the subcommand**

Create `src/mldj/capture.py`:

```python
"""Poll Spotify's currently-playing endpoint and append raw events to a session log.

Poll interval: the default is 1000 ms, against cd-player's 5000 ms, which collapses fast
skips and multi-skip bursts. At 1 request/second this makes 60 requests/minute, well
inside Spotify's rough 180/minute allowance. 1000 ms is a hypothesis, not a settled
value - `mldj report --diagnostics` (Task 12) is where it gets justified or changed.
"""

import argparse
import threading
from collections.abc import Callable

from mldj.clock import Clock, SystemClock
from mldj.env import load_env, require
from mldj.events import (
    EventWriter,
    gap_event,
    poll_event,
    session_end_event,
    session_id,
    session_path,
    session_start_event,
)
from mldj.nowplaying import ENDPOINT, parse_now_playing
from mldj.transport import DEFAULT_RETRY_MS, Transport, UrllibTransport, retry_after_ms

DEFAULT_INTERVAL_MS = 1000


def run_capture(
    *,
    transport: Transport,
    clock: Clock,
    access_token: Callable[[], str],
    writer: EventWriter,
    label: str,
    sid: str,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    should_stop: Callable[[], bool],
) -> None:
    """Poll until should_stop() is true, writing one event per poll.

    access_token is a callable rather than a string because a multi-hour session outlives
    a one-hour token; token_provider refreshes behind this call.
    """
    writer.write(session_start_event(clock.now_ms(), label, interval_ms, sid))
    reason = "stopped"
    try:
        while not should_stop():
            now = clock.now_ms()
            response = transport.get(ENDPOINT, {"Authorization": f"Bearer {access_token()}"})

            if response.status == 429:
                wait_ms = retry_after_ms(response)
                writer.write(gap_event(now, "rate-limited", wait_ms))
                clock.sleep_ms(wait_ms)
                continue
            if response.status == 204:
                writer.write(poll_event(None, now))
            elif response.status == 200:
                writer.write(poll_event(parse_now_playing(response.json(), now), now))
            else:
                writer.write(gap_event(now, f"http-{response.status}", DEFAULT_RETRY_MS))
                clock.sleep_ms(DEFAULT_RETRY_MS)
                continue

            clock.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        reason = "interrupted"
        raise
    except Exception:
        reason = "error"
        raise
    finally:
        writer.write(session_end_event(clock.now_ms(), reason))


def _run(args: argparse.Namespace) -> int:
    from mldj.auth import token_provider

    client_id = require(load_env(), "SPOTIFY_CLIENT_ID")
    transport = UrllibTransport()
    clock = SystemClock()
    sid = session_id(clock.now_ms())
    path = session_path(args.label, sid)
    stop = threading.Event()

    print(f"capturing to {path} every {args.interval_ms} ms - Ctrl-C to stop")
    with EventWriter(path) as writer:
        try:
            run_capture(
                transport=transport,
                clock=clock,
                access_token=token_provider(transport, clock, client_id),
                writer=writer,
                label=args.label,
                sid=sid,
                interval_ms=args.interval_ms,
                should_stop=stop.is_set,
            )
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("capture", help="record a listening session to data/sessions/")
    parser.add_argument(
        "--label",
        required=True,
        help="what was playing, e.g. dj - sessions are labeled by hand, never inferred",
    )
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    parser.set_defaults(handler=_run)
```

Modify `src/mldj/cli.py` to register it — replace `build_parser` with:

```python
def build_parser() -> argparse.ArgumentParser:
    from mldj import capture

    parser = argparse.ArgumentParser(prog="mldj", description="ml-dj Phase 0 baseline tools")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    capture.register(subparsers)
    return parser
```

- [ ] **Step 8: Run the whole suite to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS — 47 passed

- [ ] **Step 9: Capture a real session**

```bash
.venv/Scripts/python.exe -m mldj capture --label dj
```

Start the AI DJ in Spotify first. Let it run for at least twenty minutes, skipping as you naturally would. Stop with Ctrl-C.

Verify the log looks right — and confirm it is invisible to git:

```bash
ls data/sessions/
.venv/Scripts/python.exe -c "from pathlib import Path; from mldj.events import read_events; p=sorted(Path('data/sessions').glob('*.jsonl'))[-1]; e=list(read_events(p)); print(p, len(e), 'events'); print(e[0]); print(e[1]); print(sorted({x['type'] for x in e}))"
git status --porcelain
```

Expected: several hundred to several thousand events, the first a `session_start`, and `git status --porcelain` showing **nothing** under `data/`. If `data/` appears, stop and fix `.gitignore` before committing anything.

- [ ] **Step 10: Commit — capture is live**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/events.py src/mldj/capture.py src/mldj/cli.py tests/test_events.py tests/test_capture.py
git commit -m "feat: capture DJ sessions to raw-poll JSONL logs"
```

**From here on, run capture during ordinary listening whenever the DJ is on.** Sessions accumulate in the background while Tasks 6-12 are built. Capture at least one `--label dj` session per day, plus a few `--label playlist` sessions as a contrast case.

---
### Task 6: Derive plays and skips from a raw poll log

Turns raw polls into `Play` records. The rule from the spec is "the track changed, and the outgoing track's interpolated progress fell well short of its duration" — this task makes "well short" a number and, more importantly, refuses to guess when the record is ambiguous. Every transition that spans a capture gap, an ad, a pause-to-idle, a backwards seek, or the end of the session is `unknown`, not `skipped`. Counting an ambiguous transition as a skip would inflate the skip rate, and an inflated skip rate flatters the pitch's argument.

**Files:**
- Create: `src/mldj/skips.py`
- Create: `fixtures/session-dj-sample.jsonl`
- Test: `tests/test_skips.py`

**Interfaces:**
- Consumes: `mldj.nowplaying.{NowPlaying, interpolate_progress}`, `mldj.events.read_events`
- Produces:
  - `mldj.skips.GRACE_MS: int = 3000`
  - `mldj.skips.Play` — frozen dataclass: `track_id: str`, `title: str`, `artist: str`, `duration_ms: int`, `started_at_ms: int`, `ended_at_ms: int`, `listened_ms: int`, `outcome: str`, `session: str`, `label: str`, `reason: str`; property `listened_fraction -> float`
  - `mldj.skips.derive_plays(events: Iterable[dict], grace_ms: int = GRACE_MS) -> list[Play]`
  - `mldj.skips.load_plays(paths: Iterable[Path], grace_ms: int = GRACE_MS) -> list[Play]` — every session, sorted by `started_at_ms`
  - `mldj.skips.session_files(root: Path = SESSIONS_DIR, label: str | None = None) -> list[Path]`

`outcome` is exactly one of `"completed"`, `"skipped"`, `"unknown"`. `reason` is non-empty only when `outcome == "unknown"`.

- [ ] **Step 1: Write the fixture session**

Create `fixtures/session-dj-sample.jsonl`. This is hand-built and anonymized. It deliberately declares a 30000 ms interval so a full 3-minute track needs only a handful of poll lines and the fixture stays readable; the logic is duration-relative, so the slow interval changes nothing it exercises. It covers, in order: a completion, an early skip, a late skip, an ad interruption, a capture gap, and a truncated final track.

```
{"t":1000,"type":"session_start","label":"dj","interval_ms":30000,"session":"20250930T010000Z"}
{"t":1000,"type":"poll","kind":"track","id":"a1","title":"Ceiling Fan","artist":"Paper Lanterns","duration_ms":180000,"progress_ms":0,"is_playing":true,"fetched_at":1000}
{"t":31000,"type":"poll","kind":"track","id":"a1","title":"Ceiling Fan","artist":"Paper Lanterns","duration_ms":180000,"progress_ms":30000,"is_playing":true,"fetched_at":31000}
{"t":91000,"type":"poll","kind":"track","id":"a1","title":"Ceiling Fan","artist":"Paper Lanterns","duration_ms":180000,"progress_ms":90000,"is_playing":true,"fetched_at":91000}
{"t":151000,"type":"poll","kind":"track","id":"a1","title":"Ceiling Fan","artist":"Paper Lanterns","duration_ms":180000,"progress_ms":150000,"is_playing":true,"fetched_at":151000}
{"t":178000,"type":"poll","kind":"track","id":"a1","title":"Ceiling Fan","artist":"Paper Lanterns","duration_ms":180000,"progress_ms":177000,"is_playing":true,"fetched_at":178000}
{"t":181000,"type":"poll","kind":"track","id":"b2","title":"Static Bloom","artist":"Odell","duration_ms":240000,"progress_ms":0,"is_playing":true,"fetched_at":181000}
{"t":186000,"type":"poll","kind":"track","id":"b2","title":"Static Bloom","artist":"Odell","duration_ms":240000,"progress_ms":5000,"is_playing":true,"fetched_at":186000}
{"t":187000,"type":"poll","kind":"track","id":"c3","title":"Low Ceiling","artist":"Odell","duration_ms":200000,"progress_ms":0,"is_playing":true,"fetched_at":187000}
{"t":217000,"type":"poll","kind":"track","id":"c3","title":"Low Ceiling","artist":"Odell","duration_ms":200000,"progress_ms":30000,"is_playing":true,"fetched_at":217000}
{"t":277000,"type":"poll","kind":"track","id":"c3","title":"Low Ceiling","artist":"Odell","duration_ms":200000,"progress_ms":90000,"is_playing":true,"fetched_at":277000}
{"t":337000,"type":"poll","kind":"track","id":"c3","title":"Low Ceiling","artist":"Odell","duration_ms":200000,"progress_ms":150000,"is_playing":true,"fetched_at":337000}
{"t":338000,"type":"poll","kind":"track","id":"d4","title":"Half Light","artist":"Wire Season","duration_ms":190000,"progress_ms":0,"is_playing":true,"fetched_at":338000}
{"t":368000,"type":"poll","kind":"track","id":"d4","title":"Half Light","artist":"Wire Season","duration_ms":190000,"progress_ms":30000,"is_playing":true,"fetched_at":368000}
{"t":398000,"type":"poll","kind":"ad","id":"ad","title":"","artist":"","duration_ms":0,"progress_ms":0,"is_playing":true,"fetched_at":398000}
{"t":428000,"type":"poll","kind":"track","id":"e5","title":"Paper Cut","artist":"Wire Season","duration_ms":210000,"progress_ms":0,"is_playing":true,"fetched_at":428000}
{"t":458000,"type":"poll","kind":"track","id":"e5","title":"Paper Cut","artist":"Wire Season","duration_ms":210000,"progress_ms":30000,"is_playing":true,"fetched_at":458000}
{"t":488000,"type":"gap","reason":"rate-limited","retry_ms":30000}
{"t":518000,"type":"poll","kind":"track","id":"e5","title":"Paper Cut","artist":"Wire Season","duration_ms":210000,"progress_ms":90000,"is_playing":true,"fetched_at":518000}
{"t":548000,"type":"poll","kind":"track","id":"f6","title":"Blue Monday - 2016 Remaster","artist":"New Order","duration_ms":270000,"progress_ms":0,"is_playing":true,"fetched_at":548000}
{"t":578000,"type":"poll","kind":"track","id":"f6","title":"Blue Monday - 2016 Remaster","artist":"New Order","duration_ms":270000,"progress_ms":30000,"is_playing":true,"fetched_at":578000}
{"t":608000,"type":"session_end","reason":"stopped"}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_skips.py`:

```python
from pathlib import Path

from mldj.events import read_events
from mldj.skips import Play, derive_plays

FIXTURE = Path(__file__).parent.parent / "fixtures" / "session-dj-sample.jsonl"


def sample_plays() -> list[Play]:
    return derive_plays(read_events(FIXTURE))


def test_every_track_run_becomes_one_play_and_ads_are_excluded():
    plays = sample_plays()
    assert [p.track_id for p in plays] == ["a1", "b2", "c3", "d4", "e5", "f6"]


def test_a_track_played_to_the_end_is_completed():
    play = sample_plays()[0]
    assert play.outcome == "completed"
    assert play.listened_ms == 180000
    assert play.reason == ""


def test_an_early_skip_is_detected_with_its_fraction():
    play = sample_plays()[1]
    assert play.outcome == "skipped"
    assert play.listened_ms == 6000
    assert round(play.listened_fraction, 3) == 0.025


def test_a_late_skip_is_still_a_skip():
    # Skip weighting in Phase 3 needs the fraction, so late skips must not be silently dropped.
    play = sample_plays()[2]
    assert play.outcome == "skipped"
    assert play.listened_ms == 151000
    assert round(play.listened_fraction, 3) == 0.755


def test_a_track_interrupted_by_an_ad_is_unknown_not_skipped():
    play = sample_plays()[3]
    assert play.outcome == "unknown"
    assert "non-track" in play.reason


def test_a_track_spanning_a_capture_gap_is_unknown():
    play = sample_plays()[4]
    assert play.outcome == "unknown"
    assert "gap" in play.reason


def test_the_final_truncated_track_is_unknown_not_skipped():
    # Ctrl-C is not a skip. Counting it as one would inflate the headline skip rate.
    play = sample_plays()[5]
    assert play.outcome == "unknown"
    assert "session ended" in play.reason


def test_every_play_carries_its_session_id():
    assert {p.session for p in sample_plays()} == {"20250930T010000Z"}


def test_a_stale_last_poll_makes_the_transition_unknown():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 1000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {
            "t": 60_000, "type": "poll", "kind": "track", "id": "y", "title": "U", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 60_000,
        },
        {"t": 61_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "stale" in first.reason


def test_progress_moving_backwards_makes_the_play_unknown():
    # A seek back or a restart means interpolated progress is not listening time.
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 30000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 100000, "is_playing": True, "fetched_at": 0,
        },
        {
            "t": 30_000, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 2000, "is_playing": True, "fetched_at": 30_000,
        },
        {
            "t": 31_000, "type": "poll", "kind": "track", "id": "y", "title": "U", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 31_000,
        },
        {"t": 32_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "backwards" in first.reason


def test_playback_going_idle_is_unknown_not_a_skip():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 30000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 200000, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {"t": 30_000, "type": "idle"},
        {"t": 31_000, "type": "session_end", "reason": "stopped"},
    ]
    first = derive_plays(events)[0]
    assert first.outcome == "unknown"
    assert "stopped" in first.reason


def test_a_zero_duration_run_produces_no_play():
    events = [
        {"t": 0, "type": "session_start", "label": "dj", "interval_ms": 1000, "session": "s"},
        {
            "t": 0, "type": "poll", "kind": "track", "id": "x", "title": "T", "artist": "A",
            "duration_ms": 0, "progress_ms": 0, "is_playing": True, "fetched_at": 0,
        },
        {"t": 1_000, "type": "session_end", "reason": "stopped"},
    ]
    assert derive_plays(events) == []
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skips.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.skips'`

- [ ] **Step 4: Write the implementation**

Create `src/mldj/skips.py`:

```python
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

    if reason:
        outcome = "unknown"
    elif listened_ms >= duration_ms - grace_ms:
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


def derive_plays(events: Iterable[dict], grace_ms: int = GRACE_MS) -> list[Play]:
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
                run, at_ms, interval_ms, session, label, grace_ms, taint or successor_taint
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

    close(int(run[-1]["t"]) if run else 0, "log ended without session_end")
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skips.py -v`
Expected: PASS — 12 passed

- [ ] **Step 6: Sanity-check against your real captured session**

```bash
.venv/Scripts/python.exe -c "from mldj.skips import load_plays, session_files; from collections import Counter; p=load_plays(session_files(label='dj')); print(len(p),'plays'); print(Counter(x.outcome for x in p)); print(Counter(x.reason for x in p if x.reason))"
```

Expected: a plausible mix. If `unknown` dominates, read the reasons — a flood of `capture gap` means the poll interval is tripping rate limits, and a flood of `stale` means the loop is being starved. Note the numbers; Task 12 formalizes this check.

- [ ] **Step 7: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/skips.py tests/test_skips.py fixtures/session-dj-sample.jsonl
git commit -m "feat: derive plays and skip outcomes from raw poll logs"
```

---

### Task 7: Track matching between Spotify and Last.fm

**This is the one unsolved problem in Phase 0.** Spotify says `"Blue Monday - 2016 Remaster"`; Last.fm says `"Blue Monday"`. Novelty rate is only as trustworthy as this matcher, because the whole claim is "you had never heard this before."

**Which way the error hurts.** Over-matching makes a genuinely new DJ track look like something already in your history, so it is counted as familiar, so **measured novelty drops** — which makes the DJ look worse at exploration and flatters the pitch's argument. That is the worst direction to be wrong in. So the matcher is conservative by construction: it strips a segment only when the segment is recognisably a version qualifier, never merely because it sits in brackets. `(Don't Fear) The Reaper` must survive intact.

**The stated assumption.** The unit of novelty is **the song, not the recording**. A remaster, radio edit, live take, or acoustic version of a song you have heard is not new music. A remix credited to a different artist is a different track. This is a judgment call, it is written into the gold set, and beat 6's honesty check should be able to state it out loud.

**Files:**
- Create: `src/mldj/match.py`
- Create: `fixtures/match-gold.json`
- Test: `tests/test_match.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `mldj.match.normalize_text(value: str) -> str`
  - `mldj.match.normalize_title(title: str) -> str`
  - `mldj.match.normalize_artist(artist: str) -> str`
  - `mldj.match.track_key(artist: str, title: str) -> tuple[str, str]`
  - `mldj.match.same_track(a: tuple[str, str], b: tuple[str, str]) -> bool`
  - `mldj.match.QUALIFIER_WORDS`, `mldj.match.STRONG_QUALIFIERS`, `mldj.match.NEVER_DROP` — frozensets, extended when the gold set catches a miss

- [ ] **Step 1: Write the gold set**

Create `fixtures/match-gold.json`:

```json
{
  "assumption": "The unit of novelty is the song, not the recording. Remasters, radio edits, live takes, and acoustic versions of a song count as the same track. A remix or cover credited to another artist counts as a different track.",
  "pairs": [
    {"label": "same", "why": "trailing remaster suffix",
     "a": {"artist": "New Order", "title": "Blue Monday - 2016 Remaster"},
     "b": {"artist": "New Order", "title": "Blue Monday"}},
    {"label": "same", "why": "bracketed remastered qualifier",
     "a": {"artist": "Talking Heads", "title": "Once in a Lifetime (Remastered)"},
     "b": {"artist": "Talking Heads", "title": "Once in a Lifetime"}},
    {"label": "same", "why": "year-prefixed remastered version",
     "a": {"artist": "Kate Bush", "title": "Running Up That Hill - 2018 Remaster"},
     "b": {"artist": "Kate Bush", "title": "Running Up That Hill"}},
    {"label": "same", "why": "radio edit",
     "a": {"artist": "Odell", "title": "Static Bloom - Radio Edit"},
     "b": {"artist": "Odell", "title": "Static Bloom"}},
    {"label": "same", "why": "single version",
     "a": {"artist": "Wire Season", "title": "Half Light (Single Version)"},
     "b": {"artist": "Wire Season", "title": "Half Light"}},
    {"label": "same", "why": "live qualifier with a venue after it",
     "a": {"artist": "Paper Lanterns", "title": "Ceiling Fan - Live at the Bell House"},
     "b": {"artist": "Paper Lanterns", "title": "Ceiling Fan"}},
    {"label": "same", "why": "acoustic version",
     "a": {"artist": "Odell", "title": "Low Ceiling (Acoustic)"},
     "b": {"artist": "Odell", "title": "Low Ceiling"}},
    {"label": "same", "why": "deluxe edition bonus track marker",
     "a": {"artist": "Wire Season", "title": "Paper Cut (Bonus Track)"},
     "b": {"artist": "Wire Season", "title": "Paper Cut"}},
    {"label": "same", "why": "feat formatting differs",
     "a": {"artist": "Odell", "title": "Static Bloom (feat. Paper Lanterns)"},
     "b": {"artist": "Odell", "title": "Static Bloom"}},
    {"label": "same", "why": "ft abbreviation on the artist field",
     "a": {"artist": "Odell ft. Paper Lanterns", "title": "Static Bloom"},
     "b": {"artist": "Odell", "title": "Static Bloom"}},
    {"label": "same", "why": "casing only",
     "a": {"artist": "NEW ORDER", "title": "BLUE MONDAY"},
     "b": {"artist": "New Order", "title": "Blue Monday"}},
    {"label": "same", "why": "punctuation and apostrophes",
     "a": {"artist": "Guns N' Roses", "title": "Sweet Child o' Mine"},
     "b": {"artist": "Guns N Roses", "title": "Sweet Child O Mine"}},
    {"label": "same", "why": "ampersand versus and",
     "a": {"artist": "Simon & Garfunkel", "title": "America"},
     "b": {"artist": "Simon and Garfunkel", "title": "America"}},
    {"label": "same", "why": "diacritics",
     "a": {"artist": "Sigur Rós", "title": "Hoppípolla"},
     "b": {"artist": "Sigur Ros", "title": "Hoppipolla"}},
    {"label": "same", "why": "whitespace runs",
     "a": {"artist": "Paper  Lanterns", "title": "Ceiling   Fan"},
     "b": {"artist": "Paper Lanterns", "title": "Ceiling Fan"}},
    {"label": "same", "why": "explicit marker",
     "a": {"artist": "Odell", "title": "Low Ceiling (Explicit)"},
     "b": {"artist": "Odell", "title": "Low Ceiling"}},
    {"label": "same", "why": "stacked qualifiers",
     "a": {"artist": "New Order", "title": "Blue Monday (Remastered) - 2016 Remaster"},
     "b": {"artist": "New Order", "title": "Blue Monday"}},

    {"label": "different", "why": "same title, different artist",
     "a": {"artist": "Paper Lanterns", "title": "America"},
     "b": {"artist": "Simon & Garfunkel", "title": "America"}},
    {"label": "different", "why": "a remix credited to another artist is another recording",
     "a": {"artist": "Odell", "title": "Static Bloom - Wire Season Remix"},
     "b": {"artist": "Odell", "title": "Static Bloom"}},
    {"label": "different", "why": "numbered parts are separate pieces",
     "a": {"artist": "Wire Season", "title": "Half Light, Pt. 2"},
     "b": {"artist": "Wire Season", "title": "Half Light"}},
    {"label": "different", "why": "a parenthetical that is part of the actual title",
     "a": {"artist": "Blue Öyster Cult", "title": "(Don't Fear) The Reaper"},
     "b": {"artist": "Blue Öyster Cult", "title": "The Reaper"}},
    {"label": "different", "why": "different songs sharing a word",
     "a": {"artist": "Odell", "title": "Low Ceiling"},
     "b": {"artist": "Odell", "title": "Low Ceiling Blues"}},
    {"label": "different", "why": "a cover is a different recording",
     "a": {"artist": "Paper Lanterns", "title": "Blue Monday (New Order Cover)"},
     "b": {"artist": "New Order", "title": "Blue Monday"}},
    {"label": "different", "why": "an unrecognised bracketed phrase is kept, not stripped",
     "a": {"artist": "Wire Season", "title": "Paper Cut (Bell House Sessions Reprise)"},
     "b": {"artist": "Wire Season", "title": "Paper Cut"}}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_match.py`:

```python
import json
from pathlib import Path

import pytest

from mldj.match import normalize_artist, normalize_title, same_track, track_key

GOLD = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "match-gold.json").read_text(encoding="utf-8")
)


def gold_ids() -> list[str]:
    return [f"{p['label']}:{p['why']}" for p in GOLD["pairs"]]


@pytest.mark.parametrize("pair", GOLD["pairs"], ids=gold_ids())
def test_matcher_agrees_with_the_gold_set(pair):
    a = track_key(pair["a"]["artist"], pair["a"]["title"])
    b = track_key(pair["b"]["artist"], pair["b"]["title"])
    expected = pair["label"] == "same"
    assert same_track(a, b) is expected, (
        f"{pair['why']}\n  {pair['a']} -> {a}\n  {pair['b']} -> {b}"
    )


def test_normalize_title_strips_a_recognised_qualifier():
    assert normalize_title("Blue Monday - 2016 Remaster") == "blue monday"


def test_normalize_title_keeps_an_unrecognised_parenthetical():
    # Stripping every bracket would over-match, and over-matching deflates novelty.
    assert normalize_title("(Don't Fear) The Reaper") == "dont fear the reaper"


def test_normalize_title_never_returns_empty():
    assert normalize_title("(Remastered)") != ""


def test_normalize_artist_drops_a_featured_credit():
    assert normalize_artist("Odell ft. Paper Lanterns") == "odell"


def test_normalize_artist_keeps_a_genuine_collaboration():
    assert normalize_artist("Simon & Garfunkel") == "simon and garfunkel"


def test_track_key_is_a_pair_of_normalized_strings():
    assert track_key("New Order", "Blue Monday - 2016 Remaster") == ("new order", "blue monday")
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.match'`

- [ ] **Step 4: Write the implementation**

Create `src/mldj/match.py`:

```python
"""Match Spotify track strings against Last.fm scrobble strings.

This is the one unsolved problem in Phase 0. Novelty rate is only as trustworthy as this
module, because the pitch's claim is "you had never heard this before".

Error direction matters more than accuracy here. Over-matching maps a genuinely new DJ
track onto something already in the history, counts it as familiar, and *lowers* measured
novelty - which makes the DJ look worse and flatters the argument. So the design is
conservative: a trailing segment is dropped only when it is recognisably a version
qualifier, never merely because it sits in brackets. `(Don't Fear) The Reaper` survives.

Stated assumption: the unit is the song, not the recording. Remasters, edits, live takes
and acoustic versions match; a remix or cover credited to someone else does not. The gold
set at fixtures/match-gold.json is the contract, and every word set below is extended in
response to a gold-set failure rather than from imagination.
"""

import re
import unicodedata

# A trailing segment is dropped if every word is one of these (a bare 4-digit year allowed).
QUALIFIER_WORDS = frozenset(
    {
        "remaster", "remastered", "remasters", "remastering", "master", "mastered",
        "version", "edit", "radio", "single", "album", "deluxe", "expanded", "edition",
        "reissue", "mono", "stereo", "live", "acoustic", "demo", "instrumental",
        "bonus", "track", "explicit", "clean", "anniversary", "original", "digital",
        "take", "alternate", "extended", "the", "of", "from", "a", "an", "and",
        "in", "at", "on", "for", "feat", "ft", "featuring",
    }
)

# If a trailing segment *starts* with one of these, the whole segment goes, however it
# continues - this is what makes "Live at the Bell House" a qualifier rather than a title.
STRONG_QUALIFIERS = frozenset(
    {"remaster", "remastered", "live", "acoustic", "demo", "instrumental", "reissue"}
)

# Any of these anywhere in a segment forbids dropping it: these mark a different recording
# or a different piece, not a different master of the same one.
NEVER_DROP = frozenset(
    {"remix", "rework", "cover", "reprise", "part", "pt", "vip", "dub", "mashup",
     "interlude", "sessions", "session", "medley", "continuous"}
)

_TRAILING_BRACKET = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]\s*$")
_TRAILING_DASH = re.compile(r"\s+-\s+([^-]+)$")
_YEAR = re.compile(r"^\d{4}$")
_FEAT = re.compile(r"\s*[\(\[]?\s*\b(?:feat|ft|featuring)\b\.?\s+.*$", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[\s/,]+")


def _is_qualifier(segment: str) -> bool:
    words = [w.strip(".") for w in _WORD_SPLIT.split(segment.lower().strip()) if w.strip(".")]
    if not words:
        return False
    if any(word in NEVER_DROP for word in words):
        return False
    if words[0] in STRONG_QUALIFIERS:
        return True
    return all(_YEAR.match(word) or word in QUALIFIER_WORDS for word in words)


def _strip_qualifiers(title: str) -> str:
    """Peel recognised version qualifiers off the end. Titles rarely stack more than a few."""
    current = title.strip()
    for _ in range(4):
        for pattern in (_TRAILING_BRACKET, _TRAILING_DASH):
            match = pattern.search(current)
            if match and _is_qualifier(match.group(1)):
                stripped = current[: match.start()].strip()
                if stripped:  # never strip a title down to nothing
                    current = stripped
                    break
        else:
            break
    return current


def normalize_text(value: str) -> str:
    """Casefold, drop diacritics and punctuation, spell out &, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    spelled_out = without_marks.casefold().replace("&", " and ")
    alnum_only = "".join(c if (c.isalnum() or c.isspace()) else " " for c in spelled_out)
    return " ".join(alnum_only.split())


def normalize_title(title: str) -> str:
    return normalize_text(_FEAT.sub("", _strip_qualifiers(title))) or normalize_text(title)


def normalize_artist(artist: str) -> str:
    """Artist names keep their qualifiers; only a featured credit is dropped."""
    return normalize_text(_FEAT.sub("", artist)) or normalize_text(artist)


def track_key(artist: str, title: str) -> tuple[str, str]:
    return (normalize_artist(artist), normalize_title(title))


def same_track(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a == b
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_match.py -v`
Expected: PASS — 30 passed (24 gold pairs plus 6 unit tests)

If a gold pair fails, fix the word sets or the segment rules — **do not weaken the gold pair to match the code.** The gold set is the contract. If a pair turns out to be genuinely ambiguous, it does not belong in the gold set at all; delete it and say why in the commit message.

- [ ] **Step 6: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/match.py tests/test_match.py fixtures/match-gold.json
git commit -m "feat: conservative Spotify<->Last.fm track matching with a gold set"
```

---

### Task 8: Last.fm client and resumable scrobble ingest

Pulls the full listening history into `data/scrobbles.jsonl`, and adds the `track.getTopTags` call that Task 10 needs. At 200 scrobbles per page, 39,000 scrobbles is roughly 195 requests, so this has to be paced, resumable, and idempotent.

Three real gotchas, each with a test:
1. `user.getRecentTracks` prepends a **now-playing** entry with no `date` field. Included blindly, it becomes a scrobble with no timestamp.
2. Paging while new scrobbles arrive shifts the page boundaries, duplicating or dropping rows. Pinning `to` at ingest start freezes the window.
3. Last.fm reports API errors in a **200** response body, not an HTTP status.

**Files:**
- Create: `src/mldj/lastfm.py`
- Create: `src/mldj/scrobbles.py`
- Modify: `src/mldj/cli.py` — register `ingest`
- Create: `fixtures/lastfm-recenttracks-page.json`, `fixtures/lastfm-toptags.json`
- Test: `tests/test_lastfm.py`, `tests/test_scrobbles.py`

**Interfaces:**
- Consumes: `mldj.transport.{Transport, Response, retry_after_ms}`, `mldj.clock.Clock`, `mldj.match.track_key`, `mldj.env.{load_env, require}`
- Produces:
  - `mldj.lastfm.API_ROOT: str`, `mldj.lastfm.LastfmError`
  - `mldj.lastfm.LastfmClient(transport, clock, api_key, min_interval_ms=250, max_attempts=3)` with `call(method: str, **params) -> dict`
  - `mldj.lastfm.top_tags(client, artist: str, title: str) -> list[tuple[str, int]]`
  - `mldj.lastfm.top_tags_cached(client, artist, title, cache_dir: Path = TAGS_DIR) -> list[tuple[str, int]]`
  - `mldj.lastfm.TAGS_DIR: Path = Path("data/tags")`
  - `mldj.scrobbles.Scrobble` — frozen dataclass: `uts: int`, `artist: str`, `title: str`, `album: str`
  - `mldj.scrobbles.parse_recent_tracks_page(payload: dict) -> tuple[list[Scrobble], int]` — returns rows and `total_pages`
  - `mldj.scrobbles.read_scrobbles(path: Path = SCROBBLES_PATH) -> list[Scrobble]`
  - `mldj.scrobbles.IngestSummary` — frozen dataclass: `pages: int`, `written: int`, `duplicates: int`, `distinct_tracks: int`, `oldest_uts: int`, `newest_uts: int`
  - `mldj.scrobbles.ingest(client, user, to_uts, path=SCROBBLES_PATH, page_limit=200, max_pages=None) -> IngestSummary`
  - `mldj.scrobbles.SCROBBLES_PATH: Path = Path("data/scrobbles.jsonl")`
  - `mldj.scrobbles.register(subparsers) -> None`

- [ ] **Step 1: Write the fixtures**

Create `fixtures/lastfm-recenttracks-page.json` — anonymized, and including the now-playing row that must be skipped:

```json
{
  "recenttracks": {
    "@attr": { "user": "listener", "page": "1", "perPage": "200", "totalPages": "3", "total": "412" },
    "track": [
      {
        "@attr": { "nowplaying": "true" },
        "artist": { "#text": "Paper Lanterns" },
        "album": { "#text": "Quiet Rooms" },
        "name": "Ceiling Fan"
      },
      {
        "artist": { "#text": "New Order" },
        "album": { "#text": "Power, Corruption & Lies" },
        "name": "Blue Monday",
        "date": { "uts": "1759190400", "#text": "30 Sep 2025, 01:00" }
      },
      {
        "artist": { "#text": "Odell" },
        "album": { "#text": "" },
        "name": "Static Bloom",
        "date": { "uts": "1759190100", "#text": "30 Sep 2025, 00:55" }
      }
    ]
  }
}
```

Create `fixtures/lastfm-toptags.json`:

```json
{
  "toptags": {
    "@attr": { "artist": "New Order", "track": "Blue Monday" },
    "tag": [
      { "name": "new wave", "count": 100, "url": "https://example.invalid/1" },
      { "name": "synthpop", "count": 92, "url": "https://example.invalid/2" },
      { "name": "80s", "count": 71, "url": "https://example.invalid/3" },
      { "name": "dance", "count": 40, "url": "https://example.invalid/4" }
    ]
  }
}
```

- [ ] **Step 2: Write the failing client tests**

Create `tests/test_lastfm.py`:

```python
import json
from pathlib import Path

import pytest

from mldj.lastfm import LastfmClient, LastfmError, top_tags, top_tags_cached
from mldj.transport import Response

from fakes import FakeClock, FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures"
TOPTAGS = (FIXTURES / "lastfm-toptags.json").read_bytes()


def client(responses, clock=None):
    return LastfmClient(FakeTransport(responses), clock or FakeClock(), api_key="k")


def test_call_builds_a_json_request_with_the_api_key():
    c = client([Response(200, b"{}")])
    c.call("user.getRecentTracks", user="listener", limit="200")
    _, url, _ = c.transport.requests[0]
    assert url.startswith("https://ws.audioscrobbler.com/2.0/?")
    assert "method=user.getRecentTracks" in url
    assert "format=json" in url
    assert "api_key=k" in url
    assert "user=listener" in url


def test_call_paces_itself_between_requests():
    # Last.fm asks for a handful of requests per second at most; 195 pages must not burst.
    clock = FakeClock(0)
    c = client([Response(200, b"{}"), Response(200, b"{}")], clock)
    c.call("a")
    c.call("b")
    assert clock.sleeps == [250]


def test_call_raises_on_an_error_reported_inside_a_200_body():
    # Last.fm signals API errors in the body, not the HTTP status.
    body = json.dumps({"error": 6, "message": "User not found"}).encode()
    with pytest.raises(LastfmError, match="User not found"):
        client([Response(200, body)]).call("user.getRecentTracks", user="nobody")


def test_call_raises_on_a_non_200_status():
    with pytest.raises(LastfmError):
        client([Response(500, b"boom")]).call("a")


def test_call_retries_a_429_then_succeeds():
    clock = FakeClock(0)
    c = client([Response(429, b"", {"Retry-After": "2"}), Response(200, b'{"ok":1}')], clock)
    assert c.call("a") == {"ok": 1}
    assert 2000 in clock.sleeps


def test_call_gives_up_after_max_attempts():
    responses = [Response(429, b"", {"Retry-After": "1"})] * 3
    with pytest.raises(LastfmError):
        client(responses).call("a")


def test_top_tags_returns_names_with_counts_highest_first():
    assert top_tags(client([Response(200, TOPTAGS)]), "New Order", "Blue Monday") == [
        ("new wave", 100),
        ("synthpop", 92),
        ("80s", 71),
        ("dance", 40),
    ]


def test_top_tags_handles_a_track_with_no_tags():
    body = json.dumps({"toptags": {"tag": []}}).encode()
    assert top_tags(client([Response(200, body)]), "Nobody", "Nothing") == []


def test_top_tags_cached_hits_the_network_once(tmp_path):
    c = client([Response(200, TOPTAGS)])  # a second call would exhaust the script
    first = top_tags_cached(c, "New Order", "Blue Monday", cache_dir=tmp_path)
    second = top_tags_cached(c, "New Order", "Blue Monday", cache_dir=tmp_path)
    assert first == second
    assert len(c.transport.requests) == 1
```

- [ ] **Step 3: Write the failing ingest tests**

Create `tests/test_scrobbles.py`:

```python
import json
from pathlib import Path

from mldj.lastfm import LastfmClient
from mldj.scrobbles import Scrobble, ingest, parse_recent_tracks_page, read_scrobbles
from mldj.transport import Response

from fakes import FakeClock, FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAGE = json.loads((FIXTURES / "lastfm-recenttracks-page.json").read_text(encoding="utf-8"))


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


def test_parse_skips_the_now_playing_entry_which_has_no_timestamp():
    # The now-playing row would otherwise become a scrobble with no date.
    rows, total_pages = parse_recent_tracks_page(PAGE)
    assert [r.title for r in rows] == ["Blue Monday", "Static Bloom"]
    assert total_pages == 3


def test_parse_reads_artist_title_album_and_uts():
    rows, _ = parse_recent_tracks_page(PAGE)
    assert rows[0] == Scrobble(
        uts=1759190400, artist="New Order", title="Blue Monday",
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
    client = LastfmClient(transport, FakeClock(), api_key="k")
    path = tmp_path / "scrobbles.jsonl"
    summary = ingest(client, "listener", to_uts=1_000, path=path)
    assert summary.pages == 2
    assert summary.written == 2
    assert [s.title for s in read_scrobbles(path)] == ["Blue Monday", "Static Bloom"]


def test_ingest_pins_the_to_parameter_so_pages_cannot_shift(tmp_path):
    # New scrobbles arriving mid-ingest would otherwise duplicate or drop rows.
    transport = FakeTransport([Response(200, page_body([row("A", "T", 5)], 1))])
    client = LastfmClient(transport, FakeClock(), api_key="k")
    ingest(client, "listener", to_uts=999, path=tmp_path / "s.jsonl")
    _, url, _ = transport.requests[0]
    assert "to=999" in url


def test_ingest_is_idempotent_when_rerun(tmp_path):
    path = tmp_path / "s.jsonl"
    for _ in range(2):
        transport = FakeTransport([Response(200, page_body([row("A", "T", 5)], 1))])
        summary = ingest(
            LastfmClient(transport, FakeClock(), api_key="k"), "listener", 999, path=path
        )
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
    transport = FakeTransport([Response(200, page_body(tracks, 1))])
    summary = ingest(
        LastfmClient(transport, FakeClock(), api_key="k"), "listener", 999,
        path=tmp_path / "s.jsonl",
    )
    assert summary.written == 3
    assert summary.distinct_tracks == 2  # the remaster is the same song
    assert (summary.oldest_uts, summary.newest_uts) == (200, 300)


def test_ingest_respects_max_pages(tmp_path):
    transport = FakeTransport([Response(200, page_body([row("A", "T", 5)], 10))])
    summary = ingest(
        LastfmClient(transport, FakeClock(), api_key="k"), "listener", 999,
        path=tmp_path / "s.jsonl", max_pages=1,
    )
    assert summary.pages == 1
```

- [ ] **Step 4: Run both to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lastfm.py tests/test_scrobbles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.lastfm'`

- [ ] **Step 5: Write the Last.fm client**

Create `src/mldj/lastfm.py`:

```python
"""Last.fm API client.

Two gotchas shape this module. Last.fm reports API errors inside a 200 response body
rather than as an HTTP status, and a full history ingest is around 195 sequential
requests, so the client paces itself instead of bursting.
"""

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from mldj.clock import Clock
from mldj.transport import Transport, retry_after_ms

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
TAGS_DIR = Path("data/tags")  # gitignored


class LastfmError(RuntimeError):
    pass


@dataclass
class LastfmClient:
    transport: Transport
    clock: Clock
    api_key: str
    min_interval_ms: int = 250
    max_attempts: int = 3
    _last_call_ms: int = field(default=0, repr=False)

    def call(self, method: str, **params: str) -> dict:
        query = urllib.parse.urlencode(
            {"method": method, "api_key": self.api_key, "format": "json", **params}
        )
        url = f"{API_ROOT}?{query}"

        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            response = self.transport.get(url)
            self._last_call_ms = self.clock.now_ms()

            if response.status == 429:
                if attempt == self.max_attempts:
                    raise LastfmError(f"{method}: rate limited after {attempt} attempts")
                self.clock.sleep_ms(retry_after_ms(response))
                continue
            if response.status != 200:
                raise LastfmError(f"{method}: HTTP {response.status}")

            payload = response.json()
            if not isinstance(payload, dict):
                raise LastfmError(f"{method}: unreadable body")
            if "error" in payload:
                raise LastfmError(f"{method}: {payload.get('message', payload['error'])}")
            return payload

        raise LastfmError(f"{method}: exhausted attempts")

    def _pace(self) -> None:
        wait = self.min_interval_ms - (self.clock.now_ms() - self._last_call_ms)
        if self._last_call_ms and wait > 0:
            self.clock.sleep_ms(wait)


def _tag_rows(payload: dict) -> list:
    tags = (payload.get("toptags") or {}).get("tag") or []
    return tags if isinstance(tags, list) else [tags]


def top_tags(client: LastfmClient, artist: str, title: str) -> list[tuple[str, int]]:
    """Tag names with their counts, highest first. An untagged track returns []."""
    payload = client.call("track.getTopTags", artist=artist, track=title, autocorrect="1")
    rows = [
        (str(row.get("name", "")), int(row.get("count") or 0))
        for row in _tag_rows(payload)
        if isinstance(row, dict) and row.get("name")
    ]
    return sorted(rows, key=lambda pair: -pair[1])


def _cache_path(cache_dir: Path, artist: str, title: str) -> Path:
    digest = hashlib.sha1(f"{artist}\t{title}".encode()).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def top_tags_cached(
    client: LastfmClient, artist: str, title: str, cache_dir: Path = TAGS_DIR
) -> list[tuple[str, int]]:
    """Disk-cached top_tags. Tag pulls are the slow part of Task 10; cache them."""
    path = _cache_path(cache_dir, artist, title)
    if path.exists():
        return [(name, count) for name, count in json.loads(path.read_text(encoding="utf-8"))]
    tags = top_tags(client, artist, title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tags), encoding="utf-8")
    return tags
```

- [ ] **Step 6: Write the scrobble ingest**

Create `src/mldj/scrobbles.py`:

```python
"""Pull the full Last.fm listening history into data/scrobbles.jsonl.

39,000 scrobbles at 200 per page is roughly 195 sequential requests, so this is paced by
the client, resumable, and idempotent: a rerun re-reads what is already on disk and skips
duplicates, so an interrupted ingest costs nothing to restart.

`to` is pinned to the ingest's start time. Without it, scrobbles arriving mid-ingest shift
the page boundaries and rows are silently duplicated or dropped.

This file lives under data/, which is gitignored. It is personal listening data and never
enters the public repo.
"""

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from mldj.clock import SystemClock
from mldj.env import load_env, require
from mldj.lastfm import LastfmClient
from mldj.match import track_key
from mldj.transport import UrllibTransport

SCROBBLES_PATH = Path("data/scrobbles.jsonl")
PAGE_LIMIT = 200


@dataclass(frozen=True)
class Scrobble:
    uts: int
    artist: str
    title: str
    album: str


@dataclass(frozen=True)
class IngestSummary:
    pages: int
    written: int
    duplicates: int
    distinct_tracks: int
    oldest_uts: int
    newest_uts: int


def _rows(payload: dict) -> list:
    tracks = (payload.get("recenttracks") or {}).get("track") or []
    return tracks if isinstance(tracks, list) else [tracks]


def parse_recent_tracks_page(payload: dict) -> tuple[list[Scrobble], int]:
    """Parse one page into scrobbles plus the reported total page count.

    The now-playing entry carries no `date` and is skipped: it is not a scrobble yet.
    """
    attrs = (payload.get("recenttracks") or {}).get("@attr") or {}
    total_pages = int(attrs.get("totalPages") or 1)

    scrobbles: list[Scrobble] = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        if not isinstance(date, dict) or not date.get("uts"):
            continue  # now-playing
        scrobbles.append(
            Scrobble(
                uts=int(date["uts"]),
                artist=str((row.get("artist") or {}).get("#text", "")),
                title=str(row.get("name") or ""),
                album=str((row.get("album") or {}).get("#text", "")),
            )
        )
    return scrobbles, total_pages


def read_scrobbles(path: Path = SCROBBLES_PATH) -> list[Scrobble]:
    if not path.exists():
        return []
    out: list[Scrobble] = []
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                out.append(Scrobble(**json.loads(line)))
    return out


def ingest(
    client: LastfmClient,
    user: str,
    to_uts: int,
    path: Path = SCROBBLES_PATH,
    page_limit: int = PAGE_LIMIT,
    max_pages: int | None = None,
) -> IngestSummary:
    existing = read_scrobbles(path)
    seen = {(s.uts, s.artist, s.title) for s in existing}
    written = duplicates = 0
    page = 1
    total_pages = 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        while True:
            payload = client.call(
                "user.getRecentTracks",
                user=user,
                limit=str(page_limit),
                page=str(page),
                to=str(to_uts),
                extended="0",
            )
            rows, total_pages = parse_recent_tracks_page(payload)
            for scrobble in rows:
                key = (scrobble.uts, scrobble.artist, scrobble.title)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                existing.append(scrobble)
                fh.write(json.dumps(dataclasses.asdict(scrobble), separators=(",", ":")) + "\n")
                written += 1
            fh.flush()
            if page >= total_pages or (max_pages is not None and page >= max_pages):
                break
            page += 1

    # Distinct *tracks*, not scrobbles - spec open question 4. The matrix rank in Phase 1
    # depends on this number, and it is far smaller than the scrobble count.
    distinct = {track_key(s.artist, s.title) for s in existing}
    stamps = [s.uts for s in existing] or [0]
    return IngestSummary(
        pages=page,
        written=written,
        duplicates=duplicates,
        distinct_tracks=len(distinct),
        oldest_uts=min(stamps),
        newest_uts=max(stamps),
    )


def _run(args: argparse.Namespace) -> int:
    env = load_env()
    clock = SystemClock()
    client = LastfmClient(UrllibTransport(), clock, require(env, "LASTFM_API_KEY"))
    summary = ingest(
        client,
        require(env, "LASTFM_USER"),
        to_uts=clock.now_ms() // 1000,
        max_pages=args.max_pages,
    )
    print(
        f"{summary.pages} pages, {summary.written} new, {summary.duplicates} already held\n"
        f"{summary.distinct_tracks} distinct tracks "
        f"across {summary.oldest_uts}..{summary.newest_uts}"
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ingest", help="pull Last.fm history into data/scrobbles.jsonl")
    parser.add_argument("--max-pages", type=int, default=None, help="stop early, for a smoke test")
    parser.set_defaults(handler=_run)
```

Modify `src/mldj/cli.py` — `build_parser` becomes:

```python
def build_parser() -> argparse.ArgumentParser:
    from mldj import capture, scrobbles

    parser = argparse.ArgumentParser(prog="mldj", description="ml-dj Phase 0 baseline tools")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    capture.register(subparsers)
    scrobbles.register(subparsers)
    return parser
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lastfm.py tests/test_scrobbles.py -v`
Expected: PASS — 19 passed

- [ ] **Step 8: Smoke-test against the real API, then run the full ingest**

```bash
# One page first, to confirm the key and username before 195 requests.
.venv/Scripts/python.exe -m mldj ingest --max-pages 1
# Then the whole history. Expect roughly two to four minutes.
.venv/Scripts/python.exe -m mldj ingest
git status --porcelain
```

Expected: a final line reporting close to 39,000 scrobbles and the distinct-track count. **Write the distinct-track number down** — it is the first half of spec open question 4, and Phase 1's SVD rank depends on it. `git status --porcelain` must show nothing under `data/`.

- [ ] **Step 9: Lint, then commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/mldj/lastfm.py src/mldj/scrobbles.py src/mldj/cli.py
git add tests/test_lastfm.py tests/test_scrobbles.py
git add fixtures/lastfm-recenttracks-page.json fixtures/lastfm-toptags.json
git commit -m "feat: Last.fm client and resumable, idempotent scrobble ingest"
```

---
## Tasks 9-12 — the measurements

These four are specified more tersely than Tasks 1-8: interfaces, definitions, gotchas, and the test names each must have, but not full code bodies. Write the tests first from the names given, watch them fail, then implement. Everything in **Global Constraints** still applies, especially TDD and injected boundaries.

All four consume `mldj.skips.{Play, load_plays, session_files}` and `mldj.match.track_key`, and all four operate on plays whose `outcome` is `"completed"` or `"skipped"` unless a definition says otherwise. **Never let an `unknown` outcome silently become a denominator** — report the excluded count instead.

**One piece of test plumbing first.** `tests/measure/` is a second test directory, and pytest's default import mode puts only the *test file's own* directory on `sys.path` — so `from fakes import FakeClock` resolves in `tests/` but not in `tests/measure/`. Before Task 9, create `tests/conftest.py` with:

```python
"""Make tests/fakes.py importable from every test directory, including tests/measure/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

Task 10 is the only one of the four that needs a fake transport (for `build_tag_index`), but adding this once avoids a confusing `ModuleNotFoundError` later.

---

### Task 9: Novelty rate

The pitch's headline number: of the tracks the DJ played, the share never previously scrobbled.

**Files:** create `src/mldj/measure/__init__.py`, `src/mldj/measure/novelty.py`; test `tests/measure/test_novelty.py`

**Interfaces — produces:**
- `HistoryIndex` — frozen dataclass wrapping `keys: frozenset[tuple[str, str]]`, built by `build_history(scrobbles: Iterable[Scrobble]) -> HistoryIndex`, with `contains(artist: str, title: str) -> bool` applying `track_key`
- `NoveltyResult` — frozen dataclass: `plays: int`, `novel_plays: int`, `distinct_tracks: int`, `novel_tracks: int`, `excluded_unknown: int`, `play_rate: float`, `track_rate: float`, `novel_examples: list[tuple[str, str]]`
- `novelty_rate(plays: Iterable[Play], history: HistoryIndex, examples: int = 20) -> NoveltyResult`

**Definitions and decisions:**
- **Report both rates.** `play_rate` is novel plays over all plays; `track_rate` is novel distinct tracks over all distinct tracks. A DJ replaying one novel track three times must not triple-count, and the two numbers diverging is itself a finding.
- Include every `completed` and `skipped` play regardless of outcome — novelty is about what was *played*, not how it went. `unknown` plays are still played tracks, so **include them too** and only exclude non-track kinds; set `excluded_unknown` to 0 here and note in the docstring why this measure differs from Tasks 10-11.
- `novel_examples` exists to be eyeballed. A matcher bug shows up here as tracks you plainly recognise.

**Tests (names are the spec):**
`test_a_track_in_history_is_not_novel`, `test_a_track_absent_from_history_is_novel`, `test_a_remaster_matches_its_history_entry`, `test_play_rate_and_track_rate_differ_when_a_novel_track_repeats`, `test_empty_history_makes_everything_novel`, `test_no_plays_yields_zero_rates_not_a_division_error`, `test_novel_examples_are_capped`

---

### Task 10: Post-skip persistence

The "it isn't listening" claim, quantified.

**The critical design point: this metric is a contrast, not an absolute.** "23% of post-skip tracks share the skipped artist" means nothing on its own. The finding is the *difference* between what follows a skip and what follows a completion. If the DJ adapts within the session, artist persistence after a skip should be measurably **lower** than after a completion; if the two are the same, the system is not responding to the strongest signal a listener can send. Report both arms and the delta, and never report the post-skip arm alone.

**Files:** create `src/mldj/measure/persistence.py`; test `tests/measure/test_persistence.py`

**Interfaces — produces:**
- `TagIndex` — maps a track key to its top tags; `build_tag_index(client, plays, top_n=5, cache_dir=TAGS_DIR) -> TagIndex` using `mldj.lastfm.top_tags_cached`, and `TagIndex.tags(artist, title) -> frozenset[str]`
- `Arm` — frozen dataclass: `transitions: int`, `same_artist: int`, `artist_rate: float`, `mean_tag_jaccard: float`, `tagged_transitions: int`
- `PersistenceResult` — frozen dataclass: `after_skip: Arm`, `after_completion: Arm`, `artist_delta: float`, `tag_delta: float`, `excluded_unknown: int`
- `post_skip_persistence(plays: Iterable[Play], tags: TagIndex) -> PersistenceResult`

**Definitions and decisions:**
- A *transition* is an adjacent pair of plays **within one session**, in `started_at_ms` order. Never pair across sessions, and never pair across an `unknown` play — `unknown` means the record is ambiguous, so both the transition into it and out of it are excluded and counted in `excluded_unknown`.
- `artist_rate` compares `normalize_artist` of the two plays, not the raw string.
- `mean_tag_jaccard` is the mean Jaccard overlap of the two tracks' top-`n` tag sets, over transitions where **both** sides have at least one tag. `tagged_transitions` records how many that was — with thin Last.fm coverage this can be much smaller than `transitions`, and beat 6's tag-coverage honesty check needs the number.
- `artist_delta = after_completion.artist_rate - after_skip.artist_rate`. Positive means the DJ does back off after a skip; near zero is the finding the pitch claims.
- Build the tag index only over tracks that actually appear in captured sessions. That is a few hundred `track.getTopTags` calls, not a corpus-wide pull — the corpus-wide pull is Phase 1.

**Tests (names are the spec):**
`test_a_repeat_artist_after_a_skip_counts_as_persistence`, `test_a_different_artist_after_a_skip_does_not`, `test_transitions_never_span_two_sessions`, `test_a_transition_touching_an_unknown_play_is_excluded_and_counted`, `test_the_completion_arm_is_computed_separately`, `test_artist_delta_is_completion_minus_skip`, `test_tag_jaccard_ignores_transitions_where_either_side_is_untagged`, `test_tagged_transitions_reports_the_usable_denominator`, `test_no_transitions_yields_zero_rates_not_a_division_error`

---

### Task 11: Repetition

How often the DJ replays tracks already skipped in a recent window.

**This must work across sessions.** Beat 1's hook is literally "it plays something you skipped yesterday" — a within-session-only measure cannot support that claim.

**Files:** create `src/mldj/measure/repetition.py`; test `tests/measure/test_repetition.py`

**Interfaces — produces:**
- `RepetitionResult` — frozen dataclass: `plays: int`, `replays_of_skipped: int`, `within_session: int`, `cross_session: int`, `rate: float`, `examples: list[tuple[str, str, int]]` (artist, title, how many times it was skipped before this play)
- `repetition_rate(plays: Iterable[Play], window_days: int = 14) -> RepetitionResult`

**Definitions and decisions:**
- Walk plays in `started_at_ms` order, carrying a running map of `track_key -> list of skip timestamps`. A play counts as a replay-of-skipped when its key was skipped **earlier** and within `window_days`. Order matters: consult the map before recording the current play into it, or every skipped track counts as its own replay.
- Split the count into `within_session` and `cross_session` by comparing `Play.session`. The cross-session number is the one beat 1 rests on.
- `window_days` is a parameter, not a constant, because the right window is an empirical question. Report the rate at 1, 7, and 14 days in Task 12 rather than picking one.
- `unknown` plays never *count as* a skip (they may not have been one) but they are still plays and still occupy the denominator.

**Tests (names are the spec):**
`test_replaying_a_track_skipped_earlier_in_the_session_counts`, `test_replaying_a_track_skipped_in_an_earlier_session_counts_as_cross_session`, `test_a_skip_does_not_count_as_a_replay_of_itself`, `test_a_skip_older_than_the_window_does_not_count`, `test_a_completed_track_replayed_is_not_a_replay_of_a_skip`, `test_an_unknown_outcome_never_seeds_a_skip`, `test_a_remaster_replayed_matches_the_skipped_original`, `test_examples_report_the_prior_skip_count`

---

### Task 12: The report, and justifying the poll interval

Pulls Tasks 9-11 into one artifact, and closes out the poll-interval question `CLAUDE.md` insists must be settled by measurement rather than assumption.

**Files:** create `src/mldj/measure/report.py`; modify `src/mldj/cli.py` to register `report`; test `tests/measure/test_report.py`

**Interfaces — produces:**
- `Diagnostics` — frozen dataclass: `polls: int`, `gaps: int`, `rate_limited: int`, `idle: int`, `unknown_plays: int`, `unknown_reasons: dict[str, int]`, `min_track_gap_ms: int`, `p05_track_gap_ms: int`, `declared_interval_ms: int`, `interval_verdict: str`
- `diagnostics(paths: Iterable[Path]) -> Diagnostics`
- `build_report(plays, history, tags, diagnostics, window_days=(1, 7, 14)) -> dict` — the whole thing as a JSON-serialisable dict
- `render_markdown(report: dict) -> str`
- `register(subparsers) -> None` — `mldj report [--label dj] [--diagnostics-only]`

**Output:** writes `reports/phase0-<YYYY-MM-DD>.json` and `reports/phase0-<YYYY-MM-DD>.md`. `reports/` is already gitignored — the numbers go in the deck and the vault, not the public repo. The Markdown is what gets read aloud when defending beat 3.

**The poll-interval judgement.** `min_track_gap_ms` and `p05_track_gap_ms` are the observed intervals between consecutive track changes. Set `interval_verdict` from them:
- `min_track_gap_ms` at or below `2 * declared_interval_ms` → `"too slow: fast skips are being collapsed"`. Consecutive changes are landing inside the polling resolution, so multi-skip bursts are being lost and the interval must drop.
- `rate_limited > 0` → `"too fast: rate limits hit"`, with the count. 429s mean gaps, and gaps mean `unknown` plays.
- otherwise → `"adequate"`, quoting both numbers as the evidence.

That string is the justification `CLAUDE.md` asks for. Paste it into the plan's completion notes and into beat 6's honesty check.

**The report must surface its own weaknesses**, because beat 6 is graded on honesty, not on clean numbers. Include, at the top of the Markdown:
- total sessions and hours captured, and how many were `--label dj`
- `unknown_plays` as a share of all plays, broken down by reason
- `tagged_transitions` over `transitions` from Task 10 — the tag-coverage caveat, in numbers
- the matcher's stated assumption, copied from `fixtures/match-gold.json`
- the novelty `play_rate` / `track_rate` pair, never just the more flattering one

**Tests (names are the spec):**
`test_diagnostics_counts_polls_gaps_and_rate_limits`, `test_diagnostics_reports_the_declared_interval_from_session_start`, `test_verdict_flags_a_collapsed_fast_skip`, `test_verdict_flags_rate_limiting`, `test_verdict_is_adequate_when_neither_holds`, `test_build_report_is_json_serialisable`, `test_build_report_includes_both_novelty_rates`, `test_build_report_reports_unknown_plays_by_reason`, `test_render_markdown_states_the_matcher_assumption`, `test_report_writes_both_files` (use `tmp_path`, never the real `reports/`)

---

## Definition of done

Phase 0 is finished when all of the following are true:

- [ ] `pytest` passes with no network access and no test taking longer than a second
- [ ] `ruff check src tests` is clean
- [ ] At least five `--label dj` sessions are captured, totalling two hours or more, plus at least one contrast session under another label
- [ ] `data/scrobbles.jsonl` holds the full history, and the **distinct-track count is written down** (spec open question 4, first half)
- [ ] Every pair in `fixtures/match-gold.json` passes, and a sample of `novel_examples` has been read by eye without recognising anything
- [ ] `reports/phase0-<date>.md` exists and carries: novelty `play_rate` and `track_rate`, post-skip versus post-completion persistence with the delta, repetition at 1/7/14 days, and `unknown_plays` by reason
- [ ] `interval_verdict` reads `"adequate"` — or the interval has been changed and sessions recaptured at the new value
- [ ] `git status --porcelain` shows nothing under `data/` or `reports/`, and no credential has ever been staged

The report's numbers are then beat 3's evidence. Phase 1 starts from `docs/superpowers/specs/2026-09-28-ml-dj-design.md` and the distinct-track count this phase produced.

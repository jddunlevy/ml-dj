# Vector Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the beat-5 artifact — an R Shiny page that replays a captured DJ session, renders
the session vector beside the current track, and ranks what the engine would have played next with
the DJ's actual pick highlighted.

**Architecture:** Python already measures and builds; it gains two small exporters that write
derived session events and candidate pools as JSON. R reads those files and never touches the
network on the demo path. Inside R, every module but `app.R` is a pure function of its arguments,
so the engine and both plots are testable without a browser, a network, or a clock.

**Tech Stack:** R 4.5.3 (`shiny` 1.14.0, `ggplot2` 4.0.2, `jsonlite` 2.0.0, `testthat` 3.3.2,
`scales`), Python 3 (`mldj`, existing).

## Global Constraints

- **Line width: 100.** Both languages.
- **TDD, always.** Write the failing test, watch it fail, then implement. `pytest` for Python,
  `testthat` for R.
- **No test touches the network or sleeps.** Transports and clocks are injected.
- **Conventional commits** (`feat:`, `fix:`, `docs:`, `test:`), frequent and small.
- **THIS REPO IS PUBLIC.** Never `git add` anything under `data/`. `space.json` stays uncommitted.
  Committed fixtures must be anonymized.
- **Outcome vocabulary is `completed` | `skipped` | `unknown`**, matching `mldj.skips.Play`. Do not
  invent a second vocabulary; the spec's `played`/`skip` wording is superseded by this.
- **The four artist-name terms `radiohead`, `kanyewest`, `kendricklamar`, `timbaland` are excluded
  from every display surface.** These are the normalized term keys, not display names.
- **R is invoked by full path**, it is not on PATH:
  `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe"`. If `install.packages` fails with
  `SSL connect error`, set `options(download.file.method = "wininet")`.

## Departure from the spec — read this before Task 2

The spec says `source_replay.R` turns "capture JSONL → normalized events". **It does not.** Phase 0
already derives plays from raw polls, with skip detection and an `unknown` path, in
`mldj.skips.derive_plays` — tested. Re-implementing that in R would give the project two skip
detectors that can disagree, and the R one would be the untested one.

So the boundary moves: **Python derives, R consumes.** `mldj export-session` writes a derived event
list; `source_replay.R` reads it. Skip detection keeps exactly one implementation.

## File structure

| File | Responsibility |
|---|---|
| `src/mldj/export.py` | **new.** Plays → derived session events JSON, tags resolved |
| `src/mldj/candidates.py` | **new.** Candidate pool prefetch → JSON |
| `src/mldj/cli.py` | **modify.** Register `export-session` and `candidates` |
| `R/space.R` | load `space.json`, exclusions, `tag_vector`, `cosine_all`, PCA `project` |
| `R/engine.R` | `session_new`, `session_step` — decay and skip weighting. Pure |
| `R/source_replay.R` | derived session JSON → event list |
| `R/candidates.R` | load pool, `rank_candidates` |
| `R/plots.R` | `plot_reading`, `plot_constellation` — data in, ggplot out |
| `app.R` | Shiny UI and reactive wiring, thin |
| `www/theme.css` | the five `[data-theme]` palettes |
| `tests/testthat/*` | R tests |
| `fixtures/engine-trace.json` | the golden trace both engines must reproduce |
| `fixtures/session-synthetic.json` | development stand-in until a real session exists |

**Scope:** this plan covers the demo path only. Live mode (`R/source_live.R`, `httr2` polling,
OAuth, transport commands) is deferred to a follow-up plan — it is for the author's own use, is
never what gets presented, and cannot block the pitch.

---

### Task 1: R scaffolding and a test harness that runs

**Files:**
- Create: `R/.gitkeep`, `tests/testthat/helper-load.R`, `tests/testthat/test-harness.R`,
  `run-tests.R`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `run-tests.R`, the single command every later task uses to run R tests.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-harness.R`:

```r
test_that("the harness can see functions sourced from R/", {
  expect_true(exists("harness_ok"))
  expect_true(harness_ok())
})
```

Create `tests/testthat/helper-load.R` — testthat runs `helper-*.R` before any test file:

```r
# Source every module under R/ so tests see them. Shiny auto-loads R/ when the app runs;
# tests are not the app, so they load it themselves.
for (f in list.files(
  file.path(rprojroot_find(), "R"), pattern = "[.][Rr]$", full.names = TRUE
)) source(f)
```

That references a root-finder that does not exist yet, which is deliberate — Step 2 shows the
failure, Step 3 replaces it with the real thing.

- [ ] **Step 2: Run the test and watch it fail**

Create `run-tests.R`:

```r
options(download.file.method = "wininet")
testthat::test_dir("tests/testthat", stop_on_failure = TRUE)
```

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "rprojroot_find"`.

- [ ] **Step 3: Implement**

Replace `tests/testthat/helper-load.R` entirely:

```r
# Source every module under R/ so tests see them. Shiny auto-loads R/ when the app runs;
# tests are not the app, so they load it themselves. testthat sets the working directory to
# tests/testthat, so the project root is two levels up.
PROJECT_ROOT <- normalizePath(file.path("..", ".."), mustWork = TRUE)

for (f in list.files(file.path(PROJECT_ROOT, "R"), pattern = "[.][Rr]$", full.names = TRUE)) {
  source(f)
}
```

Create `R/harness.R`:

```r
#' A sentinel proving tests can see R/. Delete once another module exists.
harness_ok <- function() TRUE
```

Add to `.gitignore`:

```
.Rproj.user/
.Rhistory
.RData
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, 2 assertions.

- [ ] **Step 5: Commit**

```bash
git add R/ tests/ run-tests.R .gitignore
git commit -m "test: R test harness that sources R/ and runs under testthat"
```

---

### Task 2: `mldj export-session` — derived events for the prototype

**Files:**
- Create: `src/mldj/export.py`, `tests/test_export.py`
- Modify: `src/mldj/cli.py`

**Interfaces:**
- Consumes: `mldj.skips.load_plays`, `mldj.skips.Play`, `mldj.space.vocab.canonical_tag`,
  `mldj.lastfm.top_tags_cached`.
- Produces: `session_events(plays, tags_for) -> list[dict]` and the JSON file shape every R task
  reads:
  ```json
  {"session": "dj-20260924T101500Z", "label": "dj", "events": [
    {"ts": 1758707700000, "artist": "Beach House", "title": "Space Song",
     "tags": ["dreampop", "shoegaze"], "outcome": "skipped", "earliness": 0.93,
     "novel": true, "duration_ms": 260000, "listened_ms": 18000}]}
  ```

- [ ] **Step 1: Write the failing test**

Create `tests/test_export.py`:

```python
from mldj.export import earliness_of, session_events
from mldj.skips import Play


def _play(outcome: str, listened_ms: int, duration_ms: int = 200_000) -> Play:
    return Play(
        track_id="t1", title="Space Song", artist="Beach House",
        duration_ms=duration_ms, started_at_ms=1_000, ended_at_ms=2_000,
        listened_ms=listened_ms, outcome=outcome, session="dj-x", label="dj", reason="",
    )


def test_earliness_is_one_for_an_instant_skip():
    assert earliness_of(_play("skipped", 0)) == 1.0


def test_earliness_is_zero_for_a_completed_track():
    assert earliness_of(_play("completed", 200_000)) == 0.0


def test_earliness_scales_with_how_far_in_the_skip_landed():
    assert earliness_of(_play("skipped", 50_000)) == 0.75


def test_earliness_never_goes_negative_when_listened_exceeds_duration():
    # A track played past its reported duration must not produce a negative weight.
    assert earliness_of(_play("completed", 260_000)) == 0.0


def test_events_carry_canonical_tags_not_raw_lastfm_strings():
    events = session_events([_play("skipped", 0)], lambda a, t: ["Dream Pop", "shoe-gaze"])
    assert events[0]["tags"] == ["dreampop", "shoegaze"]


def test_unknown_outcome_survives_into_the_event():
    events = session_events([_play("unknown", 0)], lambda a, t: [])
    assert events[0]["outcome"] == "unknown"


def test_novel_is_true_when_the_track_is_absent_from_history():
    events = session_events([_play("completed", 200_000)], lambda a, t: [], was_heard=None)
    assert events[0]["novel"] is True


def test_novel_is_false_when_history_has_heard_it():
    events = session_events(
        [_play("completed", 200_000)], lambda a, t: [], was_heard=lambda a, t: True
    )
    assert events[0]["novel"] is False
```

`novel` is an **upper bound**, not a measurement — a track first heard inside the 64-day scrobble
hole (2026-07-24 to 2026-09-26) reads as never-heard. Any surface showing it says so.

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_export.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.export'`.

- [ ] **Step 3: Implement**

Create `src/mldj/export.py`:

```python
"""Derived session events, for the R prototype to replay.

R never parses raw polls and never re-implements skip detection. `skips.derive_plays` already
does that and is tested; a second implementation in another language is a second thing to be
wrong. This module is the boundary: plays in, the prototype's event shape out.

Tags are canonicalized here rather than in R, so the prototype's tag strings are the same
strings `space.json` holds and a lookup cannot silently miss.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mldj.skips import Play, load_plays
from mldj.space.vocab import canonical_tag

EXPORT_DIR = Path("data/exports")  # gitignored; derived from captured listening

TagsFor = Callable[[str, str], list[str]]
WasHeard = Callable[[str, str], bool]


def earliness_of(play: Play) -> float:
    """How early the listener bailed: 1.0 is instant, 0.0 is played through.

    A completed track is always 0.0 regardless of arithmetic - some sources report a
    listened_ms slightly under duration_ms, and that must not read as a partial rejection.
    """
    if play.outcome != "skipped":
        return 0.0
    return max(0.0, min(1.0, 1.0 - play.listened_fraction))


def session_events(
    plays: Iterable[Play], tags_for: TagsFor, was_heard: WasHeard | None = None
) -> list[dict[str, Any]]:
    """The prototype's event list, in chronological order.

    `novel` is an upper bound while the scrobble history has its 64-day hole: a track first
    heard inside it reads as never-heard. With no history supplied everything reads novel,
    which is the honest default for a caller that has not provided one.
    """
    events = []
    for play in plays:
        tags = [canonical_tag(t) for t in tags_for(play.artist, play.title)]
        heard = was_heard(play.artist, play.title) if was_heard is not None else False
        events.append(
            {
                "ts": play.started_at_ms,
                "artist": play.artist,
                "title": play.title,
                "tags": [t for t in tags if t],
                "outcome": play.outcome,
                "earliness": round(earliness_of(play), 4),
                "novel": not heard,
                "duration_ms": play.duration_ms,
                "listened_ms": play.listened_ms,
            }
        )
    return events


def write_session(path: Path, session: str, label: str, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"session": session, "label": label, "events": events}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.lastfm import LastfmClient, top_tags_cached
    from mldj.transport import UrllibTransport

    paths = sorted(Path(args.sessions).glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"no capture logs in {args.sessions} - run `mldj capture` first")

    env = load_env()
    client = LastfmClient(UrllibTransport(), SystemClock(), require(env, "LASTFM_API_KEY"))

    def tags_for(artist: str, title: str) -> list[str]:
        return [name for name, _count in top_tags_cached(client, artist, title)]

    from mldj.match import track_key
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles

    history = build_history(read_scrobbles(SCROBBLES_PATH))

    def was_heard(artist: str, title: str) -> bool:
        return track_key(artist, title) in history.keys

    for path in paths:
        plays = load_plays([path])
        events = session_events(plays, tags_for, was_heard)
        out = Path(args.out) / f"{path.stem}.json"
        label = plays[0].label if plays else "unknown"
        write_session(out, path.stem, label, events)
        skipped = sum(1 for e in events if e["outcome"] == "skipped")
        print(f"{out}: {len(events)} events, {skipped} skipped")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("export-session", help="derived session events for the prototype")
    p.add_argument("--sessions", default="data/sessions", help="directory of capture logs")
    p.add_argument("--out", default=str(EXPORT_DIR), help="where to write the JSON")
    p.set_defaults(handler=_run)
```

In `src/mldj/cli.py`, add the import and the call inside `build_parser()`:

```python
    from mldj import capture, export, scrobbles, tags   # add `export`
    ...
    export.register(subparsers)                          # add after tags.register(subparsers)
```

**`cli.py:29` dispatches on `args.handler`, not `args.func`.** A subcommand registered with
`set_defaults(func=...)` parses fine and then silently prints usage and returns 2.

- [ ] **Step 4: Run the test and watch it pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_export.py -v`

Expected: PASS, 8 tests.

Then confirm the whole suite still passes and the CLI registered:

Run: `.venv\Scripts\python.exe -m pytest -q`
Then: `.venv\Scripts\python.exe -m mldj export-session --help`

- [ ] **Step 5: Commit**

```bash
git add src/mldj/export.py src/mldj/cli.py tests/test_export.py
git commit -m "feat: mldj export-session - derived events for the R prototype"
```

---

### Task 3: A synthetic session fixture

**Files:**
- Create: `fixtures/session-synthetic.json`, `tests/testthat/test-fixture.R`

**Interfaces:**
- Produces: `fixtures/session-synthetic.json`, the development stand-in every later R task loads.
  Same shape as Task 2's output.

`data/sessions/` is empty and will be for days. This fixture is how R work proceeds meanwhile. It
is committed, so it carries **no real listening data** — the artists below are chosen to exercise
the engine, not to describe anyone's taste.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-fixture.R`:

```r
test_that("the synthetic session has the shape the prototype expects", {
  s <- jsonlite::fromJSON(
    file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"), simplifyVector = FALSE
  )
  expect_true(all(c("session", "label", "events") %in% names(s)))
  expect_gte(length(s$events), 8)

  outcomes <- vapply(s$events, function(e) e$outcome, character(1))
  expect_true(all(outcomes %in% c("completed", "skipped", "unknown")))
  expect_true(any(outcomes == "skipped"))
  expect_true(any(outcomes == "unknown"))

  for (e in s$events) {
    expect_true(is.numeric(e$earliness) && e$earliness >= 0 && e$earliness <= 1)
    expect_true(length(e$tags) > 0 || e$outcome == "unknown")
  }
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — the fixture file does not exist.

- [ ] **Step 3: Implement**

Create `fixtures/session-synthetic.json`. Tags are canonical term keys that exist in
`space.json`:

```json
{
 "session": "synthetic-20260924T101500Z",
 "label": "dj",
 "events": [
  {"ts": 1758707700000, "artist": "Artist A", "title": "Track 1",
   "tags": ["indierock", "alternative"], "outcome": "completed", "earliness": 0.0, "novel": true,
   "duration_ms": 214000, "listened_ms": 214000},
  {"ts": 1758707915000, "artist": "Artist B", "title": "Track 2",
   "tags": ["indierock", "dreampop"], "outcome": "completed", "earliness": 0.0, "novel": true,
   "duration_ms": 245000, "listened_ms": 245000},
  {"ts": 1758708161000, "artist": "Artist C", "title": "Track 3",
   "tags": ["dance", "electronic", "electropop"], "outcome": "skipped",
   "earliness": 0.97, "novel": true,
   "duration_ms": 198000, "listened_ms": 6000},
  {"ts": 1758708168000, "artist": "Artist D", "title": "Track 4",
   "tags": ["dreampop", "shoegaze"], "outcome": "completed", "earliness": 0.0, "novel": true,
   "duration_ms": 268000, "listened_ms": 268000},
  {"ts": 1758708437000, "artist": "Artist E", "title": "Track 5",
   "tags": ["hiphop", "rap"], "outcome": "skipped", "earliness": 0.91, "novel": true,
   "duration_ms": 187000, "listened_ms": 17000},
  {"ts": 1758708455000, "artist": "Artist F", "title": "Track 6",
   "tags": ["dreampop", "ethereal"], "outcome": "completed", "earliness": 0.0, "novel": true,
   "duration_ms": 231000, "listened_ms": 231000},
  {"ts": 1758708687000, "artist": "Artist G", "title": "Track 7",
   "tags": ["shoegaze", "noisepop"], "outcome": "unknown", "earliness": 0.0, "novel": true,
   "duration_ms": 0, "listened_ms": 0},
  {"ts": 1758708900000, "artist": "Artist H", "title": "Track 8",
   "tags": ["dreampop", "artpop"], "outcome": "completed", "earliness": 0.0, "novel": true,
   "duration_ms": 252000, "listened_ms": 252000}
 ]
}
```

Before committing, verify every tag exists in the real space:

```bash
.venv/Scripts/python.exe -c "
import json
space = set(json.load(open('space.json', encoding='utf-8'))['terms'])
s = json.load(open('fixtures/session-synthetic.json', encoding='utf-8'))
missing = {t for e in s['events'] for t in e['tags'] if t not in space}
print('missing from space.json:', missing or 'none')
"
```

If any tag is missing, replace it with one that exists — a fixture referencing absent terms would
make later tasks test nothing.

- [ ] **Step 4: Run the test and watch it pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fixtures/session-synthetic.json tests/testthat/test-fixture.R
git commit -m "test: synthetic session fixture, so R work proceeds before captures land"
```

---

### Task 4: `R/space.R` — loading the space, with the four terms excluded

**Files:**
- Create: `R/space.R`, `tests/testthat/test-space.R`
- Delete: `R/harness.R`, `tests/testthat/test-harness.R`

**Interfaces:**
- Produces:
  - `EXCLUDED_TERMS` — character vector of the four artist-name term keys
  - `load_space(path)` → list with `terms` (character), `display` (named character),
    `vectors` (numeric matrix, n × k), `unit` (row-normalized matrix)
  - `tag_vector(space, tags)` → numeric vector length k
  - `cosine_all(space, v)` → named numeric vector, one entry per term

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-space.R`:

```r
SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

test_that("the four artist-name terms never reach the loaded space", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored; build it with `mldj space`")
  sp <- load_space(SPACE_PATH)
  expect_false(any(c("radiohead", "kanyewest", "kendricklamar", "timbaland") %in% sp$terms))
})

test_that("the loaded space is internally consistent", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_equal(nrow(sp$vectors), length(sp$terms))
  expect_equal(nrow(sp$unit), length(sp$terms))
  expect_true(all(sp$terms %in% names(sp$display)))
})

test_that("unit rows are unit length", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  norms <- sqrt(rowSums(sp$unit^2))
  expect_true(all(abs(norms - 1) < 1e-8))
})

test_that("tag_vector sums the unit rows of the tags it recognises", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  one <- tag_vector(sp, "dreampop")
  two <- tag_vector(sp, c("dreampop", "shoegaze"))
  expect_equal(length(one), ncol(sp$vectors))
  expect_false(isTRUE(all.equal(one, two)))
})

test_that("tag_vector ignores unknown tags instead of failing", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_equal(tag_vector(sp, c("dreampop", "nosuchtag")), tag_vector(sp, "dreampop"))
})

test_that("tag_vector returns zeros when nothing is recognised", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_true(all(tag_vector(sp, c("nosuchtag", "alsonone")) == 0))
})

test_that("a tag is its own nearest term by cosine", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cos <- cosine_all(sp, tag_vector(sp, "dreampop"))
  expect_equal(names(which.max(cos)), "dreampop")
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "load_space"`.

- [ ] **Step 3: Implement**

Create `R/space.R`:

```r
#' The tag space: terms, their dense vectors, and the operations over them.
#'
#' space.json is gitignored because four of its terms are artist names carried over from the
#' corpus. They are dropped here, at load, rather than at each display site - one exclusion
#' cannot be forgotten, six can.

#' Normalized term keys, not display names. See the Phase 1 plan's privacy review.
EXCLUDED_TERMS <- c("radiohead", "kanyewest", "kendricklamar", "timbaland")

load_space <- function(path = "space.json", exclude = EXCLUDED_TERMS) {
  if (!file.exists(path)) {
    stop("no space.json at '", path, "' - build it with `mldj space`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path)

  keep <- !(raw$terms %in% exclude)
  terms <- raw$terms[keep]
  vectors <- raw$vectors[keep, , drop = FALSE]

  display <- vapply(terms, function(t) raw$display[[t]] %||% t, character(1))
  names(display) <- terms

  norms <- sqrt(rowSums(vectors^2))
  norms[norms == 0] <- 1
  unit <- vectors / norms

  rownames(vectors) <- terms
  rownames(unit) <- terms

  list(terms = terms, display = display, vectors = vectors, unit = unit, meta = raw$meta)
}

#' Sum of the unit vectors of the recognised tags. Unit-normalized before summing so a
#' six-tag track does not outweigh a two-tag one by sheer count. Unknown tags are dropped
#' rather than raised: Last.fm returns tags the vocabulary filtered out, routinely.
tag_vector <- function(space, tags) {
  known <- intersect(tags, space$terms)
  if (length(known) == 0) return(rep(0, ncol(space$vectors)))
  colSums(space$unit[known, , drop = FALSE])
}

#' Cosine of v against every term, named by term. A zero vector scores zero everywhere
#' rather than producing NaN.
cosine_all <- function(space, v) {
  n <- sqrt(sum(v^2))
  if (n == 0) return(stats::setNames(rep(0, length(space$terms)), space$terms))
  stats::setNames(as.vector(space$unit %*% (v / n)), space$terms)
}

`%||%` <- function(a, b) if (is.null(a)) b else a
```

Delete the sentinel now that a real module exists:

```bash
rm R/harness.R tests/testthat/test-harness.R
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS. If every space test reports SKIP, `space.json` is missing — build it with
`.venv\Scripts\python.exe -m mldj space` and re-run. Do not proceed on skips.

- [ ] **Step 5: Commit**

```bash
git add R/space.R tests/testthat/test-space.R
git rm R/harness.R tests/testthat/test-harness.R
git commit -m "feat: load the tag space in R, with the four artist-name terms excluded"
```

---

### Task 5: `R/engine.R` — the session vector

**Files:**
- Create: `R/engine.R`, `tests/testthat/test-engine.R`

**Interfaces:**
- Consumes: `tag_vector()` from Task 4.
- Produces:
  - `session_new(space, decay = 0.85, w = 1.0)` → state list with `v`, `space`, `decay`, `w`,
    `history` (list of events applied)
  - `session_step(state, event)` → new state. `event` is one element of the Task 2/3 event list.
  - `session_run(state, events)` → state after folding every event in order.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-engine.R`:

```r
SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

ev <- function(tags, outcome, earliness = 0) {
  list(tags = tags, outcome = outcome, earliness = earliness,
       artist = "A", title = "T", ts = 0)
}

test_that("a completed track moves the vector toward its tags", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_step(session_new(sp), ev("dreampop", "completed"))
  expect_gt(cosine_all(sp, s$v)[["dreampop"]], 0.9)
})

test_that("an early skip drives its tags negative", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_step(session_new(sp), ev("dance", "skipped", earliness = 1))
  expect_lt(cosine_all(sp, s$v)[["dance"]], -0.9)
})

test_that("earliness scales the size of the negative update", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  early <- session_step(session_new(sp), ev("dance", "skipped", earliness = 1.0))
  late  <- session_step(session_new(sp), ev("dance", "skipped", earliness = 0.2))
  expect_gt(sqrt(sum(early$v^2)), sqrt(sum(late$v^2)))
})

test_that("decay is applied once per event", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s1 <- session_step(session_new(sp, decay = 0.5), ev("dreampop", "completed"))
  s2 <- session_step(s1, ev("nosuchtag", "completed"))
  # the second event contributes nothing, so the vector is exactly the first, halved
  expect_equal(s2$v, s1$v * 0.5, tolerance = 1e-9)
})

test_that("an unknown outcome decays the vector but never updates it", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s1 <- session_step(session_new(sp, decay = 0.8), ev("dreampop", "completed"))
  s2 <- session_step(s1, ev("dance", "unknown", earliness = 1))
  expect_equal(s2$v, s1$v * 0.8, tolerance = 1e-9)
})

test_that("history records every event in order", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_run(session_new(sp), list(ev("dreampop", "completed"), ev("dance", "skipped", 1)))
  expect_equal(length(s$history), 2)
  expect_equal(s$history[[2]]$outcome, "skipped")
})

test_that("a skip after a completion pulls the vector back toward neutral", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  up   <- session_step(session_new(sp), ev("dreampop", "completed"))
  down <- session_step(up, ev("dreampop", "skipped", earliness = 1))
  expect_lt(cosine_all(sp, down$v)[["dreampop"]], cosine_all(sp, up$v)[["dreampop"]])
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "session_new"`.

- [ ] **Step 3: Implement**

Create `R/engine.R`:

```r
#' The session vector.
#'
#'   completed  v <- v*decay + w * sum(tags)
#'   skipped    v <- v*decay - w * sum(tags) * earliness
#'   unknown    v <- v*decay
#'
#' An unknown outcome decays without updating: an ambiguous record may not have been a skip,
#' so it cannot found a negative claim. Phase 0 applies the same rule to persistence and
#' repetition, and the prototype must not be more confident than the measurement was.
#'
#' Negative updates subtract the skipped track's own tag vector. The parent spec calls for
#' projecting along antonym-derived axes instead; that is Phase 2 work and it replaces exactly
#' the one line marked below. State this in beat 6 rather than hiding it.

session_new <- function(space, decay = 0.85, w = 1.0) {
  list(space = space, decay = decay, w = w,
       v = rep(0, ncol(space$vectors)), history = list())
}

session_step <- function(state, event) {
  v <- state$v * state$decay
  outcome <- event$outcome

  if (outcome == "completed") {
    v <- v + state$w * tag_vector(state$space, unlist(event$tags))
  } else if (outcome == "skipped") {
    earliness <- max(0, min(1, event$earliness %||% 1))
    # <- Phase 2 replaces this line with a projection along antonym axes
    v <- v - state$w * tag_vector(state$space, unlist(event$tags)) * earliness
  } else if (outcome != "unknown") {
    stop("unknown outcome '", outcome, "' - expected completed, skipped or unknown",
         call. = FALSE)
  }

  state$v <- v
  state$history <- c(state$history, list(event))
  state
}

session_run <- function(state, events) {
  for (e in events) state <- session_step(state, e)
  state
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, 7 engine tests.

- [ ] **Step 5: Commit**

```bash
git add R/engine.R tests/testthat/test-engine.R
git commit -m "feat: the session vector - decay, skip weighting, and the unknown rule"
```

---

### Task 6: The engine-parity golden trace

**Files:**
- Create: `fixtures/engine-trace.json`, `tests/testthat/test-parity.R`,
  `tools/build-engine-trace.R`

**Interfaces:**
- Produces: `fixtures/engine-trace.json` — the top-5 cosines at every step of the synthetic
  session. Phase 4's TypeScript engine must reproduce this file.

This is written now because now is the only moment it is free. Once two implementations exist,
whichever is written second gets tuned until it matches the first, and a bug in the first becomes
the specification.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-parity.R`:

```r
SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")
TRACE_PATH <- file.path(PROJECT_ROOT, "fixtures", "engine-trace.json")

test_that("the engine still reproduces the golden trace", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  expect_true(file.exists(TRACE_PATH))

  golden <- jsonlite::fromJSON(TRACE_PATH, simplifyVector = FALSE)
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events

  state <- session_new(sp, decay = golden$decay, w = golden$w)
  for (i in seq_along(events)) {
    state <- session_step(state, events[[i]])
    top <- head(sort(cosine_all(sp, state$v), decreasing = TRUE), 5)
    expected <- golden$steps[[i]]
    expect_equal(names(top), unlist(expected$terms),
                 info = paste("step", i, "term order changed"))
    expect_equal(unname(round(top, 6)), unlist(expected$cos),
                 tolerance = 1e-6, info = paste("step", i, "cosines changed"))
  }
})
```

This depends on `read_session()` from Task 7. Implement Task 7 first if executing strictly in
order, or accept one failing test between the two — the runner reports it clearly either way.

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `fixtures/engine-trace.json` does not exist.

- [ ] **Step 3: Implement**

Create `tools/build-engine-trace.R`:

```r
# Regenerates fixtures/engine-trace.json. Run this ONLY when the engine's behaviour is meant
# to change, and say so in the commit message - a silent regeneration turns the parity test
# into a test that the engine equals itself.
for (f in list.files("R", pattern = "[.][Rr]$", full.names = TRUE)) source(f)

DECAY <- 0.85
W <- 1.0

sp <- load_space("space.json")
events <- read_session("fixtures/session-synthetic.json")$events

state <- session_new(sp, decay = DECAY, w = W)
steps <- lapply(events, function(e) {
  state <<- session_step(state, e)
  top <- head(sort(cosine_all(sp, state$v), decreasing = TRUE), 5)
  list(terms = names(top), cos = round(unname(top), 6))
})

jsonlite::write_json(
  list(source = "fixtures/session-synthetic.json", decay = DECAY, w = W, steps = steps),
  "fixtures/engine-trace.json", auto_unbox = TRUE, digits = 8, pretty = TRUE
)
cat("wrote fixtures/engine-trace.json:", length(steps), "steps\n")
```

Run it:

```bash
"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" tools/build-engine-trace.R
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS. Then prove the test actually bites — temporarily change `decay = 0.85` to `0.5` in
`session_new`'s default, re-run, confirm the parity test FAILS, and change it back. A golden test
that cannot fail is worse than none.

- [ ] **Step 5: Commit**

```bash
git add fixtures/engine-trace.json tools/build-engine-trace.R tests/testthat/test-parity.R
git commit -m "test: golden engine trace, so Phase 4's TypeScript engine cannot drift"
```

---

### Task 7: `R/source_replay.R` — reading a derived session

**Files:**
- Create: `R/source_replay.R`, `tests/testthat/test-source-replay.R`

**Interfaces:**
- Produces: `read_session(path)` → `list(session, label, events)` where `events` is a plain list
  of event lists, each with `ts`, `artist`, `title`, `tags`, `outcome`, `earliness`.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-source-replay.R`:

```r
FIXTURE <- file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json")

test_that("a derived session reads back with its events in order", {
  s <- read_session(FIXTURE)
  expect_equal(s$label, "dj")
  expect_gte(length(s$events), 8)
  ts <- vapply(s$events, function(e) e$ts, numeric(1))
  expect_false(is.unsorted(ts))
})

test_that("tags come back as a character vector, not a nested list", {
  s <- read_session(FIXTURE)
  expect_type(s$events[[1]]$tags, "character")
})

test_that("a single-tag event does not collapse to a scalar of the wrong shape", {
  s <- read_session(FIXTURE)
  for (e in s$events) expect_true(is.character(e$tags))
})

test_that("a missing file fails loudly rather than returning empty", {
  expect_error(read_session(file.path(PROJECT_ROOT, "fixtures", "nope.json")), "no session")
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "read_session"`.

- [ ] **Step 3: Implement**

Create `R/source_replay.R`:

```r
#' The replay source: a session derived by `mldj export-session`.
#'
#' This file deliberately does no skip detection. `mldj.skips.derive_plays` already does it,
#' tested, and two implementations of one rule is one implementation too many.
#'
#' simplifyVector = FALSE keeps the events as a list of lists. With simplification on,
#' jsonlite turns a one-tag event's `tags` into a bare string and a multi-tag event's into a
#' character vector, so the same field has two shapes depending on the data - which is exactly
#' the bug that shows up only on the one track with a single tag.

read_session <- function(path) {
  if (!file.exists(path)) {
    stop("no session at '", path, "' - run `mldj export-session`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  raw$events <- lapply(raw$events, function(e) {
    e$tags <- as.character(unlist(e$tags) %||% character(0))
    e$earliness <- as.numeric(e$earliness %||% 0)
    e$ts <- as.numeric(e$ts %||% 0)
    e
  })
  raw
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, including Task 6's parity test now that `read_session` exists.

- [ ] **Step 5: Commit**

```bash
git add R/source_replay.R tests/testthat/test-source-replay.R
git commit -m "feat: replay source reads derived sessions, and derives nothing itself"
```

---

### Task 8: `R/plots.R` — the reading bars

**Files:**
- Create: `R/plots.R`, `tests/testthat/test-plots.R`

**Interfaces:**
- Produces:
  - `reading_data(space, v, n_toward = 6, n_away = 3)` → data frame with `tag`, `cos`, `sign`
  - `plot_reading(reading_df, theme = THEMES$notebook)` → ggplot object

Build the bars before the constellation. They need no projection, they are already correct, and
the spec's open question is whether the constellation earns its place at all.

**Before writing any plot code, load the `dataviz` skill.** The spec's encodings — black toward,
grey away, sign carried by value rather than hue — are decisions to validate against it, not
settled output.

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-plots.R`:

```r
SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

test_that("reading_data returns the strongest toward and away terms", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  v <- tag_vector(sp, c("dreampop", "shoegaze")) - tag_vector(sp, "dance")
  d <- reading_data(sp, v, n_toward = 4, n_away = 2)

  expect_equal(nrow(d), 6)
  expect_equal(sum(d$sign == "toward"), 4)
  expect_equal(sum(d$sign == "away"), 2)
  expect_false(is.unsorted(rev(d$cos[d$sign == "toward"])))
  expect_true(all(d$cos[d$sign == "toward"] >= d$cos[d$sign == "away"]))
})

test_that("reading_data labels with display names, never raw term keys", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, tag_vector(sp, "dreampop"), n_toward = 3, n_away = 1)
  expect_true("dream pop" %in% d$tag)
  expect_false("dreampop" %in% d$tag)
})

test_that("no excluded artist term can appear in a reading", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, tag_vector(sp, "hiphop"), n_toward = 20, n_away = 20)
  expect_false(any(tolower(gsub(" ", "", d$tag)) %in% EXCLUDED_TERMS))
})

test_that("plot_reading returns a ggplot without drawing it", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  p <- plot_reading(reading_data(sp, tag_vector(sp, "dreampop")))
  expect_s3_class(p, "ggplot")
})

test_that("a zero vector still produces a plottable frame", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, rep(0, ncol(sp$vectors)))
  expect_gt(nrow(d), 0)
  expect_true(all(d$cos == 0))
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "reading_data"`.

- [ ] **Step 3: Implement**

Create `R/plots.R`:

```r
#' The two plots. Data in, ggplot out - nothing here reads a file or a reactive.

THEMES <- list(
  notebook       = list(bg = "#f5f1e8", surface = "#ffffff", text = "#1a1a1a",
                        muted = "#666666", accent = "#000000"),
  avocado        = list(bg = "#d4e3c0", surface = "#e8efd9", text = "#2d3a1f",
                        muted = "#5a6b46", accent = "#3d5a2a"),
  sakura         = list(bg = "#fce4ec", surface = "#fdeef3", text = "#3a1f2e",
                        muted = "#7a4a60", accent = "#d9869f"),
  `blood-orange` = list(bg = "#ffb380", surface = "#ffd9b3", text = "#2a0f00",
                        muted = "#8a3a1a", accent = "#c91540"),
  `blue-bird`    = list(bg = "#bcd4e6", surface = "#d4e2ee", text = "#3a2820",
                        muted = "#7a5a48", accent = "#6e4030")
)

MONO <- "mono"

base_theme <- function(th) {
  ggplot2::theme_minimal(base_family = MONO, base_size = 11) +
    ggplot2::theme(
      plot.background  = ggplot2::element_rect(fill = th$bg, colour = NA),
      panel.background = ggplot2::element_rect(fill = th$surface, colour = th$muted,
                                               linewidth = .3),
      panel.grid.major = ggplot2::element_line(colour = scales::alpha(th$muted, .13),
                                               linewidth = .25),
      panel.grid.minor = ggplot2::element_blank(),
      plot.title    = ggplot2::element_text(colour = th$text, size = 10.5, face = "bold",
                                            hjust = 0, margin = ggplot2::margin(b = 2)),
      plot.subtitle = ggplot2::element_text(colour = th$muted, size = 8, hjust = 0,
                                            margin = ggplot2::margin(b = 9)),
      axis.text  = ggplot2::element_text(colour = th$muted, size = 7.5),
      axis.title = ggplot2::element_blank(),
      legend.position = "none",
      plot.margin = ggplot2::margin(11, 13, 9, 11)
    )
}

#' The strongest terms toward, and the strongest away. Display names, never term keys.
reading_data <- function(space, v, n_toward = 6, n_away = 3) {
  cos <- cosine_all(space, v)
  ordered <- sort(cos, decreasing = TRUE)
  toward <- head(ordered, n_toward)
  away <- rev(tail(ordered, n_away))

  data.frame(
    tag  = c(unname(space$display[names(toward)]), unname(space$display[names(away)])),
    cos  = c(unname(toward), unname(away)),
    sign = c(rep("toward", length(toward)), rep("away", length(away))),
    stringsAsFactors = FALSE
  )
}

#' Sign is carried by value, not hue: with one accent token there is no diverging scale
#' available, and this survives greyscale, all five themes, and a projector.
plot_reading <- function(reading_df, th = THEMES$notebook) {
  d <- reading_df
  d$tag <- factor(d$tag, levels = d$tag[order(d$cos)])
  d$fill <- ifelse(d$sign == "toward", th$accent, th$muted)
  lim <- max(abs(d$cos), 0.1) * 1.35

  ggplot2::ggplot(d, ggplot2::aes(cos, tag, fill = fill)) +
    ggplot2::geom_col(width = .62) +
    ggplot2::geom_vline(xintercept = 0, colour = th$muted, linewidth = .35) +
    ggplot2::geom_text(
      ggplot2::aes(label = sprintf("%+.2f", cos), hjust = ifelse(cos > 0, -0.22, 1.22)),
      family = MONO, size = 2.6, colour = th$text
    ) +
    ggplot2::scale_fill_identity() +
    ggplot2::scale_x_continuous(limits = c(-lim, lim)) +
    ggplot2::labs(title = "What the vector is pointing at",
                  subtitle = "cosine vs every tag \u00b7 grey = pushed away by a skip") +
    base_theme(th) +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_blank(),
                   axis.text.y = ggplot2::element_text(colour = th$text, size = 8.5, hjust = 1))
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, 5 plot tests.

Then look at one, because a passing test does not mean it is legible:

Create `tools/preview.R`:

```r
# Render the current plots for the synthetic session, so they can be looked at.
for (f in list.files("R", pattern = "[.][Rr]$", full.names = TRUE)) source(f)
sp <- load_space("space.json")
s <- session_run(session_new(sp), read_session("fixtures/session-synthetic.json")$events)
dir.create("preview", showWarnings = FALSE)
ggplot2::ggsave("preview/reading.png", plot_reading(reading_data(sp, s$v)),
                width = 5.4, height = 3.3, dpi = 190)
cat("wrote preview/reading.png\n")
```

Run it, and add `preview/` to `.gitignore`:

```bash
"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" tools/preview.R
```

- [ ] **Step 5: Commit**

```bash
git add R/plots.R tests/testthat/test-plots.R
git commit -m "feat: the reading bars - what the session vector is pointing at"
```

---

### Task 9: `R/plots.R` — the constellation, which must justify itself

**Files:**
- Modify: `R/plots.R`, `tests/testthat/test-plots.R`

**Interfaces:**
- Consumes: `load_space()`, `session_run()`.
- Produces:
  - `space_layout(space, n_labels = 26, min_sep = 0.095)` → data frame `term`, `tag`, `x`, `y`,
    `label` (logical)
  - `trail_data(space, layout_basis, states)` → data frame `step`, `outcome`, `x`, `y`
  - `plot_constellation(layout_df, trail_df, th)` → ggplot

The projection is computed once from the term cloud and reused, so the backdrop never moves
between frames. A backdrop that shifts as the vector moves is unreadable.

- [ ] **Step 1: Write the failing test**

Append to `tests/testthat/test-plots.R`:

```r
test_that("the layout is stable across calls", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  a <- space_layout(sp)
  b <- space_layout(sp)
  expect_equal(a$x, b$x)
  expect_equal(a$y, b$y)
})

test_that("labelled terms are separated by at least min_sep of the span", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  lay <- space_layout(sp, n_labels = 20, min_sep = 0.1)
  lab <- lay[lay$label, ]
  span <- max(diff(range(lay$x)), diff(range(lay$y)))
  d <- as.matrix(stats::dist(cbind(lab$x, lab$y)))
  diag(d) <- Inf
  expect_gte(min(d), 0.1 * span)
})

test_that("the trail has one row per state and marks skips", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events
  states <- Reduce(function(s, e) session_step(s, e), events, session_new(sp), accumulate = TRUE)
  states <- states[-1]
  tr <- trail_data(sp, space_layout(sp), states)
  expect_equal(nrow(tr), length(events))
  expect_true(any(tr$outcome == "skipped"))
})

test_that("plot_constellation returns a ggplot", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events
  states <- Reduce(function(s, e) session_step(s, e), events, session_new(sp), accumulate = TRUE)
  lay <- space_layout(sp)
  expect_s3_class(plot_constellation(lay, trail_data(sp, lay, states[-1])), "ggplot")
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "space_layout"`.

- [ ] **Step 3: Implement**

Append to `R/plots.R`:

```r
#' A fixed 2-D basis for the term cloud, computed once. Centre, then take the first two
#' principal components. The basis is cached on the space object's meta so repeated calls in a
#' reactive cannot produce a backdrop that drifts between frames.
space_basis <- local({
  cache <- new.env(parent = emptyenv())
  function(space) {
    key <- paste0(length(space$terms), "-", ncol(space$vectors))
    if (!is.null(cache[[key]])) return(cache[[key]])
    mu <- colMeans(space$vectors)
    centred <- sweep(space$vectors, 2, mu)
    sv <- svd(centred, nu = 0, nv = 2)
    basis <- list(mu = mu, P = sv$v, xy = centred %*% sv$v)
    cache[[key]] <- basis
    basis
  }
})

#' Terms in 2-D, with a greedy de-collision pass choosing which get labels. Character cells and
#' text labels both collide; picking labels by separation is cheaper and more predictable than
#' a repulsion solver, and it degrades gracefully when the space changes.
space_layout <- function(space, n_labels = 26, min_sep = 0.095) {
  b <- space_basis(space)
  xy <- b$xy
  span <- max(diff(range(xy[, 1])), diff(range(xy[, 2])))

  keep <- integer(0)
  for (i in seq_len(nrow(xy))) {
    if (length(keep) >= n_labels) break
    if (length(keep) > 0) {
      d <- sqrt((xy[i, 1] - xy[keep, 1])^2 + (xy[i, 2] - xy[keep, 2])^2)
      if (min(d) < min_sep * span) next
    }
    keep <- c(keep, i)
  }

  data.frame(
    term = space$terms, tag = unname(space$display[space$terms]),
    x = xy[, 1], y = xy[, 2],
    label = seq_len(nrow(xy)) %in% keep,
    stringsAsFactors = FALSE
  )
}

#' Project each state's vector into the same basis as the terms.
trail_data <- function(space, layout_df, states) {
  b <- space_basis(space)
  pts <- t(vapply(states, function(s) as.vector(s$v %*% b$P), numeric(2)))
  data.frame(
    step = seq_along(states),
    outcome = vapply(states, function(s) {
      h <- s$history
      if (length(h) == 0) "completed" else h[[length(h)]]$outcome
    }, character(1)),
    x = pts[, 1], y = pts[, 2],
    stringsAsFactors = FALSE
  )
}

#' The constellation. Motion lives here; truth lives in the reading. The subtitle says so,
#' because a 150-to-2 projection discards 148 dimensions and the audience cannot see that.
plot_constellation <- function(layout_df, trail_df, th = THEMES$notebook) {
  lab <- layout_df[layout_df$label, ]
  n <- nrow(trail_df)
  trail_df$alpha <- if (n > 1) seq(.3, 1, length.out = n) else 1
  cur <- trail_df[n, , drop = FALSE]
  skips <- trail_df[trail_df$outcome == "skipped", , drop = FALSE]

  ggplot2::ggplot() +
    ggplot2::geom_point(data = layout_df, ggplot2::aes(x, y), colour = th$muted,
                        size = 1.2, alpha = .5) +
    ggplot2::geom_text(data = lab, ggplot2::aes(x, y, label = tag), family = MONO,
                       size = 2.4, colour = th$muted, vjust = -1) +
    ggplot2::geom_path(data = trail_df, ggplot2::aes(x, y), colour = th$accent,
                       linewidth = .45, alpha = .4) +
    ggplot2::geom_point(data = trail_df, ggplot2::aes(x, y, alpha = alpha),
                        colour = th$accent, size = 1.9) +
    ggplot2::geom_point(data = skips, ggplot2::aes(x, y), shape = 4, colour = th$accent,
                        size = 3.6, stroke = 1.15) +
    ggplot2::geom_point(data = cur, ggplot2::aes(x, y), colour = th$accent, size = 4.2) +
    ggplot2::geom_point(data = cur, ggplot2::aes(x, y), colour = th$surface, size = 1.5) +
    ggplot2::geom_text(data = cur, ggplot2::aes(x, y, label = "now"), family = MONO,
                       size = 2.8, colour = th$accent, hjust = -0.45, fontface = "bold") +
    ggplot2::scale_alpha_identity() +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = .12)) +
    ggplot2::scale_y_continuous(expand = ggplot2::expansion(mult = .09)) +
    ggplot2::labs(title = "Session vector in tag space",
                  subtitle = paste("2-D of 150 · read the bars for what it means",
                                   "· × = skip")) +
    base_theme(th)
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS.

**Then answer the spec's open question.** Render the constellation for the synthetic session and
look at it beside the reading. If the nearest term in the bars is nowhere near `now` on the plot —
which is what happened during design — the subtitle must carry that caveat, which it does. If the
plot is too crowded or the trail too cramped to read from across a room, say so and cut it: the
bars and the candidate list carry the argument alone.

- [ ] **Step 5: Commit**

```bash
git add R/plots.R tests/testthat/test-plots.R
git commit -m "feat: the constellation, with a stable basis and a de-collision pass"
```

---

### Task 10: `mldj candidates` — the prefetched pool

**Files:**
- Create: `src/mldj/candidates.py`, `tests/test_candidates.py`
- Modify: `src/mldj/cli.py`

**Interfaces:**
- Consumes: `mldj.lastfm.LastfmClient`, `top_tags_cached`, `mldj.space.vocab.canonical_tag`.
- Produces: `candidate_pool(events, similar_for, tags_for)` → list of
  `{"artist", "title", "tags", "novel"}`, and a JSON file
  `{"session": ..., "candidates": [...]}` at `data/candidates/<session>.json`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_candidates.py`:

```python
from mldj.candidates import candidate_pool


def _events():
    return [
        {"artist": "A", "title": "1", "tags": ["dreampop"], "outcome": "completed"},
        {"artist": "B", "title": "2", "tags": ["dance"], "outcome": "skipped"},
    ]


def test_pool_excludes_tracks_already_played_in_the_session():
    similar = {"A": [("A", "1"), ("C", "3")], "B": [("B", "2")]}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert ("A", "1") not in [(c["artist"], c["title"]) for c in pool]
    assert ("B", "2") not in [(c["artist"], c["title"]) for c in pool]
    assert ("C", "3") in [(c["artist"], c["title"]) for c in pool]


def test_pool_deduplicates_tracks_reached_from_two_seeds():
    similar = {"A": [("C", "3")], "B": [("C", "3")]}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert len(pool) == 1


def test_pool_carries_canonical_tags():
    similar = {"A": [("C", "3")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["Dream Pop"])
    assert pool[0]["tags"] == ["dreampop"]


def test_a_candidate_with_no_tags_is_dropped():
    # An untagged candidate can never be scored, so it is noise in the pool.
    similar = {"A": [("C", "3")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: [])
    assert pool == []
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_candidates.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mldj.candidates'`.

- [ ] **Step 3: Implement**

Create `src/mldj/candidates.py`:

```python
"""The candidate pool, prefetched offline.

Shiny never calls Last.fm. Prefetching keeps the demo deterministic - no rate limit, no
network, no 500 during a presentation - and keeps the R dependency set small enough that the
pitch does not depend on an HTTP client in a second language.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mldj.space.vocab import canonical_tag

CANDIDATES_DIR = Path("data/candidates")  # gitignored; derived from captured listening

SimilarFor = Callable[[str], list[tuple[str, str]]]
TagsFor = Callable[[str, str], list[str]]
WasHeard = Callable[[str, str], bool]


def candidate_pool(
    events: Iterable[dict[str, Any]],
    similar_for: SimilarFor,
    tags_for: TagsFor,
    was_heard: WasHeard | None = None,
) -> list[dict[str, Any]]:
    """Tracks reachable from the session's artists, minus everything already played.

    An untagged candidate is dropped rather than kept with an empty tag list: it can never be
    scored, so keeping it only inflates the denominator of "ranked Nth of M".
    """
    played = {(e["artist"], e["title"]) for e in events}
    seen: set[tuple[str, str]] = set()
    pool: list[dict[str, Any]] = []

    for event in events:
        for artist, title in similar_for(event["artist"]):
            key = (artist, title)
            if key in played or key in seen:
                continue
            seen.add(key)
            tags = [canonical_tag(t) for t in tags_for(artist, title)]
            tags = [t for t in tags if t]
            if not tags:
                continue
            heard = was_heard(artist, title) if was_heard is not None else False
            pool.append(
                {"artist": artist, "title": title, "tags": tags, "novel": not heard}
            )
    return pool


def write_pool(path: Path, session: str, pool: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session": session, "candidates": pool}, indent=1), encoding="utf-8"
    )


def _run(args: argparse.Namespace) -> int:
    from mldj.clock import SystemClock
    from mldj.env import load_env, require
    from mldj.lastfm import LastfmClient, top_tags_cached
    from mldj.transport import UrllibTransport

    export = Path(args.session)
    if not export.exists():
        raise SystemExit(f"no export at {export} - run `mldj export-session` first")
    payload = json.loads(export.read_text(encoding="utf-8"))

    env = load_env()
    client = LastfmClient(UrllibTransport(), SystemClock(), require(env, "LASTFM_API_KEY"))

    def similar_for(artist: str) -> list[tuple[str, str]]:
        data = client.call("artist.getSimilar", artist=artist, autocorrect="1", limit="20")
        rows = ((data.get("similarartists") or {}).get("artist")) or []
        out: list[tuple[str, str]] = []
        for row in rows:
            name = str(row.get("name") or "")
            if not name:
                continue
            top = client.call("artist.getTopTracks", artist=name, autocorrect="1", limit="5")
            for t in ((top.get("toptracks") or {}).get("track")) or []:
                if t.get("name"):
                    out.append((name, str(t["name"])))
        return out

    def tags_for(artist: str, title: str) -> list[str]:
        return [name for name, _count in top_tags_cached(client, artist, title)]

    from mldj.match import track_key
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles

    history = build_history(read_scrobbles(SCROBBLES_PATH))
    pool = candidate_pool(
        payload["events"], similar_for, tags_for,
        lambda a, t: track_key(a, t) in history.keys,
    )
    out = Path(args.out) / f"{payload['session']}.json"
    write_pool(out, payload["session"], pool)
    print(f"{out}: {len(pool)} candidates")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("candidates", help="prefetch a candidate pool for a session")
    p.add_argument("--session", required=True, help="path to a `mldj export-session` JSON file")
    p.add_argument("--out", default=str(CANDIDATES_DIR))
    p.set_defaults(handler=_run)
```

In `src/mldj/cli.py`, add the import and the call inside `build_parser()`:

```python
    from mldj import candidates, capture, export, scrobbles, tags   # add `candidates`
    ...
    candidates.register(subparsers)                                  # add after export.register
```

Again: `handler=`, not `func=`.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_candidates.py -v`
Then the whole suite: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS, 4 new tests, whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mldj/candidates.py src/mldj/cli.py tests/test_candidates.py
git commit -m "feat: mldj candidates - prefetch the pool so the demo never calls last.fm"
```

---

### Task 11: `R/candidates.R` — ranking, and the DJ's actual pick

**Files:**
- Create: `R/candidates.R`, `tests/testthat/test-candidates.R`, `fixtures/candidates-synthetic.json`

**Interfaces:**
- Produces:
  - `read_candidates(path)` → list of candidates, each with `artist`, `title`, `tags`
  - `rank_candidates(space, v, candidates, actual = NULL, epsilon = 0)` → data frame `rank`,
    `artist`, `title`, `score`, `novel`, `is_actual`

`actual` is the track the DJ played next. Its row is what the pitch points at, so ranking must
return it even when it falls far outside the visible top — the whole claim is "ranked 47th".

- [ ] **Step 1: Write the failing test**

Create `tests/testthat/test-candidates.R`:

```r
SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")
CAND <- file.path(PROJECT_ROOT, "fixtures", "candidates-synthetic.json")

test_that("candidates rank by cosine against the session vector", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  v <- tag_vector(sp, c("dreampop", "shoegaze"))
  r <- rank_candidates(sp, v, read_candidates(CAND))
  expect_equal(r$rank, seq_len(nrow(r)))
  expect_false(is.unsorted(rev(r$score)))
})

test_that("the DJ's actual pick is flagged wherever it lands", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- read_candidates(CAND)
  actual <- list(artist = cands[[length(cands)]]$artist, title = cands[[length(cands)]]$title)
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)
  expect_equal(sum(r$is_actual), 1)
})

test_that("an actual pick absent from the pool flags nothing rather than erroring", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), read_candidates(CAND),
                       actual = list(artist = "Nobody", title = "Nothing"))
  expect_equal(sum(r$is_actual), 0)
})

test_that("a candidate whose tags are all unknown scores zero, not NA", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(list(artist = "X", title = "Y", tags = c("nosuchtag")))
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands)
  expect_equal(r$score[1], 0)
})

test_that("epsilon lifts a novel candidate above an identical familiar one", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "Known", title = "K", tags = "dreampop", novel = FALSE),
    list(artist = "Fresh", title = "F", tags = "dreampop", novel = TRUE)
  )
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, epsilon = 0.2)
  expect_equal(r$artist[1], "Fresh")
})

test_that("epsilon of zero ignores novelty entirely", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "Known", title = "K", tags = "dreampop", novel = FALSE),
    list(artist = "Fresh", title = "F", tags = "dreampop", novel = TRUE)
  )
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, epsilon = 0)
  expect_equal(r$score[1], r$score[2])
})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: FAIL — `could not find function "read_candidates"`.

- [ ] **Step 3: Implement**

Create `fixtures/candidates-synthetic.json`:

```json
{
 "session": "synthetic-20260924T101500Z",
 "candidates": [
  {"artist": "Artist J", "title": "Cand 1", "tags": ["dreampop", "shoegaze"], "novel": true},
  {"artist": "Artist K", "title": "Cand 2", "tags": ["dreampop", "ethereal"], "novel": false},
  {"artist": "Artist L", "title": "Cand 3", "tags": ["shoegaze", "noisepop"], "novel": true},
  {"artist": "Artist M", "title": "Cand 4", "tags": ["indierock"], "novel": false},
  {"artist": "Artist N", "title": "Cand 5", "tags": ["dance", "electropop"], "novel": true}
 ]
}
```

Create `R/candidates.R`:

```r
#' Ranking the prefetched pool against the session vector.
#'
#' The ranking returns every candidate, not a top-N. The pitch's claim is "the DJ played
#' something this engine ranked 47th", and a truncated ranking cannot make that claim - the UI
#' truncates for display, the ranking does not.

read_candidates <- function(path) {
  if (!file.exists(path)) {
    stop("no candidate pool at '", path, "' - run `mldj candidates`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  lapply(raw$candidates, function(c) {
    c$tags <- as.character(unlist(c$tags) %||% character(0))
    c$novel <- isTRUE(c$novel)
    c
  })
}

#' epsilon is the exploration knob the parent spec makes user-visible: the amount a
#' never-before-heard candidate is lifted. Novelty is an upper bound (the scrobble hole), so a
#' large epsilon amplifies a number that is already generous. Default it low.
rank_candidates <- function(space, v, candidates, actual = NULL, epsilon = 0) {
  if (length(candidates) == 0) {
    return(data.frame(rank = integer(0), artist = character(0), title = character(0),
                      score = numeric(0), novel = logical(0), is_actual = logical(0),
                      stringsAsFactors = FALSE))
  }

  nv <- sqrt(sum(v^2))
  score <- vapply(candidates, function(c) {
    cv <- tag_vector(space, c$tags)
    ncv <- sqrt(sum(cv^2))
    if (nv == 0 || ncv == 0) 0 else sum(cv * v) / (ncv * nv)
  }, numeric(1))

  novel <- vapply(candidates, function(c) isTRUE(c$novel), logical(1))

  d <- data.frame(
    artist = vapply(candidates, function(c) c$artist, character(1)),
    title  = vapply(candidates, function(c) c$title, character(1)),
    novel  = novel,
    score  = score + epsilon * novel, stringsAsFactors = FALSE
  )
  d <- d[order(-d$score), ]
  d$rank <- seq_len(nrow(d))
  d$is_actual <- if (is.null(actual)) {
    rep(FALSE, nrow(d))
  } else {
    d$artist == actual$artist & d$title == actual$title
  }
  rownames(d) <- NULL
  d[, c("rank", "artist", "title", "score", "novel", "is_actual")]
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, 6 candidate tests.

- [ ] **Step 5: Commit**

```bash
git add R/candidates.R fixtures/candidates-synthetic.json tests/testthat/test-candidates.R
git commit -m "feat: rank the candidate pool, and flag what the DJ actually played"
```

---

### Task 12: `app.R` — the page

**Files:**
- Create: `app.R`, `www/theme.css`

**Interfaces:**
- Consumes: everything above. Shiny auto-sources `R/` for an app in this directory.

- [ ] **Step 1: Write `www/theme.css`**

```css
:root, [data-theme="notebook"] {
  --bg:#f5f1e8; --surface:#fff; --text:#1a1a1a; --muted:#666; --accent:#000;
}
[data-theme="avocado"]      { --bg:#d4e3c0; --surface:#e8efd9; --text:#2d3a1f;
                              --muted:#5a6b46; --accent:#3d5a2a; }
[data-theme="sakura"]       { --bg:#fce4ec; --surface:#fdeef3; --text:#3a1f2e;
                              --muted:#7a4a60; --accent:#d9869f; }
[data-theme="blood-orange"] { --bg:#ffb380; --surface:#ffd9b3; --text:#2a0f00;
                              --muted:#8a3a1a; --accent:#c91540; }
[data-theme="blue-bird"]    { --bg:#bcd4e6; --surface:#d4e2ee; --text:#3a2820;
                              --muted:#7a5a48; --accent:#6e4030; }

body { background:var(--bg); color:var(--text);
       font-family:"JetBrains Mono", ui-monospace, monospace; font-size:13px; }
.hd { display:flex; justify-content:space-between; align-items:center;
      padding:8px 12px; background:var(--surface); border-bottom:1px solid var(--muted); }
.logo { letter-spacing:.15em; text-transform:uppercase; font-size:12px; }
.lab { font-size:9px; letter-spacing:.17em; text-transform:uppercase;
       color:var(--muted); margin:0 0 8px; }
.kv { display:flex; justify-content:space-between; font-size:10.5px;
      padding:2.5px 0; border-bottom:1px dotted var(--muted); }
.cand-row { display:grid; grid-template-columns:28px 1fr 40px; gap:6px;
            padding:3px 4px; border-bottom:1px dotted var(--muted); font-size:10.5px; }
.cand-row.hit { background:#fdf0d8; outline:1px solid #d9a441; }
.trk { font-size:14px; margin:0; }
.art { font-size:11px; color:var(--muted); margin:0 0 10px; }
```

- [ ] **Step 2: Write `app.R`**

```r
# The prototype. Shiny auto-sources R/ for an app in this directory, so the modules are
# already loaded by the time ui and server are evaluated.

SESSION_PATH <- Sys.getenv("MLDJ_SESSION", "fixtures/session-synthetic.json")
CANDS_PATH   <- Sys.getenv("MLDJ_CANDIDATES", "fixtures/candidates-synthetic.json")

space <- load_space(Sys.getenv("MLDJ_SPACE", "space.json"))
session <- read_session(SESSION_PATH)
candidates <- read_candidates(CANDS_PATH)
layout_df <- space_layout(space)

# Every prefix state, recomputed only when decay or w changes. The scrubber is then a lookup,
# not a fold over the whole session on every frame.
all_states <- function(decay, w) {
  Reduce(function(s, e) session_step(s, e), session$events,
         session_new(space, decay = decay, w = w), accumulate = TRUE)[-1]
}

ui <- shiny::fluidPage(
  shiny::tags$head(shiny::tags$link(rel = "stylesheet", href = "theme.css")),
  shiny::tags$script(shiny::HTML(
    "Shiny.addCustomMessageHandler('theme', function(t){
       document.documentElement.setAttribute('data-theme', t); });"
  )),
  shiny::div(
    class = "hd",
    shiny::div(shiny::span(class = "logo", "ml-dj"),
               shiny::span(style = "margin-left:14px;color:var(--muted);font-size:10px",
                           shiny::textOutput("ident", inline = TRUE))),
    shiny::div(
      style = "display:flex;gap:10px;align-items:center",
      shiny::numericInput("decay", "decay", 0.85, min = 0, max = 1, step = .05, width = "90px"),
      shiny::numericInput("w", "w", 1, min = 0, max = 5, step = .25, width = "70px"),
      shiny::numericInput("eps", "ε", 0, min = 0, max = 1, step = .05, width = "70px"),
      shiny::selectInput("theme", NULL, choices = names(THEMES), width = "150px")
    )
  ),
  shiny::fluidRow(
    shiny::column(
      2,
      shiny::p(class = "lab", "now playing"),
      shiny::uiOutput("track"),
      shiny::p(class = "lab", style = "margin-top:18px", "session"),
      shiny::uiOutput("stats")
    ),
    shiny::column(6, shiny::p(class = "lab", "session vector"),
                  shiny::plotOutput("constellation", height = "380px")),
    shiny::column(
      4,
      shiny::p(class = "lab", "reading"),
      shiny::plotOutput("reading", height = "260px"),
      shiny::p(class = "lab", style = "margin-top:14px", "what i'd play next"),
      shiny::uiOutput("candidates")
    )
  ),
  shiny::div(
    style = "padding:10px 14px;border-top:1px solid var(--muted);background:var(--surface)",
    shiny::sliderInput("step", NULL, min = 1, max = length(session$events), value = 1, step = 1,
                       width = "100%", animate = shiny::animationOptions(interval = 1400)),
    shiny::div(style = "font-size:9px;color:var(--muted);margin-top:4px",
               "* novelty is an upper bound: the scrobble history has a 64-day hole,",
               "2026-07-24 to 2026-09-26, and a track first heard inside it reads as new.")
  )
)

server <- function(input, output, session_) {
  th <- shiny::reactive(THEMES[[input$theme %||% "notebook"]])
  shiny::observeEvent(input$theme, {
    session_$sendCustomMessage("theme", input$theme)
  })

  states <- shiny::reactive(all_states(input$decay %||% 0.85, input$w %||% 1))
  state <- shiny::reactive(states()[[input$step]])
  event <- shiny::reactive(session$events[[input$step]])
  nxt <- shiny::reactive({
    i <- input$step + 1
    if (i > length(session$events)) NULL else session$events[[i]]
  })

  output$ident <- shiny::renderText(
    paste(session$session, "\u00b7", session$label, "\u00b7",
          input$step, "/", length(states))
  )

  output$track <- shiny::renderUI({
    e <- event()
    shiny::tagList(
      shiny::p(class = "trk", e$title),
      shiny::p(class = "art", e$artist),
      shiny::div(style = "font-size:10px;color:var(--muted)",
                 paste(e$tags, collapse = " \u00b7 "))
    )
  })

  output$stats <- shiny::renderUI({
    h <- state()$history
    outcomes <- vapply(h, function(e) e$outcome, character(1))
    row <- function(k, v) shiny::div(class = "kv", shiny::b(k), shiny::span(v))
    shiny::tagList(
      row("tracks", length(h)),
      row("skipped", sum(outcomes == "skipped")),
      row("unknown", sum(outcomes == "unknown")),
      row("novel*", paste0(sum(vapply(h, function(e) isTRUE(e$novel), logical(1))),
                           " / ", length(h)))
    )
  })

  output$constellation <- shiny::renderPlot({
    plot_constellation(layout_df,
                       trail_data(space, layout_df, states()[seq_len(input$step)]), th())
  })

  output$reading <- shiny::renderPlot(plot_reading(reading_data(space, state()$v), th()))

  output$candidates <- shiny::renderUI({
    r <- rank_candidates(space, state()$v, candidates, actual = nxt(),
                         epsilon = input$eps %||% 0)
    top <- head(r, 5)
    rows <- lapply(seq_len(nrow(top)), function(i) {
      shiny::div(class = paste("cand-row", if (top$is_actual[i]) "hit" else ""),
                 shiny::span(top$rank[i]),
                 shiny::span(paste(top$title[i], "\u2014", top$artist[i])),
                 shiny::span(sprintf("%.2f", top$score[i])))
    })
    hit <- r[r$is_actual, ]
    if (nrow(hit) == 1 && hit$rank > 5) {
      rows <- c(rows, list(
        shiny::div(style = "text-align:center;color:var(--muted);font-size:9px",
                   "· · ·"),
        shiny::div(class = "cand-row hit", shiny::span(hit$rank),
                   shiny::span(paste(hit$title, "\u2014", hit$artist)),
                   shiny::span(sprintf("%.2f", hit$score)))))
    }
    shiny::tagList(rows)
  })
}

shiny::shinyApp(ui, server)
```

- [ ] **Step 3: Run it**

```bash
"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" \
  -e "shiny::runApp('.', port = 7788, launch.browser = TRUE)"
```

Expected: the page loads on the synthetic session. Drag the scrubber and confirm all five of these,
because each is a claim the pitch makes:

1. The trail grows and the `×` marks appear on the two skipped steps.
2. The reading bars reorder, and `dance` / `hiphop` go negative after their skips.
3. The candidate ranking changes between steps, and raising ε lifts novel candidates.
4. Switching themes restyles both plots and the page together.
5. Changing `decay` re-folds the whole session — a lower value makes the trail turn faster.

- [ ] **Step 4: Confirm the test suite is still green**

Run: `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R`

Expected: PASS, everything.

- [ ] **Step 5: Commit**

```bash
git add app.R www/theme.css
git commit -m "feat: the prototype page - scrubber, both plots, and the ranked next pick"
```

---

### Task 13: Run it on a real captured session

**Files:**
- Modify: `docs/superpowers/plans/2026-09-29-phase-3-vector-prototype.md` (record what happened)

**Blocked until `data/sessions/` holds at least one `dj` capture.** Everything above runs on the
synthetic fixture; this is the task that makes it real.

- [ ] **Step 1: Export a real session**

```bash
.venv\Scripts\python.exe -m mldj export-session
.venv\Scripts\python.exe -m mldj candidates --session data/exports/<name>.json
```

- [ ] **Step 2: Confirm nothing personal has entered git**

```bash
git status --porcelain
```

Expected: **nothing** under `data/`. If anything appears, stop and fix `.gitignore` before
continuing.

- [ ] **Step 3: Run the app against it**

```bash
MLDJ_SESSION=data/exports/<name>.json MLDJ_CANDIDATES=data/candidates/<name>.json \
  "C:\Program Files\R\R-4.5.3\bin\Rscript.exe" -e "shiny::runApp('.', port = 7788)"
```

- [ ] **Step 4: Record what a real session exposed**

Write into this plan, below this task: how many events, how many carried tags at all, whether the
ranking put the DJ's actual pick low (the pitch's claim) or high (which would be a finding against
the argument and must be reported either way), and whether the constellation was legible with real
data rather than eight synthetic steps.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-09-29-phase-3-vector-prototype.md
git commit -m "docs: the prototype on a real captured session"
```

---

## Definition of done

- [ ] `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R` passes, with no test skipped
- [ ] `.venv\Scripts\python.exe -m pytest -q` passes
- [ ] `git status --porcelain` shows nothing under `data/`
- [ ] `space.json` is still uncommitted
- [ ] None of `radiohead`, `kanyewest`, `kendricklamar`, `timbaland` can appear on any surface
- [ ] `fixtures/engine-trace.json` exists, and changing the engine's decay fails the
      parity test
- [ ] The app runs on a real captured session, not only the synthetic fixture
- [ ] The spec's open question is answered in writing: does the constellation earn its place?

## Deferred to a follow-up plan

**Live mode:** `R/source_live.R`, `httr2` polling of `currently-playing`, PKCE in Shiny, and the
transport controls. It is off the demo path, needs `httr2` and `dplyr` which are not installed, and
cannot block the pitch. The spec's left-hand transport panel is part of this, so Task 12's page
shows the current track without play/pause buttons until then — the scrubber drives the demo
anyway.

**Hover-linking the bars to the constellation.** The spec asks that hovering a bar highlight its
term in the constellation. Base ggplot in Shiny cannot do it without a re-render per hover, and
`ggiraph`/`plotly` are not installed. The argument for shipping both plots does not depend on it:
the bars are readable beside the constellation without a link. Revisit only if a real session shows
the pairing is hard to follow.

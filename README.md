# ml-dj

A teardown and redesign of Spotify's AI DJ.

The DJ optimizes for familiarity, gives you no way to tell it otherwise, and narrates in a confident
voice about taste it hasn't demonstrated. `ml-dj` replaces it with a recommender that adapts to what
you skip *within the session*, makes exploration an explicit parameter instead of an emergent
property, and renders its own state on screen instead of talking about it.

The interesting part is underneath: Last.fm tags are an uncontrolled vocabulary, so `chill`,
`chillout`, `chill-out`, `mellow`, `laid back`, `lo-fi` and `lofi` are seven strings covering maybe
three meanings. Handling a skip correctly means moving *away* from a track's character — which
requires telling antonyms from synonyms in a space where both look similar. That discriminator is
the project's core.

## Status

**Phase 0 — measuring the baseline.** Capturing DJ sessions and computing novelty rate, post-skip
persistence, and repetition against a 39,000-scrobble listening history. These measurements are what
make the critique a teardown rather than an opinion.

| Phase | What | State |
|---|---|---|
| 0 | Baseline measurement of the real DJ | in progress |
| 1 | The semantic space — PPMI + SVD over the tag graph | not started |
| 2 | Antonym detection | not started |
| 3 | Session engine + replay prototype | built — see *Running the prototype* |
| 4 | Live client driving a real queue | `mldj next` writes a real queue |

## Design

`docs/superpowers/specs/2026-09-28-ml-dj-design.md` is canonical. Plans live in
`docs/superpowers/plans/`.

## Architecture

Python trains. R/Shiny serves. The boundary is a versioned `space.json`.

```
[ offline — Python ]
  last.fm scrobble history + tag pulls
      -> normalize; build tags x tracks matrix
      -> PPMI weighting + SVD -> dense tag vectors
      -> antonym detection (similarity up, co-tag down)
      -> export versioned space.json
            |
[ live — Python captures, R/Shiny renders ]
  PKCE auth - poll currently-playing - interpolate progress
      -> skip detection, with timing
      -> session vector over the loaded space
      -> POST /me/player/queue
      -> render the session vector on screen
```

Python never runs at listen time.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
cp .env.local.example .env.local
pytest
```

Needs a Spotify app (redirect URI exactly `http://127.0.0.1:8888/callback`, account must be
Premium) and a Last.fm API key.

## Running the prototype

The screen is an R/Shiny app. It needs **R 4.5.3** at `C:\Program Files\R\R-4.5.3\` (the path
`demo.ps1` looks for) and four packages:

```r
install.packages(c("shiny", "jsonlite", "ggplot2", "scales"))
```

Everything below runs from the repo root in PowerShell.

### Replay a finished session — no network, no Spotify

The quickest way to see the app, and the safe fallback if anything live goes wrong.

```powershell
.\demo.ps1 142116Z     # 17 events, 6 skips - the one with a real candidate pool
.\demo.ps1 030749Z     # 8 events, 4 skips - loud skips, no candidate pool
.\demo.ps1 150121Z     # 20 events, 4 skips - coherent reading, no candidate pool
.\demo.ps1             # synthetic fixture
```

It prints `http://127.0.0.1:7788` and opens a browser itself. Ctrl-C to stop. Pass `-Port` to move
it off 7788.

Sessions without a candidate pool still run, but "what i'd play next" falls back to the synthetic
pool — don't read it as a real recommendation for that session. `142116Z` is the one to use when the
pick has to mean something.

### Follow a live session — three terminals

This is the stage demo. **Start Spotify playing first**, then one command per terminal:

```powershell
# 1 - capture: polls currently-playing, writes events
.venv\Scripts\python.exe -m mldj capture --label demo

# 2 - live: runs the engine over what capture is writing
.venv\Scripts\python.exe -m mldj live

# 3 - the screen
.\demo.ps1 -Live
```

Then, when you want the queue write, in a fourth terminal:

```powershell
.venv\Scripts\python.exe -m mldj next --dry-run   # prints the pick, queues nothing
.venv\Scripts\python.exe -m mldj next             # writes it to Spotify
```

**Start the capture fresh.** A session carrying earlier skips has a decayed vector, and the engine
declines to queue rather than act on a dead reading — a clean session scores far higher.

**When presenting, use `mldj live --no-candidates`.** Rebuilding the pool is a few dozen serial
Last.fm round trips, so one unfamiliar artist can freeze `session.json` for minutes. The queue write
doesn't read the pool, and the app re-ranks whatever pool is already on disk against the current
vector, so nothing on screen is lost.

`demo.ps1 -Live` is only the screen. It fails fast if `data/live/session.json` is missing, and warns
if that file hasn't changed in 30 seconds — which means `mldj live` has died. `-Live` and a named
session are mutually exclusive: one follows a running capture, the other replays a finished one.

## Capture

```bash
python -m mldj capture --label dj
```

Polls currently-playing and appends events to `data/sessions/`. Run it while the AI DJ plays; stop
it with Ctrl-C. Captured data is personal and gitignored.

To make a captured session replayable: `mldj export-session` writes the derived events to
`data/exports/`, and `mldj candidates` prefetches its candidate pool into `data/candidates/`. The
replay commands above take the timestamp from those filenames.

## A note on the data

This repo is public; the listening data is not. The scrobble corpus and captured sessions stay in
`data/`, which is gitignored. Only anonymized fixtures under `fixtures/` are committed.

## Lineage

Spotify auth and polling patterns come from `cd-player`, a retro now-playing display. Same approach,
separate repo, no dependency.

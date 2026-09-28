# ml-dj

A teardown and redesign of Spotify's AI DJ. Python trains, TypeScript serves.

**Read `docs/superpowers/specs/2026-09-28-ml-dj-design.md` before doing anything.** It is the
canonical design and the source of every decision below. This file is only the operating manual.

## What this is

Two things at once, and they share a deadline:

1. **A course deliverable** — MIS 430 Individual Pitch, a 5-minute teardown of a real AI product
   plus a prototype of the redesign. The pitch is beats 1-7 in the spec.
2. **A distributional-semantics project** — a folksonomy tag space over Last.fm data, with antonym
   detection, driving a session-adaptive recommender.

The coursework lives in the vault at `C:\dev\jaxon-brain\MIS 430\`. The code lives here. The deck
is a vault deliverable, not a repo artifact.

## THIS REPO IS PUBLIC

Before every commit, assume a stranger reads it.

- Never commit: the Spotify client ID, the Last.fm API key, `.env.local`, tokens.
- Never commit: the scrobble corpus or captured session logs. They are personal listening data and
  live in `data/`, which is gitignored.
- Anonymized fixtures under `fixtures/` are committed and are the only listening data in git.
- `space.json` is derived. Commit it only if it provably contains no raw history.

If you are about to `git add` something under `data/`, stop.

## Current phase

**Phase 0 — measure the baseline.** Plan: `docs/superpowers/plans/2026-09-28-phase-0-baseline.md`

Phase 0 produces the numbers the entire pitch rests on. Beat 3 claims the DJ has an exploration
deficit and does not adapt; Phase 0 is what turns those from opinions into measurements. Nothing
else in the project depends on the recommender existing, so this comes first.

**The capture tool is the long pole.** Collecting DJ sessions takes days of real listening that
cannot be compressed by writing code faster. Tasks 1-5 of the plan exist to get capture running;
everything after that is built while sessions accumulate. Prioritize accordingly.

## Architecture

```
[ offline — Python ]   last.fm history + tags -> normalize -> PPMI + SVD
                       -> antonym detection -> versioned space.json
[ live — TypeScript ]  PKCE auth -> poll currently-playing -> skip detection
                       -> session vector -> queue writes -> render the vector
```

Python never runs at listen time. The client stays serverless and dependency-free.

**Phase 0 is all Python**, including Spotify capture. The spec's reuse table (`auth.ts`,
`spotify.ts`, `player-state.ts` from `cd-player`) applies to the Phase 4 browser client, not to
this. Standing up a second toolchain just to capture JSONL would delay the long pole for no gain.
`interpolate_progress` is reimplemented here in ~5 lines; that is cheaper than the detour.

## Conventions

- **Dependencies:** stdlib only where practical. Phase 0 needs no third-party runtime deps.
  `numpy`/`scipy` arrive in Phase 1 for PPMI + SVD. Justify anything else.
- **Tests:** `pytest`, TDD. Every network boundary takes an injected transport so tests never hit
  the wire. Same for the clock — no test sleeps.
- **Fixtures:** JSON/JSONL under `fixtures/`, anonymized, committed.
- **Commits:** conventional commits (`feat:`, `fix:`, `docs:`, `test:`), frequent and small.
- **Line width:** 100.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell:  .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.local.example .env.local   # then fill in the two credentials
pytest
```

Spotify app: reuse the existing one from `C:\Users\jaxon\Code\cd-player\.env.local`, or create a
new one at https://developer.spotify.com/dashboard. Redirect URI must be exactly
`http://127.0.0.1:8888/callback`. The account needs Premium.

Last.fm API key: https://www.last.fm/api/account/create

## Known constraints — do not rediscover these

- **Spotify audio features are gone.** Audio Features, Audio Analysis, Recommendations, and Related
  Artists are cut off for apps created after 2024-11-27 in development mode. This is why the feature
  space is the Last.fm tag graph. It is a design input, not a workaround.
- **Last.fm does not record skips.** Scrobbles fire after ~half a track or four minutes, so a skip
  is an absence. Historical skip data does not exist; it only exists live, from capture.
- **Poll granularity matters.** `cd-player` polls at 5000 ms, which collapses fast skips and
  multi-skip bursts. Phase 0 polls faster and the chosen value must be justified by measurement,
  traded against rate limits.
- **History depth is settled:** 39,000+ all-time scrobbles. What is not settled is how many
  *distinct* tracks that covers and how well Last.fm tags them.

## The one unsolved problem in Phase 0

Spotify and Last.fm identify tracks by different strings. `"Blue Monday - 2016 Remaster"` and
`"Blue Monday"` are the same track; `feat.` formatting, casing, punctuation, and remaster suffixes
all diverge. **Novelty rate is only as trustworthy as this matching**, because the whole claim is
"you had never heard this before." Task 7 of the plan handles it and carries a gold set. If the
matcher is sloppy, the headline number of the pitch is wrong in the direction that flatters the
argument, which is the worst direction.

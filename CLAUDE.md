# ml-dj

A teardown and redesign of Spotify's AI DJ. **Python trains, R shows, TypeScript serves.**

**Read `docs/superpowers/specs/2026-09-28-ml-dj-design.md` before doing anything.** It is the
canonical design and the source of every decision below. This file is only the operating manual.

For the Phase 3 prototype, read `docs/superpowers/specs/2026-09-29-vector-prototype-design.md`
too. It refines the parent spec's Phase 3 and departs from it in two named places.

## What this is

Two things at once, and they share a deadline:

1. **A course deliverable** — MIS 430 Individual Pitch, a 5-minute teardown of a real AI product
   plus a prototype of the redesign. The pitch is beats 1-7 in the spec.
2. **A distributional-semantics project** — a folksonomy tag space over Last.fm data, with antonym
   detection, driving a session-adaptive recommender.

The coursework lives in the vault at `C:\dev\jaxon-brain\MIS 430\`. The code lives here. The deck
is a vault deliverable, not a repo artifact.

## The thesis — read this before prioritizing anything

**The product claim is session adaptation: the app reads your skip and listen behavior *this
session* and gets better within it.** Not discovery. A skip is the strongest signal a listener can
send, and the DJ does nothing with it; this app moves the session vector in response and the next
pick changes. That is the pitch.

**The demo artifact is the rendered recommendation vector.** The session vector on screen *is* the
explanation for the next track — it is the fix for the "no observable system state" diagnosis and it
is what beat 5 shows. A correct recommender with nothing to look at does not demo. Treat the
visualization as a first-class deliverable with its own design work, not as a reporting layer bolted
on at the end. Spec: §5, and "the session vector is rendered on screen" in the session-engine
section.

**Novelty is supporting evidence, not the thesis.** It backs beat 3's exploration-deficit diagnosis
and becomes a user-visible knob (`ε · novelty`) in the engine. It is one input to one term. When
novelty's measurement and adaptation's measurement compete for effort, adaptation wins.

## THIS REPO IS PUBLIC

Before every commit, assume a stranger reads it.

- Never commit: the Spotify client ID, the Last.fm API key, `.env.local`, tokens.
- Never commit: the scrobble corpus or captured session logs. They are personal listening data and
  live in `data/`, which is gitignored.
- Anonymized fixtures under `fixtures/` are committed and are the only listening data in git.
- `space.json` is derived. Commit it only if it provably contains no raw history.

If you are about to `git add` something under `data/`, stop.

## Current phase

**Phase 3 — the vector prototype, in R Shiny.** Spec written and approved:
`docs/superpowers/specs/2026-09-29-vector-prototype-design.md`. Plan not yet written.

**Phase 2 is deliberately deferred behind it.** The normal order is 2 then 3, and this inverts it
for one reason: the deliverable most at risk is the demo existing and landing, and Phase 2 is the
one phase whose premise died. The prototype does not need antonymy to work — a skip subtracts the
skipped track's own tag vector, which demos correctly — and the antonym-axis version is a drop-in
replacement for a single function once Phase 2 lands. **Say this limitation in beat 6; do not hide
it.**

When Phase 2 does start, it builds the antonym discriminator and evaluates it against the gold set,
including the complementary-pair trap. **It does not start from Phase 1's Task 8 assumption**,
which is dead: low same-item co-occurrence is produced by opposition *and* by interchangeability,
so co-occurrence alone cannot tell the two apart. The Task 4 co-occurrence matrix and the recorded
level-1 baselines are still the inputs. Design first, build second.

Phase 1 is complete — `docs/superpowers/plans/2026-09-29-phase-1-semantic-space.md` — and handed
over two unfinished items, both real, both explained in its plan:

- **Level-1 evaluation fails** in all 72 sweep configurations — see the premise-inversion bullet
  under known constraints. Nothing may claim "the space works" until that is fixed or reframed.
- **`space.json` stays uncommitted** — 4 genuine artist-name leaks. Preferred fix: drop those four
  terms by name at export time and record the deletion in `meta`. Raising `min_artists` to 4 also
  clears it but costs ~70 terms.

**Phase 0 is still open and it is still the long pole — because it is what proves the thesis.**
`data/sessions/` is empty: zero DJ sessions captured, so `reports/phase0-<date>.md` does not exist.
The code has been done since `c02e33e`; what it needs is days of real listening, which no amount of
Phase 2 or Phase 3 work substitutes for. **Run `mldj capture --label dj` whenever the DJ is on.**
The prototype needs it too: its replay source has nothing to replay until a real session exists,
and a synthetic fixture is a development stand-in, not something to demo.

The number that matters most from it is **`artist_delta` — post-skip versus post-completion
persistence.** Near zero means the DJ does not respond to a skip, which is the exact deficit this
app's session adaptation fixes, and it is the before-picture the redesign is measured against. It is
also the one headline metric that owes nothing to the scrobble history. Phase 0's definition of done
wants at least five `--label dj` sessions totalling two hours, plus one contrast session under
another label. Plan: `docs/superpowers/plans/2026-09-28-phase-0-baseline.md`

## Architecture

```
[ offline — Python ]   last.fm history + tags -> normalize -> PPMI + SVD
                       -> antonym detection -> versioned space.json
                       -> capture sessions, prefetch candidate pools
[ prototype — R ]      Shiny: space.json + session + candidates
                       -> session vector -> ggplot constellation + reading
                       -> ranked "what I'd play next"          [Phase 3, the pitch]
[ live — TypeScript ]  PKCE auth -> poll currently-playing -> skip detection
                       -> session vector -> queue writes -> render the vector
                                                             [Phase 4, after the pitch]
```

Python never runs at listen time, and never at demo time either. Each language has one job:
**Python measures and builds the space, R shows it moving, TypeScript will drive a real queue.**

**Phase 0 is all Python**, including Spotify capture. The spec's reuse table (`auth.ts`,
`spotify.ts`, `player-state.ts` from `cd-player`) applies to the Phase 4 browser client, not to
this. Standing up a second toolchain just to capture JSONL would delay the long pole for no gain.
`interpolate_progress` is reimplemented here in ~5 lines; that is cheaper than the detour.

**R is the prototype only, and it does not reach the wire on the demo path.** Candidate pools are
prefetched by Python; Shiny reads JSON from disk. `httr2`/`dplyr` are needed only for live mode,
which is for your own use and is never what gets presented.

## Conventions

- **Dependencies:** stdlib only where practical. Phase 0 needs no third-party runtime deps;
  `numpy`/`scipy` came in with Phase 1 for PPMI + SVD. In R: `ggplot2`, `scales`, `shiny`,
  `jsonlite`, `testthat`, plus `httr2`/`dplyr` for live mode only. Justify anything else.
- **Tests:** `pytest` for Python, `testthat` for R. TDD either way. Every network boundary takes an
  injected transport so tests never hit the wire. Same for the clock — no test sleeps.
- **One algorithm, two languages:** the session engine will exist in R now and TypeScript in Phase
  4. `fixtures/engine-trace.json` is the golden trace both must reproduce. Write it while there is
  still only one implementation — that is the only moment it is free.
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

R (Phase 3 only) — R 4.5.3 lives at `C:\Program Files\R\R-4.5.3\bin\Rscript.exe` and is **not on
PATH**:

```bash
Rscript -e "install.packages(c('shiny','jsonlite','testthat'))"   # ggplot2, scales already present
Rscript -e "shiny::runApp('.')"
```

## Known constraints — do not rediscover these

- **Spotify audio features are gone.** Audio Features, Audio Analysis, Recommendations, and Related
  Artists are cut off for apps created after 2024-11-27 in development mode. This is why the feature
  space is the Last.fm tag graph. It is a design input, not a workaround.
- **Last.fm does not record skips.** Scrobbles fire after ~half a track or four minutes, so a skip
  is an absence. No skip data exists *in Last.fm*, historically or otherwise — it only exists live,
  from capture. **But see the next bullet: the spec reasons only from Last.fm, and Spotify's own
  export is a different source that nobody had checked.**
- **Spotify's data export may carry historical skips — verify, do not assume either way.** The
  Extended Streaming History export (account.spotify.com/privacy) records per-play `ms_played`,
  `reason_start` and `reason_end`, and `reason_end: "fwdbtn"` means the next button was pressed:
  a skip, with timing. If that holds it is a large offline-evaluation corpus for Phase 3. Two
  caveats before relying on it: the exact field set must be confirmed against a real export, and
  **the export probably does not flag which plays came from the AI DJ**. Novelty, persistence and
  repetition are all claims about *what the DJ chose*, so **capture stays necessary** regardless of
  what the export contains — and see "do not plan around the export arriving" below on timing.
- **Poll granularity matters.** `cd-player` polls at 5000 ms, which collapses fast skips and
  multi-skip bursts. Phase 0 polls faster and the chosen value must be justified by measurement,
  traded against rate limits.
- **History depth is settled, and counted:** 39,159 all-time scrobbles over **5,844 distinct
  tracks**, spanning 2021-09-05 to now (re-measured 2026-09-29). The corpus is deep rather than
  broad, about 6.7 plays per track. That retires spec open question 4 in full: Phase 1 measured the
  tagging too — **98.2% of tracks carry a vector**, at tiers `{track: 1359, album: 810, artist:
  3556, none: 106}`. Those are beat 6 numbers.
- **The scrobble hole affects novelty and nothing else — do not let it drive priorities.** A
  64-day hole, 2026-07-24 to 2026-09-26; scrobbling is reconnected and `mldj ingest` reports
  `gap_days = 0` (2026-09-29). It is bounded, so its cost is finite. It touches exactly one metric,
  and the module boundaries prove it:
  - `measure/novelty.py` is the only metric that reads scrobble history (`build_history`). A track
    first heard in the hole reads as never-heard, so novelty is an **upper bound** — report it with
    the two dates named, and never quietly drop the window from the denominator. The error flatters
    the DJ, not this project's argument, which is the safe direction.
  - `measure/persistence.py` and `measure/repetition.py` never touch it. Persistence reads the
    capture log plus Last.fm *tags*; repetition reads capture logs alone. **The adaptation claim —
    `artist_delta`, the quantified "it isn't listening" — is therefore unaffected by the hole.** The
    thesis metric is clean.
  - So: the hole is a footnote in the honesty section, not a project risk. Say it once, correctly,
    and move on. `IngestSummary.stale` (threshold 2 days) catches a *new* stoppage, which would be a
    real problem because it would corrupt the capture window itself — re-run `mldj ingest` before
    generating the report.
- **Do not plan around the Spotify export arriving.** It was requested 2026-09-29 and extended
  history can take 30 days, so it may well miss the demo. Nothing on the critical path may depend on
  it. If it lands in time it backfills the hole and upgrades novelty from upper bound to measured,
  and it is a Phase 3 offline-evaluation corpus — both are bonuses, neither is a plan.
- **Synonyms co-occur LESS than related pairs in this corpus — the spec's premise is inverted.**
  Mean jaccard: synonym 0.103, related 0.259. Tagging is *choosing* a label, not enumerating
  equivalents, so nobody tags a track both `hip-hop` and `rap`. Level 1 therefore fails in all 72
  sweep configurations (`related` 0.409 > `synonym` 0.183): a tuning problem was ruled out by
  exhaustion, not by guess. Recorded baselines for Phase 2: **antonym 0.023, complementary −0.026.**
  Do not re-run the sweep hoping for a different answer.
- **`space.json` is gitignored and must stay that way until the leaks are removed.** The privacy
  review flags 8 of 371 terms as matching a corpus artist name: 4 genuine (`radiohead`,
  `Kanye West`, `kendrick lamar`, `Timbaland`) and 4 false positives — `electronic`, `Love`, `fun`,
  `lush` are all real bands whose names are ordinary descriptive words. **Do not "fix" this by
  dropping all 8**; the four false positives are legitimate, load-bearing genre and mood terms.
- **A higher gold-set score on a smaller scorable subset is not an improvement.** Raising
  `min_count` drops the rare mood tags, which are exactly the pairs the space fails on, so
  separation appears to rise while coverage quietly falls. Any sweep or evaluation table must print
  `scored` and `missing` next to the score. This was caught once already; do not reintroduce it.

## The load-bearing join: Spotify names to Last.fm names

Spotify and Last.fm identify tracks by different strings. `"Blue Monday - 2016 Remaster"` and
`"Blue Monday"` are the same track; `feat.` formatting, casing, punctuation, and remaster suffixes
all diverge. **Novelty rate is only as trustworthy as this matching**, because the whole claim is
"you had never heard this before." If the matcher is sloppy, the headline number of the pitch is
wrong in the direction that flatters the argument, which is the worst direction.

`match.track_key` handles it and passes all 26 pairs in `fixtures/match-gold.json`. That is the
floor, not the ceiling: the gold set only proves the cases someone thought to write down. The
remaining check is human and still outstanding — read a sample of the report's `novel_examples` by
eye, and anything you actually recognise is either a match failure or a track from the 64-day hole.
Add every such case to the gold set.

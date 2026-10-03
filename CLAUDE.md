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

**The offline evaluation is a bounded addition to Phase 3, not a new phase.** Spec written and
approved 2026-10-02: `docs/superpowers/specs/2026-10-02-offline-evaluation-design.md`. Plan not
yet written — that is the next step. The Spotify export arrived and turns the adaptation claim
from *demonstrated* into *measured*: 10,114 labeled skips replay through the existing engine, and
the result is an AUC ablation — **responsive** (the engine as built) against **inert** (skips
downgraded to `unknown`). `AUC(responsive) > AUC(inert)` is the measured form of the thesis,
because both arms share the space, the decay and the completions and differ only in whether a
skip does anything. A tie means the skip arithmetic earns nothing on real data, and the pitch
would have to say so — which is the reason to run it.

It is scoped to one adapter (`streaming_history.py` emits the existing `Play` shape) plus a
measurement module, precisely so 59 MB of new data cannot absorb the days the demo needs. **The
demo existing and landing is still the deliverable at risk; this does not outrank it.**

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
Three `--label dj` sessions are captured, **1.99 of the 2.00 target hours** but 3 of 5 sessions, and
no contrast session under another label. `reports/phase0-2026-09-30.md` exists and is gitignored.
**Run `mldj capture --label dj` whenever the DJ is on** — and see the power argument below: the
reason to keep capturing has changed from filling an empty directory to buying statistical
resolution. **The poll interval is now 500 ms** (2026-10-02), because the report's verdict on the
first three captures was `"too slow"` - shortest track-change gap 1129 ms at a declared 1000 ms
interval. Those three sessions inherit that verdict unrepairably; every session from here does not.
Re-read the verdict after each capture, since 1129 ms is a minimum over sessions so far and a faster
change would reopen it.

**`artist_delta` came back +0.0000 and it is a floored probe, not a result. Do not quote it as
"the DJ does not respond to a skip".** Both arms are 0.0%, not one: across 42 adjacent pairs there
are 0 artist repeats — the 6 same-artist adjacencies are all the same track resuming after a pause
— and the skipped artist never returns within 5 tracks after a skip *or* a completion. The DJ
enforces artist rotation unconditionally, so this metric's ceiling equals its floor and it cannot
distinguish the two arms in principle. A measurement with no variance is absence of measurement,
not evidence of absence.

**The before-picture is the rotation rule itself, and it is the stronger claim.** 0 repeats in 42
pairs, 0 returns within 5 tracks, *identical* after a skip and after a completion: a fixed variety
rule whose output does not depend on which outcome preceded it is by construction not adapting. The
absence of contrast is the evidence once it is framed as a rule rather than as a delta near zero.
That needs no further capture.

Two of the three Phase 0 metrics came back null. **Repetition is 0% at 1d/7d/14d**, so beat 1's
"a track you skipped, played again" hook is unsupported — do not narrate it as observed. **Novelty
is the only one with signal:** 24.4% per play, 26.3% per track. The **tag** arm of persistence is
the only probe with room to move and it is starved — 2 of 8 post-skip and 0 of 12 post-completion
transitions had tags on both sides, so its reported `tag_delta` is arithmetic over an empty set.
Full numbers, the permutation test, and the proposed (not implemented) widening of the tag
measurement are in the plan's **Findings — 2026-09-30** section.

**The starvation is relieved, but in a different corpus — do not conflate the two.** The Spotify
export yields **7,290** skip→next pairs with tags on both sides against these 2. It does not
repair this metric, because the export cannot tell which plays came from the DJ: the capture log
measures *the DJ's* behavior and the export measures *yours*. The export answers "does the engine
score what this listener accepts", which is the Phase 3 question. It cannot answer "does the DJ
adapt", which is the Phase 0 question. Two corpora, two claims, and beat 6 keeps them apart.
Plan: `docs/superpowers/plans/2026-09-28-phase-0-baseline.md`

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
  from capture, **or from the Spotify export: see the next bullet. The parent spec reasons only
  from Last.fm and its "no historical skip data exists" conclusion is now wrong.** The scrobble
  threshold has a second consequence that is easy to miss — it silently removes always-skipped
  tracks from the corpus entirely. See "the tag gap is CAUSED by skipping" below.
- **The Spotify export DOES carry historical skips. Arrived 2026-10-02; field set confirmed.**
  It lives in `data/spotify-export/` (gitignored — every record carries `ip_addr`). Per play:
  `ts`, `ms_played`, `reason_start`, `reason_end`, `shuffle`, `skipped`, `spotify_track_uri`,
  track/artist/album names, `platform`, `conn_country`, `offline`, `incognito_mode`, `ip_addr`.
  **`skipped` is an explicit boolean the spec did not anticipate.** 63,785 plays carry a track
  URI: 36,314 `trackdone`, and **10,114 clean skips** where `reason_end == "fwdbtn"` *and*
  `skipped` — median `ms_played` 5.9 s, p10 1.2 s. **7,290 skip→next-track pairs have tags on
  both sides**, against Phase 0's 2.
  - **The two fields disagree on 8,249 plays** (2,194 `fwdbtn` but not `skipped`; 6,055 `skipped`
    but ended `endplay`). The strict intersection is the rule, and every disagreement resolves to
    `unknown`, never to `skipped` — same reasoning as `skips.py`, since an inflated skip rate
    flatters this project's own argument.
  - **It does not flag which plays came from the AI DJ** — predicted, now confirmed. There is no
    playback-context field. Novelty, persistence and repetition are claims about *what the DJ
    chose*, so **capture stays necessary** and Phase 0 is not retired by this.
  - **It carries no counterfactual.** It contains only tracks Spotify played, so it can validate
    the engine's *scoring* but never its *candidate selection*. Say that in beat 6.
  - Design: `docs/superpowers/specs/2026-10-02-offline-evaluation-design.md`.
- **Poll granularity matters.** `cd-player` polls at 5000 ms, which collapses fast skips and
  multi-skip bursts. Phase 0 polls faster and the chosen value must be justified by measurement,
  traded against rate limits.
- **History depth is settled, and counted — but say which source.** Two now exist:

  | | plays | distinct tracks | span |
  | --- | --- | --- | --- |
  | Last.fm scrobbles | 39,159 | 5,844 | 2021-09-05 → 2026-09-29 |
  | Spotify export | 63,785 | 8,497 | 2017-05-01 → 2025-12-31 |

  Last.fm is deep rather than broad, about 6.7 plays per track, and it remains **the tag corpus**:
  the space and every tag vector are built from it, and 61.9% of export tracks join to it by
  `match.track_key`. That retires spec open question 4 in full: Phase 1 measured the tagging too —
  **98.2% of Last.fm tracks carry a vector**, at tiers `{track: 1360, album: 813, artist: 3563,
  none: 108}`. Those are beat 6 numbers. Do not quote the export's 8,497 as a tagged-track count.
- **The scrobble hole affects novelty and nothing else — do not let it drive priorities.** A
  64-day hole, 2026-07-24 to 2026-09-26; scrobbling is reconnected and `mldj ingest` reports
  `gap_days = 0` (2026-09-29). It is bounded, so its cost is finite. It touches exactly one metric,
  and the module boundaries prove it:
  - `measure/novelty.py` is the only metric that reads scrobble history (`build_history`). A track
    first heard in the hole reads as never-heard, so novelty is an **upper bound** — report it with
    the two dates named, and never quietly drop the window from the denominator. The error flatters
    the DJ, not this project's argument, which is the safe direction.
  - `measure/persistence.py` and `measure/repetition.py` never touch it. Persistence reads the
    capture log plus Last.fm *tags*; repetition reads capture logs alone. **The adaptation claim is
    therefore unaffected by the hole** — whatever else is wrong with it, the hole is not it. (That
    claim now rests on the rotation rule rather than on `artist_delta`; see "Current phase". Both
    read the capture log alone, so the conclusion here is unchanged.)
  - So: the hole is a footnote in the honesty section, not a project risk. Say it once, correctly,
    and move on. `IngestSummary.stale` (threshold 2 days) catches a *new* stoppage, which would be a
    real problem because it would corrupt the capture window itself — re-run `mldj ingest` before
    generating the report.
  - **The Spotify export cannot repair it** — the export stops 2025-12-31, seven months before the
    hole opens. Do not go looking for a fix there; see the staleness bullet below.
- **The export is 272 days stale, and it does NOT backfill the scrobble hole.** It ends
  **2025-12-31**; Last.fm runs to 2026-09-29. The 64-day hole is 2026-07-24 → 2026-09-26, which is
  seven months *past the end of the export* — there are **zero** export plays inside it. An
  earlier version of this file said the export would backfill the hole and upgrade novelty from
  upper bound to measured. **That was wrong and is now retracted: novelty stays an upper bound,
  permanently as far as this deliverable is concerned.**
  - **The two corpora are complementary, neither subsumes the other.** The export adds
    2017-05-01 → 2021-09-05, which Last.fm never saw: 11,895 plays over 1,509 distinct tracks.
    Last.fm adds the final 272 days, which the export never saw. Any claim about "all-time"
    listening must name which source it came from.
  - **The offline eval therefore ends 272 days before the demo.** Acceptable for validating a
    scoring function, and it must be said rather than glossed: the eval corpus and the demo
    session are different windows, and taste drifts.
  - The filenames are offset from their contents — the file named `2026` holds Oct–Dec 2025 — so
    **a file covering 2026 may exist and may not have been downloaded.** Worth one look in the
    download folder. Nothing on the critical path depends on it.
- **The tag gap is CAUSED by skipping, and it biases the eval — conservatively.** 2,992 export
  tracks carry no tags, and only 944 of those are explained by predating Last.fm. The other 2,048
  were played in the Last.fm era and still have no tags, because **Last.fm only scrobbles past
  ~half a track: a track you always skip never scrobbles, so it never enters the corpus, so it
  has no vector.** The mechanism is visible in the rates — over Last.fm-era export plays, skip
  rate is **36.7% on untagged tracks against 18.1% on tagged ones**, and **95.5% of untagged
  tracks were never completed even once** (16.6% of tagged ones).
  - So the unscorable set is *not* missing at random; it is enriched for exactly the skips the
    eval cares about. **The direction is safe:** dropping never-completed tracks removes the
    easiest skips to predict, which lowers AUC, so any measured AUC is a **lower bound** on the
    engine's discrimination. Same safe direction as the novelty upper bound — report it the same
    way, once, with the numbers named.
  - Do not "fix" this by back-filling tags for untagged tracks from the artist tier alone without
    saying so. The missingness is informative, and hiding it would convert a lower bound into an
    unknown.
- **Synonyms co-occur LESS than related pairs in this corpus — the spec's premise is inverted.**
  Mean jaccard: synonym 0.103, related 0.259. Tagging is *choosing* a label, not enumerating
  equivalents, so nobody tags a track both `hip-hop` and `rap`. Level 1 therefore fails in all 72
  sweep configurations (`related` 0.396 > `synonym` 0.176): a tuning problem was ruled out by
  exhaustion, not by guess. Recorded baselines for Phase 2: **antonym 0.030, complementary −0.020.**
  These moved from 0.023 / −0.026 when the non-descriptive stoplist dropped 68 terms; the
  conclusion did not move, and level 1 still fails.
  Do not re-run the sweep hoping for a different answer.
- **`space.json` is gitignored and must stay that way until the leaks are removed.** The privacy
  review flags 8 of 323 terms as matching a corpus artist name: 4 genuine (`radiohead`,
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

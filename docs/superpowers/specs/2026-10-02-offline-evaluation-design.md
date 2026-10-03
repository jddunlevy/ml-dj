# Offline evaluation from the Spotify streaming-history export

**Date:** 2026-10-02
**Status:** approved
**Parent:** `2026-09-28-ml-dj-design.md` (Phase 3), `2026-09-29-vector-prototype-design.md`

## Why this exists

The Extended Streaming History export arrived on 2026-10-02. The parent spec reasons only from
Last.fm and therefore concluded that no historical skip data exists. That conclusion is now
wrong, and this spec records what the export actually contains and what it is allowed to prove.

The export is a windfall, which makes it a risk: 59 MB of new data can absorb every remaining
day while the deliverable actually at risk is the demo existing and landing. This spec is
deliberately narrow. It buys one thing — a **measured** adaptation claim in place of a
demonstrated one — and explicitly declines three others.

## What the export contains — measured, not assumed

`known constraints` in CLAUDE.md said the field set "must be confirmed against a real export."
It is confirmed. Per play: `ts`, `ms_played`, `reason_start`, `reason_end`, `shuffle`,
`skipped`, `spotify_track_uri`, track/artist/album names, `platform`, `conn_country`,
`offline`, `incognito_mode`, and `ip_addr`.

| | Last.fm | Export |
| --- | --- | --- |
| plays | 39,159 | 65,383 |
| distinct tracks | 5,844 | 8,497 |
| earliest | 2021-09-05 | 2017-05-01 |

Outcome counts over the 63,785 plays carrying a track URI:

| | count |
| --- | --- |
| `reason_end == trackdone` | 36,314 |
| `fwdbtn` **and** `skipped` | 10,114 |
| `fwdbtn` but **not** `skipped` | 2,194 |
| `skipped` but ended `endplay` | 6,055 |

Skips are decisive: median `ms_played` on a clean skip is 5.9 s, p10 is 1.2 s.

**The number that justifies the work.** Phase 0's tag arm was starved — 2 of 8 post-skip
transitions had tags on both sides, so its `tag_delta` was arithmetic over an empty set. In the
export there are **7,290 skip→next-track pairs with both sides tag-joinable**. 86.2% of clean
skips and 91.9% of completions land on a track already in the Last.fm corpus, so tags come from
the existing index with no new tag fetching.

### Three things the export is not

1. **It is stale and does not backfill the hole.** It ends 2025-12-31; there are **zero** plays
   inside the 64-day hole (2026-07-24 → 2026-09-26). Novelty stays an **upper bound** and the
   two dates stay named in the report. The filenames are offset from their contents — the file
   named `2026` holds Oct–Dec 2025 — so a file covering 2026 may exist and may not have been
   downloaded. Worth one check; nothing here depends on it.
2. **It does not flag the AI DJ.** Predicted, now confirmed: there is no playback-context field.
   Novelty, persistence and repetition are claims about *what the DJ chose*, so **capture stays
   necessary** and Phase 0 is not retired by this.
3. **It cannot prove our picks beat Spotify's.** The export contains only tracks Spotify played.
   See "What this is allowed to claim".

## Privacy

Every record carries `ip_addr`, and this repo is public. The export lives in
`data/spotify-export/`, already covered by the blanket `data/` rule in `.gitignore`. No derived
artifact may carry `ip_addr`, `conn_country`, or `platform` forward. The duration cache holds
track URIs and integers only.

## Design

### One adapter, not a new pipeline

`Play` is already the universal play shape and `export.session_events` already turns `Play`
records into engine events. So the read path gains exactly one module, and the engine, the
event shape, the R prototype and `fixtures/engine-trace.json` are all untouched.

```
export JSON ──> streaming_history.py ──> Play ──> export.session_events ──> engine
                 (the only new thing            (unchanged)            (unchanged)
                  on the read path)
```

### Outcome mapping, decided once

- `trackdone` → `completed`
- `fwdbtn` **and** `skipped == True` → `skipped`
- everything else → `unknown`

The strict intersection is the point. The two fields disagree on 8,249 plays and this resolves
every one of them to `unknown` rather than to `skipped`, mirroring `skips.py`: ambiguity is
never a skip, because an inflated skip rate flatters this project's own argument. A `fwdbtn`
with `skipped == False` is most likely the next button pressed near a track's end, which is not
the signal the thesis rests on.

### Listening runs

The export is a flat stream with no session identifier. Plays are grouped into runs by a gap
threshold between the end of one play and the start of the next; the chosen value is recorded
with the measurement rather than assumed, and the eval reports run-count sensitivity at the
threshold and at double it. A run shorter than two scorable plays contributes nothing and is
dropped from the denominator, reported.

### Durations

`Play.duration_ms` is required for `earliness` and the export does not carry it.

Durations are fetched once from `GET /v1/tracks?ids=` (50 per request, ~170 requests) through
the existing `Transport`, following `library.py`'s pattern, and cached to a gitignored file
keyed by track URI. Every later run is offline.

The fetch is cross-checked against an independent offline estimate: for a track with at least
one `trackdone` play, `max(ms_played)` over those plays approximates its duration. Measured on
the 2,084 tracks with three or more `trackdone` plays, the median relative gap between the top
two values is **0.00%** and 83% agree within 2%, so the estimate is sound enough to validate the
API numbers. It is not sufficient alone — it covers only 82.1% of clean skips, and some
`trackdone` records have `ms_played == 0`, which must be guarded against rather than divided by.
Disagreement beyond a recorded tolerance is reported, not silently reconciled.

## The evaluation

### The claim, stated so it can fail

At each position in a listening run, build the session vector `v` from the preceding events
only. Score the **actual** next track by the cosine between `v` and that track's tag vector.

> Completed next-tracks should score higher than skipped next-tracks.

Metric: **AUC** — the probability that a randomly chosen completed next-track outranks a
randomly chosen skipped one. Scale-free, and 0.5 is exactly "no signal", so the null is not a
matter of interpretation.

### The ablation is the result

The same corpus is scored twice:

| arm | skip handling |
| --- | --- |
| **responsive** | `v ← v·decay − w · tagvec · earliness` (the engine as built) |
| **inert** | skips downgraded to `unknown`: decay only, no subtraction |

**AUC(responsive) > AUC(inert) is the measured form of the thesis.** It isolates adaptation
rather than testing the tag space in general, because both arms share the same space, the same
decay, and the same completions — they differ only in whether a skip does anything.

If the two arms tie, the engine's skip arithmetic earns nothing on real data, and the pitch must
say so. That outcome is the reason the eval is worth running.

Significance by permutation test over run labels, matching Phase 0's existing methodology.

### Honesty guards, built in rather than bolted on

1. **Stratify by `shuffle`.** 45,650 plays are shuffled and 19,733 are not. Album-order
   listening makes consecutive tracks tag-similar *by construction*, so pooling the two arms
   would move AUC for a reason unrelated to the engine. Shuffled and non-shuffled AUC are
   reported separately and never averaged into one headline.
2. **`scored` and `missing` print next to every number.** 2,992 export tracks (38%) carry no
   tags and are unscorable. CLAUDE.md's existing rule — a higher score on a smaller scorable
   subset is not an improvement — applies to this table in full.
3. **Decay and `w` are swept, and the sweep prints coverage per row.** A configuration that
   wins by scoring fewer pairs has not won.

### What this is allowed to claim

It validates the engine's **scoring function**: given a session vector, the engine ranks a track
this listener will accept above one they will skip. It does **not** validate candidate
selection, because the export contains only tracks Spotify chose — there is no counterfactual in
it. Beat 6 says this plainly, next to the Phase 2 antonymy limitation it already carries.

## Components

| module | responsibility |
| --- | --- |
| `src/mldj/streaming_history.py` | parse the export, map outcomes, group runs, emit `Play` |
| `src/mldj/durations.py` | fetch and cache track durations; the `trackdone` cross-check |
| `src/mldj/measure/offline.py` | session replay, AUC, ablation, permutation test, reporting |
| CLI | `mldj durations` to populate the cache, `mldj eval-offline` to run the measurement |

Deliberately **not** done: no package reshuffle of the 21 flat modules under `src/mldj/`. It
would touch imports repo-wide for no benefit here, and unrelated refactoring is out of scope by
convention. `streaming_history.py` sits beside `scrobbles.py` because that is already the
pattern for a history source, and is named for Spotify's own term so it cannot be confused with
`export.py`, which exports *to* R.

## Testing

`pytest`, TDD, per existing convention. The duration fetch takes an injected `Transport` so no
test reaches the wire. Fixtures are a small anonymized slice of export records under
`fixtures/`, with `ip_addr` and `platform` stripped — committed, as the convention allows.

Cases that must be covered: each outcome mapping including all three disagreement shapes; a
`trackdone` record with `ms_played == 0`; a run boundary at exactly the gap threshold; a track
with no tags; a skipped play with no known duration; AUC on a hand-computed tiny example; and an
inert-arm run proving skips genuinely do nothing in it.

## Out of scope

- **Deepening the semantic space** with the 2,992 new tracks. The level-1 failure is a premise
  inversion, not a coverage problem, and CLAUDE.md says not to re-run the sweep hoping otherwise.
- **Backfilling novelty.** Impossible: the export predates the hole.
- **Phase 2 antonymy.** The inert/responsive ablation is orthogonal to it and both arms will
  re-run unchanged once the antonym projection replaces the one marked line in `engine.py`.

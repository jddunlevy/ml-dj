# The recommendation vector prototype

**Date:** 2026-09-29
**Status:** design approved, not yet planned
**Parent spec:** `docs/superpowers/specs/2026-09-28-ml-dj-design.md` — this refines its Phase 3 and
does not override it except where stated in "Departures from the parent spec".

## What this is

The beat-5 artifact: a session that visibly changes its mind. A page showing the current track with
transport controls, the session vector rendered beside it, and a ranked list of what the engine
would play next — with the track the DJ actually played next highlighted in that list.

It exists to make one claim visible. **The product thesis is session adaptation**: the app reads
skip and listen behaviour *within a session* and its next pick changes in response. The DJ does not
do this. The vector is the observable system state whose absence is beat 3's third diagnosis.

Novelty is not the thesis here. It appears as one term in the ranking (`ε · novelty`) and as a
session statistic, nothing more.

## Departures from the parent spec

Two, both deliberate.

1. **The prototype is R Shiny, not TypeScript.** The parent spec's `[live — TypeScript]` lane and
   the `cd-player` reuse table now describe **Phase 4**, the post-pitch live client, which is
   unchanged. Phase 3 is R. The reason is throughput under a deadline: the author is fluent in R,
   `ggplot2` produces publication-clean output with no chart library to build, and `space.json` is
   a language-neutral handoff. The repo's one-line identity becomes **"Python trains, R shows,
   TypeScript serves."**
2. **The page sends transport commands.** The parent spec's "Not a Spotify client" line rules out
   in-browser audio, not remote control. Audio stays in whatever Spotify app is running; this page
   issues pause/next via the Web API under the `user-modify-playback-state` scope the parent spec
   already grants. No Web Playback SDK.

## Architecture

```
OFFLINE — Python, existing and unchanged
  last.fm history + tags  → PPMI + SVD → space.json            [Phase 1, done]
  mldj capture            → data/sessions/*.jsonl              [Phase 0, in progress]
  mldj candidates         → data/candidates/<session>.json     [new, small]

PROTOTYPE — R Shiny
  space.json ──┐
  session ─────┼→ SessionSource → SessionEngine → { vector, ranking }
  candidates ──┘                        │
                                        ▼
        TrackPanel │ Constellation │ Reading │ Candidates │ Scrubber
```

Python never runs at demo time, exactly as it never runs at listen time.

### Modules

| File | Responsibility | Pure |
|---|---|---|
| `R/space.R` | load `space.json`; `tag_vector()`, `cosine_all()`, `project()` | yes |
| `R/engine.R` | `session_new()`, `session_step(state, event)` — decay, skip weighting | **yes** |
| `R/source_replay.R` | capture JSONL → normalized events | yes, given a file |
| `R/source_live.R` | poll currently-playing, detect skips, send transport | injected transport |
| `R/candidates.R` | load the prefetched pool; `rank(pool, vector)` | yes |
| `R/plots.R` | `plot_constellation()`, `plot_reading()` — data in, ggplot out | yes |
| `app.R` | Shiny UI and reactive wiring, thin | — |

Everything except `app.R` and `source_live.R` is a pure function of its arguments, so the whole
engine and both plots are testable without a browser, a network, or a clock.

### The event contract — the load-bearing boundary

Both sources emit the same shape:

```
{ ts, artist, title, tags[], outcome: played|skip|unknown, earliness: 0..1 }
```

`session_step()` cannot tell replay from live. That is what makes the replay a genuine rehearsal of
the live path rather than a mock, and it is why the demo can run offline without the demo being a
different program from the one being demonstrated.

`earliness` is `1 - (progress_at_change / duration)`, clamped to `[0, 1]`: 1.0 is an instant skip,
0.0 is a track that finished. An `unknown` outcome never updates the vector — ambiguous records are
not evidence, matching the rule Phase 0 already applies to persistence and repetition.

## The engine

```
v ← 0
per event:
    played   v ← v·decay + w · Σ tags(track)
    skip     v ← v·decay − w · Σ tags(track) · earliness
    unknown  v ← v·decay

ranking(candidate) = cos(tags(candidate), v)  +  ε · novelty  −  recency_penalty
```

`decay = 0.85` per pick and `w = 1.0` are the starting values, exposed in the UI so they can be
moved during the demo. They are not yet chosen by measurement; Phase 3's evaluation does that.

Tag vectors are unit-normalized before summing, so a track carrying six tags does not outweigh one
carrying two by sheer count.

**Negative updates are naive in v1**: a skip subtracts the track's own tag vector. The parent spec
calls for projecting along antonym-derived axes instead, which is Phase 2 work and Phase 2's
premise died in Phase 1 (see `docs/superpowers/plans/2026-09-29-phase-1-semantic-space.md`). The
naive form demos correctly and the axis-projection form is a drop-in replacement for one function.
**This limitation is stated in beat 6, not hidden.**

## The two plots, and why both must ship

**Constellation** — all terms projected to a fixed 2-D PCA basis computed once, offline, from the
term matrix. The session vector is a point with a fading trail; skips are marked `×`. This is what
makes adaptation over *time* legible.

**Reading** — cosine of the vector against all 371 terms, as horizontal bars: strongest few, and
the few most pushed away. Black toward, grey away.

They ship together because **the projection lies and the bars do not.** In the first real render
against `space.json`, the vector's nearest term by cosine was `dream pop` at **+0.75** while the
projected point sat visibly far from `dream pop` on screen — correct in both cases, because the
projection discards 148 of 150 dimensions. The constellation alone would contradict the
recommender in front of the audience. The bars are the citable truth; the constellation is the
motion. Hovering a bar highlights its term in the constellation.

## Design language

Adopted from `ascii-editor` (`C:\Users\jaxon\Code\ascii-editor`), which is the author's existing
system:

- Five themes via `[data-theme]`, five tokens each: `--bg --surface --text --muted --accent`.
  `notebook` (`#f5f1e8` paper) is the default and what the plots are designed against.
- JetBrains Mono throughout.
- **Sign is encoded by value, not hue** — black for toward, grey for away, plus an explicit `+`/`−`.
  With only one accent token there is no diverging colour scale available, and this survives
  greyscale, all five themes, and a projector that mangles colour.

Load the `dataviz` skill before writing plot code. It was deliberately not consulted during
brainstorming, so the encodings above are decisions to validate, not settled output.

## Layout

Three columns under a header, over a scrubber.

- **Header** — `ml-dj`, a visible `replay | live` source toggle, session identity, theme picker.
- **Left** — now playing, progress, transport (`|<` `||` `>|`), session statistics, current tags.
- **Centre** — the constellation.
- **Right** — the reading bars, then "what I'd play next", with the DJ's actual next pick
  highlighted.
- **Footer** — a timeline scrubber; one pip per pick, filled pips are skips, with step and play.

Three choices worth defending:

1. **The scrubber is the demo instrument.** Real-time playback cannot be paused on the interesting
   moment or rewound when someone asks a question. Filled pips let the presenter jump straight to a
   skip and show the vector turning.
2. **The candidate list carries the argument.** The vector explains *why*; the highlighted row is
   the *claim* — the DJ played something this engine ranked 47th.
3. **`replay | live` is on screen, not a build flag.** It makes the determinism claim legible rather
   than hidden, and it is the same engine either way.

## Candidate pools

Prefetched offline by a new `mldj candidates` subcommand, reusing the existing `lastfm.py` client
and tag cache: `artist.getSimilar`, `tag.getTopTracks`, `track.getSimilar`, minus everything already
played in the session. Written as JSON per session.

Shiny never calls Last.fm. This keeps the demo deterministic, keeps the R dependency set small, and
means `httr2` and `dplyr` are needed only for live mode — not for the pitch.

## Testing

`testthat`, mirroring the repo's existing discipline: TDD, injected transports, no sleeping tests.

- `engine.R` — unit tests per rule: decay applied per pick, a skip subtracts, `earliness` scales the
  subtraction, `unknown` decays without updating.
- **Engine-parity fixture.** A fixed synthetic session produces `fixtures/engine-trace.json`: the
  vector's top-5 cosines at every step. The R tests assert against it, and Phase 4's TypeScript
  engine must assert against the same file. This is what keeps two implementations of one algorithm
  from drifting, and it is written now, while there is only one.
- `source_replay.R` — a committed anonymized capture fixture in, expected events out.
- `source_live.R` — injected transport; skip detection tested against recorded poll sequences,
  including the multi-skip burst that a slow poll interval collapses.
- `plots.R` — tested on the data frames they build, not on rendered pixels.

## Risks and dependencies

1. **The replay source has nothing to replay.** `data/sessions/` is empty. Development proceeds
   against a synthetic session fixture, but **the demo needs one real captured DJ session**,
   which keeps `mldj capture` on the critical path. This is the same long pole Phase 0 has.
2. ~~**R package installs are unverified.**~~ **RESOLVED 2026-09-29.** Installed and smoke-tested
   on R 4.5.3: `shiny` 1.14.0, `jsonlite` 2.0.0, `testthat` 3.3.2, alongside `ggplot2` 4.0.2 and
   `scales`. `jsonlite::fromJSON` parses `space.json` in **0.08 s** to 371 terms and a 371×150
   matrix, and a `shinyApp` object constructs. `httr2`/`dplyr` are still uninstalled; they are
   live-mode only and off the demo path.

   One environment trap worth keeping: **R's default `libcurl` download method fails here** with
   `SSL connect error` while the package index still fetches, which makes it look like a broken
   mirror. `wininet` and `curl` both work. If `install.packages` fails this way, set
   `options(download.file.method = "wininet")` rather than chasing the mirror.
3. **ggplot re-render latency: measured 187 ms median** (range 173–341 ms, n=5, the constellation
   at 6.4×4.3in / 190 dpi). Comfortable on a scrubber step and at a 2–5 s poll. Not viable per-poll
   if Phase 0's measured interval lands near 250 ms, in which case live mode renders on a throttle
   rather than on every poll. The demo path is the scrubber, so this cannot affect the pitch.
4. **OAuth inside Shiny** is the fiddliest part of live mode. It is not on the demo path — replay
   needs no auth at all — so it cannot block the pitch.
5. **`space.json` is gitignored** because 4 of its 371 terms are artist names carried over from the
   corpus (`radiohead`, `Kanye West`, `kendrick lamar`, `Timbaland`). The prototype reads it from
   disk, so nothing is published — but those four terms must be excluded from the constellation
   backdrop and the reading, or a demo in a public room shows four artists out of the author's
   listening history. Excluding them is the same fix the export needs, so do it once, in
   `space.R`, and let the export reuse it.

## Out of scope

**No queue writes.** Transport control (pause, next) acts on what is already playing; writing the
engine's picks into the Spotify queue is a different capability and belongs to Phase 4. The engine
ranks; it never chooses what you hear. No voice or generated commentary;
removing those is the parent spec's finding. No accounts beyond the single Spotify login. No
hosting: the app runs locally via `shiny::runApp()`, which is all a laptop demo needs.

## Open question

**Does the constellation earn its place?** It is the more expensive of the two plots and the less
honest. If the de-collision pass and the projection prove fussy, the reading bars plus the candidate
list carry the entire argument on their own. Build the bars first, and treat the constellation as
the thing that must justify itself.

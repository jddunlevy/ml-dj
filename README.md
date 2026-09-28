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
| 3 | Session engine + replay prototype | not started |
| 4 | Live client driving a real queue | after the pitch |

## Design

`docs/superpowers/specs/2026-09-28-ml-dj-design.md` is canonical. Plans live in
`docs/superpowers/plans/`.

## Architecture

Python trains. TypeScript serves. The boundary is a versioned `space.json`.

```
[ offline — Python ]
  last.fm scrobble history + tag pulls
      -> normalize; build tags x tracks matrix
      -> PPMI weighting + SVD -> dense tag vectors
      -> antonym detection (similarity up, co-tag down)
      -> export versioned space.json
            |
[ live — TypeScript ]
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

## Capture

```bash
python -m mldj capture --label dj
```

Polls currently-playing and appends events to `data/sessions/`. Run it while the AI DJ plays; stop
it with Ctrl-C. Captured data is personal and gitignored.

## A note on the data

This repo is public; the listening data is not. The scrobble corpus and captured sessions stay in
`data/`, which is gitignored. Only anonymized fixtures under `fixtures/` are committed.

## Lineage

Spotify auth and polling patterns come from `cd-player`, a retro now-playing display. Same approach,
separate repo, no dependency.

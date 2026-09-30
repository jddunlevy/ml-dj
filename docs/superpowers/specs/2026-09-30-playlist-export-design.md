# Playlist export

**Date:** 2026-09-30
**Status:** design, awaiting review
**Parent spec:** `docs/superpowers/specs/2026-09-28-ml-dj-design.md` — this is a slice of its Phase 4,
pulled forward. It does not override anything in the parent.

## What this is

One command that turns a captured session into a private Spotify playlist:

```
mldj playlist --session data/exports/dj-20260930T142116Z.json
```

The session's final vector ranks a pool of candidates; the top N become a playlist in your account.
Nothing polls, nothing queues, nothing touches playback. It is the smallest version of "use this
algorithm with my Spotify" that is actually usable, and it is the foundation the queue-writing tiers
would stand on.

## Why this slice, and why now

The parent spec puts Phase 4 after the pitch, and that stays true: **this must not eat the
deadline.** Phase 0 is at 1.99 of its 2 target hours but only 3 of 5 sessions, and it remains the
long pole — more so since 2026-09-30, because the reason to keep capturing is now statistical power
on the tag arm rather than an empty directory. See the plan's **Findings — 2026-09-30**.

This earns its place early for one reason: it is the only tier that needs no new algorithm, no
realtime path, and no Premium account. Everything it needs except a Spotify writer already exists
and is tested. If it turns out to be more than a day's work, that is the signal to stop and
reconsider, not to push through.

## The decision that shapes everything: where candidates come from

The prototype's pool comes from Last.fm `artist.getSimilar` → `artist.getTopTracks`. Those are
**names with no Spotify id**. Turning one into something playable means a search plus a fuzzy match,
and `match.track_key` is already described in CLAUDE.md as the load-bearing join. On the output side
the failure is worse than a skewed metric: a bad match puts *the wrong song* in your playlist, and
nothing downstream can detect it.

**So the pool comes from your own Spotify library instead** — `/v1/me/tracks` and
`/v1/me/top/tracks`. Every candidate then arrives with its URI already attached and the matching
problem does not exist. Tags come from the existing cache: 8,050 track-tag and 2,045 artist-tag
lookups are already on disk.

The cost is that it can only recommend music you already have. That is not a compromise here. The
thesis is session adaptation, **not discovery** — "Novelty is supporting evidence, not the thesis".
Session-adaptive reordering of music you own is the claim, stated exactly.

A Last.fm discovery pool stays possible later as a second, separately labelled source. It is out of
scope for this spec.

## Architecture

```
data/exports/<session>.json        (mldj export-session, already exists)
        │
        ├─ session vector  ── engine, ported to Python (see "The third engine")
        │
library ─┴─ /v1/me/tracks, /v1/me/top/tracks  ── URI + artist + title
        │
        ├─ tags           ── top_tags_cached / artist_top_tags_cached (already exist)
        ├─ rank           ── cosine against the session vector
        ├─ thin           ── at most N per artist
        │
        └─ POST /v1/users/{id}/playlists  +  POST /v1/playlists/{id}/tracks
```

### Modules

| Module | Job |
|---|---|
| `mldj/engine.py` | `session_new`, `session_step`, `session_run` — the port |
| `mldj/library.py` | Read saved and top tracks; `LibraryTrack(uri, artist, title)` |
| `mldj/playlist.py` | Rank, thin, create, add. Owns the `mldj playlist` subcommand |

`library.py` and `playlist.py` take an injected transport, per the repo convention that no test ever
reaches the wire.

## The third engine

This is the main design cost and it should be argued, not assumed.

The session vector is computed in `R/engine.R`. CLAUDE.md says the engine "will exist in R now and
TypeScript in Phase 4", with `fixtures/engine-trace.json` as the golden trace both must reproduce. A
Python port makes it **three** implementations of one algorithm.

Three alternatives were considered:

1. **Generate the playlist from R.** R already has the engine and the ranking, and `httr2` is
   already sanctioned for live mode. Rejected: it puts account-writing HTTP calls in the layer the
   architecture defines as display-only, and R would then need Spotify auth and token refresh, which
   is a second auth implementation — a worse duplication than the engine.
2. **R exports the final vector, Python does the rest.** Rejected as the worst of both: a new
   file-format contract between the languages, and the prototype becomes a required step in a
   pipeline that has nothing to do with the prototype.
3. **Port the engine to Python.** Chosen.

The port is roughly 40 lines: `session_new`, `session_step`, `session_run`, plus `tag_vector` and
cosine, all of which Python already has in `space/`. It is validated against
`fixtures/engine-trace.json` — the same trace R is held to — so the trace goes from guarding two
implementations to guarding three. **That strengthens the trace rather than weakening it**, and it
is the artifact Phase 4's TypeScript engine will be held to anyway.

The trace now carries `space_terms`, so a space rebuild is distinguishable from an engine change.

## Behaviour

```
mldj playlist --session <path> [--name NAME] [--limit 30] [--per-artist 2]
              [--decay 0.85] [--w 1.0] [--epsilon 0] [--dry-run]
```

- **Input** is an `mldj export-session` JSON — the same contract the prototype reads. No new format.
- **The pool** is the library minus every track played in the session. A session-adaptive playlist
  that opens with the track you just skipped is self-evidently broken.
- **Ranking** is cosine against the final session vector, with the same `ε · novelty` term the
  prototype uses, so the two agree on what "next" means.
- **Thinning** caps tracks per artist, defaulting to 2. The prototype's `top_by_artist` found six
  distinct artists in a top 20 because artist-tier tags are identical across an artist's tracks; a
  30-track playlist from six artists is the same bug wearing a different hat.
- **Output** is a new private playlist named `ml-dj · <session id>` unless `--name` overrides.
- **`--dry-run`** prints the tracklist and creates nothing. Off by default — see open question 2,
  resolved.

### Never modify an existing playlist

Every run creates a new one. Appending to or rewriting a playlist the user may have edited is a
destructive operation with no undo, and the saving in clutter is not worth the class of bug.

### The playlist description records provenance

`decay`, `w`, `epsilon`, pool size, the source session id, and the space's `vocabulary_size` and
`built_utc`. A playlist that cannot say which space produced it is not reproducible, and the space
is rebuilt often enough for that to matter: the stoplist added on 2026-09-30 moved the vocabulary
from 371 terms to 323 and shifted every cosine, which is exactly the kind of change a playlist made
last week cannot otherwise account for.

## Auth

This is the first thing in the project that **writes to the account**, and `auth.py` currently says
of its single read scope: "Do not widen it; user-modify-playback-state belongs to Phase 4."

Three scopes are added:

| Scope | For |
|---|---|
| `playlist-modify-private` | creating the playlist |
| `user-library-read` | `/v1/me/tracks` |
| `user-top-read` | `/v1/me/top/tracks` |

`user-modify-playback-state` is **not** added. Nothing here touches playback, and the narrower the
token the smaller the blast radius of a bug in a tool that is one typo from writing to a real
account.

Widening the scope invalidates the cached token: `data/.spotify-tokens.json` must be deleted and the
PKCE flow re-run. That is a one-time interruption to capture, and **capture is the long pole** — so
re-auth happens between sessions, never during one. The comment in `auth.py` is updated rather than
deleted, so the reasoning survives.

## Testing

Per repo convention, `pytest` with an injected transport; no test reaches the wire.

- **Engine parity** — the Python engine reproduces `fixtures/engine-trace.json` step for step. This
  is the test that earns the port.
- **Pool construction** — tracks played in the session are excluded; pagination over `/v1/me/tracks`
  is followed to the end; a library track with no cached tags falls back to the artist tier and then
  to exclusion, never to a zero vector entered at rank 0.
- **Thinning** — the per-artist cap holds, and a pool with fewer artists than slots returns what
  exists rather than padding.
- **Playlist writes** — the create and add calls are made with the right body; `--dry-run` makes
  neither; a track list longer than Spotify's 100-per-request limit is chunked.
- **Failure** — a 401 refreshes and retries once; a 403 (usually a missing scope) raises with the
  scope named, because "Forbidden" alone sends you to the wrong place.

## Risks

- **Library size.** `/v1/me/tracks` is paginated at 50. A large library is many requests, and tags
  for tracks outside the 5,844-track corpus are uncached. Mitigation: the pool is cached to
  `data/library.json` and refreshed only on `--refresh-library`.
- **Tag coverage on the library.** Corpus coverage is 98.2%, but the library is a different set and
  the figure does not transfer. **The first build must report coverage before anything is ranked**;
  a low number means the pool is thin and the ranking is uninformative, and that must be visible
  rather than inferred from a disappointing playlist.
- **The playlist is only as good as the session.** A session of 16 events with 8 `unknown` produces
  a weak vector. The command reports the outcome mix, so a thin result is attributable.
- **Scope creep toward Tier 2.** Queue writing is one endpoint away and must stay out until the
  pitch is delivered.

## Out of scope

Queue writes, playback control, skip control, a Last.fm discovery pool, any R change, any change to
the prototype, multi-user support, and the Spotify Extended Streaming History export.

## Open questions

1. **Does the ranking want the *final* session vector, or the vector at each step?** This spec uses
   the final one: one vector, one playlist. A per-step variant — each track chosen against the
   vector as it stood — would produce a playlist that narrates the session rather than summarising
   it, which is arguably more faithful to the thesis. It is also a different and larger design.
   Deferred deliberately, not overlooked.
2. ~~**Should `--dry-run` be the default?**~~ — **RESOLVED 2026-09-30: off by default.** Every
   other command in this repo does its job when run, and the two guards that matter are already in
   the design rather than in a flag: every run creates a *new* playlist and never edits an existing
   one, and the token carries no `user-modify-playback-state`. So the worst case of a mistaken run
   is a stray private playlist the user deletes — not lost data and not interrupted playback. A
   default that makes the ordinary invocation a no-op trains people to append `--write` without
   reading the output, which buys nothing.

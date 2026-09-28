# ml-dj — Design

**Deliverable:** MIS 430 Individual Pitch (week 8)
**Target product:** Spotify AI DJ
**Prototype repo:** `github.com/jddunlevy/ml-dj` — **public**, default branch `main`, to be cloned at
`C:\dev\ml-dj`
**Lineage:** `C:\Users\jaxon\Code\cd-player` — same Spotify auth and polling patterns, separate repo
**Status:** design drafted 2026-09-28, restructured against the pitch prompt. **Confirmed as the
Individual Pitch target** — the Character.AI alternative (`2026-09-28-second-voice-design.md`) is
superseded and not being built.

---

## The assignment

Pick a real AI product you can actually access and use. Tear it down through the course lens —
where it fails its users, hides its uncertainty, creates harm, or over-promises. Propose and pitch a
redesign, including a prototype of the key improvement. The role is **the analyst making the case
for change**.

| Requirement | How this design meets it |
|---|---|
| A real AI product you can access and use | Spotify AI DJ. Premium confirmed — `cd-player` already requires it |
| Real users, specific task | Subscribers wanting lean-back listening without curating |
| Flawed and **bounded** | One feature inside Spotify, not Spotify; two named failures |
| Live presentation | Delivered live; no recording |
| Slide deck or visual aid | HTML deck, print CSS, exported to PDF — see Deliverables |
| **Prototype of the improvement, included** | Recorded-session replay with the live session vector — beat 5 |
| 5 minutes, strictly enforced | Timing and rehearsal belong to the presenter |
| Every claim defensible if asked | See *The underlying teardown* |

**The governing line in the prompt:** *"structure your pitch as though [the full teardown analysis
and design documentation] exists and you could defend any claim if asked."*

Everything below the pitch section exists for that line. The semantic space, the antonymy work, and
the evaluation harness are not additions to the assignment — they are the documentation a teardown
of this kind assumes. The pitch surfaces a fraction of it.

## The brief, which is the diagnosis

The original complaints, unchanged, because they *are* the teardown:

1. **It does not introduce enough new music.**
2. **It does not learn from what you skip during the current session.**
3. **No AI DJ voice** — this turns out to be an analytical finding, not a preference. See beat 3.

---

# The pitch

Seven beats, in the prompt's order. Timing and rehearsal are the presenter's.

## 1. Hook — a real user in a real moment

A first-party moment, captured and dated: you put the DJ on to work. It plays something you skipped
yesterday. You skip it. It plays another track by the same artist. You skip again. Twenty minutes
in, you have heard nothing you didn't already know, you are still skipping, and you give up and put
on a playlist you made years ago.

The DJ was talking the whole time — warm, confident, telling you it knows what you're into.

**Open on the person, not the product**, as the prompt requires. The moment must be real, yours, and
dated, because beat 3 is going to prove it with your own listening data.

## 2. Product and user — briefly

Spotify AI DJ: a generated-voice radio feature inside Spotify that picks tracks continuously and
talks between them. Users are subscribers who want music without curating it. The task is lean-back
listening.

*Brief means brief. The hook bought attention; spend as little of it here as possible.*

## 3. Diagnosis — confident narration over a system that isn't adapting

Three findings, in the course's terms.

**It fails its users through an exploration deficit.** The DJ optimizes for familiarity. Measured
against your own scrobble history, the share of DJ-played tracks you had never heard before is the
headline number of this pitch — quantified, first-party, dated.

**It hides its uncertainty by having no feedback channel.** A skip is the strongest signal a
listener can send, and it changes nothing you can observe within the session. The system gives you
no way to tell whether it registered anything, because it displays no state at all.

**It over-promises, and the voice is where.** The DJ *speaks* like a curator who knows you and is
reading the room. That narration is a confidence display, and the adaptation it implies does not
exist — the two measurements above are the evidence. This is the sharpest finding in the teardown:
the product's most distinctive feature is the part that over-claims relative to what the system
actually knows.

## 4. Redesign — delete the voice, show the state, adapt within the session

Each change traces to a diagnosed cause, as the prompt requires:

| Diagnosed cause | Change |
|---|---|
| Exploration deficit | Novelty becomes an explicit, user-visible parameter rather than an emergent property |
| Skips change nothing in-session | A session vector updated live from skip and completion events |
| No observable system state | The session vector is rendered on screen — it *is* the explanation for the next track |
| Voice implies adaptation that doesn't exist | The voice is removed. Confidence should be earned by visible behavior, not narrated |

Deleting the DJ's most recognizable feature is a strong claim, so it is made the way the prompt
wants claims made: traced to a specific diagnosed failure, and defensible.

## 5. Prototype — a session that visibly changes its mind

A recorded real session replayed through the engine: tracks arriving, skips landing, and the session
vector moving in tag space as they do — with the next pick explained by the vector's current
position.

Deterministic and offline, so no network, rate limit, or Spotify state can break a live
presentation. The live client that drives a real queue is the phase after the pitch; it is not
required to show the idea, and betting a graded five minutes on live playback would be a bad trade.

## 6. Honesty check — what must be true

Required by the prompt, and generated by the design rather than improvised:

- **Tag coverage.** The semantic space is only as good as Last.fm's tags for the music in question.
  Obscure and very new releases are thinly tagged, and those are exactly the tracks novelty
  depends on.
- **Spotify audio features are unavailable** to a new app, so the whole feature space is the tag
  graph. Verify against a real client ID before the live phase.
- **Skip data does not exist historically.** Last.fm records no skips, so offline evaluation uses
  played-next prediction and the real signal only exists live.
- **The antonymy assumption.** Negative updates depend on distinguishing opposition from similarity
  in the tag space; if that discriminator fails, skips move the session the wrong way.
- **It is a single-user system.** Everything is trained on one listening history, so nothing here
  demonstrates it would work for someone with a different or thinner history.
- **Queue control requires Premium**, and the redesign assumes a platform willing to expose
  recommendation state to users, which is a product decision the analysis cannot make.

## 7. Close — mirror the hook

Back to the same evening. Same skip — but this time the session visibly turns, and the next track is
one you have never heard. The system does not tell you it understands you. It shows you.

---

# Deliverables

| Artifact | Beat | Notes |
|---|---|---|
| Slide deck | all | HTML + print CSS, one slide per page, exported to PDF. Inline SVG, no Mermaid, per established coursework practice. Mono aesthetic. |
| Session replay prototype | 5 | Static page, deterministic, no network |
| Novelty measurement | 3 | Computed from scrobble history; the pitch's headline number |
| Captured DJ session logs | 1, 3 | First-party, dated evidence |
| Underlying teardown documentation | — | Not submitted. Exists so claims survive questions. |

---

# The underlying teardown

The analysis the pitch is grounded on. Not submitted; the prompt says to have it and be able to
defend from it.

## Measuring the diagnosis

The teardown's credibility rests on beat 3 being measured rather than asserted.

- **Novelty rate** — of tracks played by the DJ, the share never previously scrobbled. Requires
  logging DJ sessions against scrobble history.
- **Post-skip persistence** — after a skip, how often the next track shares the skipped track's
  artist or dominant tags. This is the "it isn't listening" claim, quantified.
- **Repetition** — how often the DJ replays tracks already skipped in a recent window.

All three come from the same captured logs, and all three are computable before any of the
recommender exists. **This is the first thing to build**, because it is what makes the pitch a
teardown rather than an opinion.

## Why this is also a semantics project

The requirement that produces it is skip handling.

Skipping a `mellow` track should move the session vector away from mellow. But antonyms and
near-antonyms have similar distributions — `loud`/`quiet`, `mellow`/`intense`, `minimal`/`maximal`
occur in the same contexts, so cosine similarity scores them as *similar*. A naive negative update
can therefore push the session toward the opposite of what the skip meant, or back into the skipped
region through its nearest neighbours.

**Skips cannot be handled correctly without solving antonymy.** The linguistics is the mechanism,
not an ornament on it.

Underneath that sits the folksonomy problem. Last.fm tags are an uncontrolled vocabulary: `chill`,
`chillout`, `chill-out`, `mellow`, `laid back`, `lo-fi`, `lofi` are seven strings covering perhaps
three meanings. A bag-of-tags model treats them as seven orthogonal dimensions, which is a semantic
failure rather than a modelling one. The ceiling on recommendation quality is set by how well the
system models what tags mean.

### The antonymy discriminator

Synonyms co-tag the same track constantly — one song carries both `chill` and `mellow`. Antonyms
occupy similar contexts but almost never co-tag a single item; nobody tags one track both `loud` and
`quiet`.

```
high distributional similarity + low same-item co-occurrence  ⇒  antonym pair
high distributional similarity + high same-item co-occurrence ⇒  synonym pair
```

Testable against a hand-built gold set, and the project's most defensible contribution.

**Known risk:** complementary pairs that are neither synonym nor antonym — `male vocalist` /
`female vocalist`, `verse` / `chorus` — may also show high similarity with low co-tagging. The gold
set must include them as a distinct class, or the discriminator will silently misfile them.

### Other semantic problems in scope

- **Morphological normalization** — `hip hop` / `hip-hop` / `hiphop`, `lo-fi` / `lofi`
- **Polysemy** — `dream` across *dream pop*, *dreamy*, *dreamcore*
- **Gradable predicates** — `heavy`, `dark`, `mellow` are scalar and genre-relative; `heavy` in
  ambient is not `heavy` in metal
- **Compositionality** — the session vector is compositional distributional semantics: how tag
  meanings combine into "what I want right now"

## Architecture

**Python trains. TypeScript serves.** The boundary is a versioned `space.json`.

```
[ offline — Python ]
  last.fm scrobble history + tag pulls
      ↓  normalize; build tags × tracks matrix
      ↓  PPMI weighting + SVD → dense tag vectors
      ↓  antonym detection (similarity ↑, co-tag ↓)
      ↓  export versioned space.json
            ↓
[ live — TypeScript, cd-player lineage ]
  PKCE auth · poll currently-playing · interpolateProgress
      ↓  skip detection, with timing
      ↓  session vector over the loaded space
      ↓  POST /me/player/queue
      ↓  render the session vector on screen
```

Python never runs at listen time. The client stays serverless and dependency-free, like `cd-player`.
Cosine similarity and weighted sums are a few lines of TypeScript, so nothing substantial is
duplicated.

## The session engine

```
session vector, in tag space

  played through   +w · tags(track)
  skip @ 0:05      −w · tags(track) · 1.0
  skip @ 2:10      −w · tags(track) · 0.3
  each pick        vector *= decay

next pick = argmax over candidates of
      sim(tags, session_vector)
    + ε · novelty
    − recency_penalty
```

Skip weight scales with earliness: an early skip rejects the track's character, a late skip means it
was acceptable and finished. `interpolateProgress` from `cd-player` already computes the number that
separates these.

Negative updates project along semantic axes identified by antonym detection, not along raw tag
dimensions — this is where the antonymy work is consumed.

**The session vector is rendered on screen.** It is the explanation for the next track, it is the
fix for the "no observable state" diagnosis, and it is what the prototype shows in beat 5.

## Candidate pool

Last.fm `artist.getSimilar`, `tag.getTopTracks`, and `track.getSimilar`, minus everything already
scrobbled. Free, no deprecation exposure, and the tag graph doubles as the content feature space.

`ε` controls how far from the known cluster each pick reaches — the exploration parameter answering
diagnosis 1 directly, and the thing the redesign makes visible instead of emergent.

## Inherited constraints

**Spotify audio features are unavailable.** Audio Features, Audio Analysis, Recommendations, and
Related Artists were cut off for apps created after 2024-11-27 in development mode. Assume a new app
has none. This is why the feature space is the tag graph — a design input, not a workaround. Verify
against a real client ID before the live phase.

**Last.fm does not record skips.** Scrobbles fire after roughly half a track or four minutes, so a
skip is an absence in the history. Historical skip data is unavailable; offline evaluation uses
played-next prediction.

**Poll granularity.** `cd-player` polls at 5000 ms. Skip detection is "track changed, and the
outgoing track's interpolated progress fell well short of its duration." At 5 s, fast skips and
multi-skip bursts collapse or vanish. The interval must drop, traded against rate limits, and the
chosen value justified by measurement.

## Reuse from cd-player

Patterns, not a dependency — `ml-dj` is a separate repo.

| `cd-player` | Role here |
|---|---|
| `auth.ts` | PKCE, token persistence and refresh, loopback redirect |
| `spotify.ts` | Polling, 429 and `Retry-After` handling |
| `player-state.ts` | `interpolateProgress` — the skip detector's core primitive |
| `controls.ts` | Command shape and the stale-scope 403 path; extended to queue writes |
| TS + Vite + Vitest, per-module tests, JSON fixtures | Same harness |

Additional scope beyond `cd-player`'s `user-read-currently-playing user-modify-playback-state`:
`user-read-playback-state` if the upcoming queue is read back.

## Evaluation

1. **Semantic.** A hand-built gold set of tag pairs labeled synonym / related / antonym /
   complementary / unrelated. Does the space rank them correctly? Does antonym detection recover
   known pairs without swallowing complementary ones?
2. **Offline recommendation.** Held-out sessions from scrobble history: given the first *n* tracks,
   does the model predict what was actually played next?
3. **Online.** Skip rate and novelty rate against the measured Spotify DJ baseline — the same
   numbers as beat 3, which is what makes the comparison fair.

## Phases

**Phase 0 — measure the baseline.** Capture DJ sessions, compute novelty rate, post-skip
persistence, and repetition against scrobble history. Produces beat 3's evidence and the yardstick
every later phase is judged against. Nothing else depends on the recommender existing.

**Phase 1 — the semantic space.** Ingest, normalize, matrix, PPMI + SVD, gold set, level-1
evaluation. Pure Python. No Spotify API, no Premium, no `cd-player`.

**Phase 2 — antonymy.** The discriminator, evaluated against the gold set, including the
complementary-pair trap.

**Phase 3 — session engine + prototype.** Session vector, decay, skip weighting, candidate pool,
exploration. The replay visualization is the pitch's beat 5 artifact.

**Phase 4 — live client.** The `cd-player`-lineage browser app driving a real queue. After the
pitch.

Phases 0 through 3 are the pitch. Phase 4 is the payoff.

## Public repo handling

The repo is public, unlike the vault.

- `.env.local`, the Spotify client ID, and the Last.fm API key stay gitignored
- The scrobble corpus is personal listening data and stays gitignored; a small anonymized fixture is
  committed for tests
- `space.json` is derived — committed only if it contains no raw history

## Out of scope

No voice, no TTS, no generated commentary — removing these is a finding, not an omission. No social
features, no multi-user support, no accounts beyond the single Spotify login. Not a Spotify client:
playback stays in whatever Spotify app is running; `ml-dj` only drives the queue.

## Open questions

1. Whether a new Spotify app has any audio-feature access. Assumed none; verify before Phase 3.
2. Poll interval against rate limits — measured in Phase 4, not assumed.
3. Whether DJ sessions can be reliably distinguished from ordinary listening in the capture logs.
   Phase 0 depends on it.
4. Unique-track count and tag coverage across the corpus. The history is deep enough (below), but
   the matrix is built from distinct tracks, not scrobbles, and PPMI + SVD rank depends on the
   distinct count and on how many of those tracks Last.fm actually tags. Counted in Phase 1's
   ingest step.

## Resolved

**History depth — 39,000+ all-time scrobbles.** This was the main risk to Phase 1 and it is retired.
A corpus that size supports a tags × tracks matrix at a useful SVD rank, and it gives the novelty
measurement in beat 3 a long baseline to judge "never previously scrobbled" against. What remains is
question 4: how many *distinct* tracks those scrobbles cover, and how well tagged they are.

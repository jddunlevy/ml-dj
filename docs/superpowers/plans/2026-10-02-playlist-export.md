# Playlist Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mldj playlist --session <export>` turns a captured session into a new private Spotify
playlist, ranked by the session's final vector against your own library.

**Architecture:** The engine is ported to Python and held to `fixtures/engine-trace.json`, the same
golden trace R is held to. The candidate pool is your Spotify library, so every candidate arrives
with its URI attached and no fuzzy match can ever put the wrong song in a playlist. Ranking is
cosine against the final session vector with the prototype's `ε · novelty` term, thinned per
artist, then written as a brand-new playlist that records its own provenance.

**Tech Stack:** Python 3 stdlib plus `numpy` (already a dependency). No new third-party packages.
`pytest` with an injected transport; no test reaches the wire.

**Spec:** `docs/superpowers/specs/2026-09-30-playlist-export-design.md`

---

## Three places the spec meets the code and needs more than it says

Found while reading the existing modules against the spec. Each is handled by a task below; none
changes the spec's design.

1. **`Transport.post` cannot express a JSON body.** It form-urlencodes
   (`urllib.parse.urlencode`), which is right for the OAuth token endpoint and wrong for every
   Spotify playlist write. The boundary gains `post_json` — Task 1.

2. **The tag cache is keyed on raw Last.fm strings; the library arrives with Spotify strings.**
   `lastfm._cache_path` hashes `f"{artist}\t{title}"` unnormalized, and the cache was filled from
   scrobbles. So the spec's "the matching problem does not exist" is true of *playback* — the URI
   is exact — but not of *tags*: `"Blue Monday - 2016 Remaster"` from Spotify will miss the cache
   entry Last.fm filled as `"Blue Monday"`. The fix reuses `match.track_key` in the safe
   direction: build a `track_key -> tags` index and look library tracks up in it. A miss thins the
   pool; it can never mis-select a song. Task 5.

3. **Parity needs two things Python's space layer does not currently do.** R's `tag_vector`
   sums **unit-normalized** term vectors; `TagSpace.compose` sums raw ones, so a straight reuse
   produces different cosines. And R's `load_space` drops the four leaked artist terms at load
   while Python's does not — the trace was taken against 319 terms, not 323. Task 2 adds an
   opt-in `exclude`; Task 3 normalizes inside the engine.

   **The exclusion must not become `load_space`'s default.** The Phase 2 baselines recorded in
   CLAUDE.md (antonym 0.030, complementary −0.020) were measured over the full 323-term
   vocabulary. A default that silently dropped four terms would move those numbers with no commit
   that appears to touch them.

## Global Constraints

- **Line width: 100.**
- **Dependencies:** stdlib plus the existing `numpy`/`scipy`. Justify anything else; nothing here
  needs it.
- **Tests:** `pytest`, TDD. Every network boundary takes an injected transport, so no test reaches
  the wire. No test sleeps.
- **THIS REPO IS PUBLIC.** Never commit anything under `data/`. `space.json` stays uncommitted.
  Check `git status --porcelain` before every commit.
- **The four excluded terms** — `radiohead`, `kanyewest`, `kendricklamar`,
  `timbaland` — must not reach any surface this command produces.
- **Never modify an existing playlist.** Every run creates a new one. No append, no rewrite.
- **`user-modify-playback-state` is never added to the token.** Nothing here touches playback.
- **Commits:** conventional (`feat:`, `fix:`, `test:`, `docs:`), one per task, frequent and small.
- **Scope:** no queue writes, no playback control, no Last.fm discovery pool, no R change, no
  change to the prototype.
- **The ranking uses the session's FINAL vector**, one vector per playlist. The per-step variant is
  the spec's open question 1 and is deliberately deferred.

## File structure

| File | Responsibility |
|---|---|
| `src/mldj/engine.py` | **Create.** `session_new`, `session_step`, `session_run`, `tag_vector`, `cosine_all`. The port. Pure arithmetic over a `TagSpace`; no I/O. |
| `src/mldj/library.py` | **Create.** `LibraryTrack`, paginated reads of `/v1/me/tracks` and `/v1/me/top/tracks`, the on-disk pool cache, the `track_key -> tags` index, and the coverage report. |
| `src/mldj/playlist.py` | **Create.** Rank, thin, create, add, and the `mldj playlist` subcommand. |
| `src/mldj/transport.py` | **Modify.** Add `post_json` to the `Transport` protocol and `UrllibTransport`. |
| `src/mldj/space/space.py` | **Modify.** Add `EXCLUDED_TERMS` and an opt-in `exclude` argument to `load_space`. |
| `src/mldj/auth.py` | **Modify.** Widen `SCOPE` by three scopes; update the comment that forbade widening. |
| `src/mldj/cli.py` | **Modify.** Register the subcommand. |
| `tests/fakes.py` | **Modify.** `FakeTransport.post_json`. |
| `tests/test_engine.py` | **Create.** Engine behaviour plus the parity test that earns the port. |
| `tests/test_library.py` | **Create.** Pagination, dedupe, caching, the tag index, coverage. |
| `tests/test_playlist.py` | **Create.** Ranking, thinning, writes, chunking, dry-run, failure modes. |
| `tests/test_transport.py` | **Modify.** The JSON request builder. |
| `tests/space/test_space.py` | **Modify.** Exclusion at load, and that the default excludes nothing. |
| `tests/test_auth.py` | **Modify.** The scopes present, and the one that must stay absent. |

`library.py` holds the tag index as well as the fetch because both are about turning a library row
into a scorable row — files that change together live together. `playlist.py` follows the spec's
module table.

---

### Task 1: A JSON body on the transport boundary

`Transport.post` urlencodes a form. Spotify's playlist endpoints take JSON. This adds a second
method rather than changing `post`, because the OAuth token endpoint genuinely wants a form body
and `auth.py` depends on that.

**Files:**
- Modify: `src/mldj/transport.py`
- Modify: `tests/fakes.py`
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Transport.post_json(url: str, payload: Mapping[str, object], headers: Mapping[str, str] | None = None) -> Response`
  - `transport._json_request(url: str, payload: Mapping[str, object], headers: Mapping[str, str] | None) -> urllib.request.Request`
  - `FakeTransport.requests` records a JSON post as `("POST_JSON", url, payload)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_transport.py`:

```python
from mldj.transport import _json_request


def test_a_json_post_carries_the_payload_as_a_utf8_json_body():
    request = _json_request(
        "https://api.spotify.com/v1/playlists/p1/tracks",
        {"uris": ["spotify:track:a"]},
        {"Authorization": "Bearer tok"},
    )
    assert request.get_method() == "POST"
    assert request.data == b'{"uris": ["spotify:track:a"]}'
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") == "Bearer tok"


def test_a_json_post_does_not_let_a_caller_override_the_content_type():
    # A form content-type on a JSON body is a 400 from Spotify with an unhelpful message.
    request = _json_request("https://x/y", {"a": 1}, {"Content-Type": "text/plain"})
    assert request.get_header("Content-type") == "application/json"
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_transport.py -q
```

Expected: `ImportError: cannot import name '_json_request' from 'mldj.transport'`.

- [ ] **Step 3: Implement**

In `src/mldj/transport.py`, add to the `Transport` protocol:

```python
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...
```

Add the builder as a module-level function, so the body and headers are testable without the wire:

```python
def _json_request(
    url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str] | None = None,
) -> urllib.request.Request:
    """A POST carrying a JSON body. The content-type is ours, not the caller's: a form
    content-type on a JSON body earns a 400 whose message names nothing useful."""
    body = json.dumps(payload).encode("utf-8")
    merged = {**dict(headers or {}), "Content-Type": "application/json"}
    return urllib.request.Request(url, data=body, headers=merged, method="POST")
```

And the method on `UrllibTransport`:

```python
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._send(_json_request(url, payload, headers))
```

In `tests/fakes.py`, add to `FakeTransport`:

```python
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        self.requests.append(("POST_JSON", url, payload))
        return self._next()
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass, two more than before.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/transport.py tests/fakes.py tests/test_transport.py
git commit -m "feat: a JSON body on the transport, for writes the form encoder cannot express"
```

---

### Task 2: Excluding the four leaked terms at load, opt-in

R drops them at load. Python must be able to, or the ported engine sees 323 terms where the trace
was taken against 319. **Opt-in, not default:** the recorded Phase 2 baselines were measured over
the full vocabulary and must not move silently.

**Files:**
- Modify: `src/mldj/space/space.py`
- Test: `tests/space/test_space.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `mldj.space.space.EXCLUDED_TERMS: tuple[str, ...]`
  - `load_space(path: Path = DEFAULT_SPACE_PATH, exclude: Collection[str] = ()) -> TagSpace`

- [ ] **Step 1: Write the failing test**

Add to `tests/space/test_space.py`:

```python
import numpy as np

from mldj.space.space import EXCLUDED_TERMS, TagSpace, load_space, save_space

FULL_META = {
    "rank": 2,
    "eigenvalue_weighting": 0.0,
    "shift": 1.0,
    "context_smoothing": 1.0,
    "min_count": 2,
    "min_artists": 2,
    "include_artists": False,
    "seed": 0,
    "vocabulary_size": 3,
    "item_counts": {},
    "tier_counts": {},
}


def _saved(tmp_path):
    space = TagSpace(
        terms=("indie", "radiohead", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]),
        meta=FULL_META,
        display={"radiohead": "radiohead"},
    )
    path = tmp_path / "space.json"
    save_space(space, path)
    return path


def test_load_space_drops_excluded_terms_and_keeps_the_vectors_aligned(tmp_path):
    space = load_space(_saved(tmp_path), exclude=("radiohead",))
    assert space.terms == ("indie", "shoegaze")
    # The surviving rows must be the surviving terms' rows, not simply the first two rows.
    assert space.vector("shoegaze").tolist() == [1.0, 1.0]


def test_load_space_excludes_nothing_by_default(tmp_path):
    # The recorded Phase 2 baselines (antonym 0.030, complementary -0.020) were measured over
    # the full vocabulary. A default exclusion would move them with no commit touching them.
    assert load_space(_saved(tmp_path)).terms == ("indie", "radiohead", "shoegaze")


def test_the_excluded_terms_are_the_four_the_privacy_review_confirmed():
    # R/space.R holds the same list. Two implementations of one exclusion must not drift.
    assert EXCLUDED_TERMS == ("radiohead", "kanyewest", "kendricklamar", "timbaland")
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/space/test_space.py -q
```

Expected: `ImportError: cannot import name 'EXCLUDED_TERMS'`.

- [ ] **Step 3: Implement**

In `src/mldj/space/space.py`, add the constant beside the other module constants:

```python
# The four terms the Phase 1 privacy review confirmed are artist names rather than
# descriptors. Normalized keys, and identical to R/space.R's EXCLUDED_TERMS - two
# implementations of one exclusion list must not drift. The other four flagged terms
# (electronic, love, fun, lush) are real bands AND ordinary descriptors; they stay.
EXCLUDED_TERMS = ("radiohead", "kanyewest", "kendricklamar", "timbaland")
```

Widen the `collections.abc` import to `from collections.abc import Collection, Mapping, Sequence`
and replace `load_space`'s body:

```python
def load_space(path: Path = DEFAULT_SPACE_PATH, exclude: Collection[str] = ()) -> TagSpace:
    """Read the versioned export.

    `exclude` is opt-in and empty by default. The engine passes EXCLUDED_TERMS because the
    prototype does and parity is measured against it; the sweep and the evaluation must NOT,
    because the recorded baselines were taken over the full vocabulary.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("format_version")
    if version != SPACE_FORMAT_VERSION:
        raise ValueError(
            f"format_version {version!r} is not the expected {SPACE_FORMAT_VERSION}; "
            "rebuild the space rather than reading it with the wrong reader"
        )
    terms = list(raw["terms"])
    vectors = np.array(raw["vectors"], dtype=np.float64)
    banned = {canonical_tag(term) for term in exclude}
    if banned:
        keep = [i for i, term in enumerate(terms) if canonical_tag(term) not in banned]
        terms = [terms[i] for i in keep]
        vectors = vectors[keep] if keep else vectors[:0]
    return TagSpace(
        terms=tuple(terms),
        vectors=vectors,
        meta=raw["meta"],
        display=raw.get("display", {}),
    )
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass. If an existing space test fails, the default changed — fix the code, not
the test.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/space/space.py tests/space/test_space.py
git commit -m "feat: let a caller exclude terms at load, without moving the recorded baselines"
```

---

### Task 3: `mldj/engine.py` — the port, held to the golden trace

The task that earns the port. Three implementations of one algorithm is the cost; the trace going
from guarding two to guarding three is the return.

**Files:**
- Create: `src/mldj/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `TagSpace`, `load_space(path, exclude=EXCLUDED_TERMS)`, `EXCLUDED_TERMS` (Task 2).
- Produces:
  - `SessionState` dataclass with fields `space: TagSpace`, `decay: float`, `w: float`,
    `v: np.ndarray`, `history: list[Mapping[str, object]]`
  - `session_new(space: TagSpace, decay: float = 0.85, w: float = 1.0) -> SessionState`
  - `session_step(state: SessionState, event: Mapping[str, object]) -> SessionState`
  - `session_run(state: SessionState, events: Iterable[Mapping[str, object]]) -> SessionState`
  - `tag_vector(space: TagSpace, tags: Sequence[str]) -> np.ndarray`
  - `cosine_all(space: TagSpace, v: np.ndarray) -> list[tuple[str, float]]` — descending,
    ties in the space's own term order
  - `DEFAULT_DECAY = 0.85`, `DEFAULT_W = 1.0`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest

from mldj.engine import cosine_all, session_new, session_run, session_step, tag_vector
from mldj.space.space import EXCLUDED_TERMS, TagSpace, load_space

TRACE_PATH = Path("fixtures/engine-trace.json")
SPACE_PATH = Path("space.json")
SESSION_PATH = Path("fixtures/session-synthetic.json")


def a_space() -> TagSpace:
    # Deliberately un-normalized rows: tag_vector must unit them before summing, and rows of
    # different length are the only way to see that it did.
    return TagSpace(
        terms=("indie", "shoegaze", "loud"),
        vectors=np.array([[3.0, 0.0], [0.0, 5.0], [0.0, 0.0]]),
        meta={},
    )


def test_tag_vector_sums_unit_vectors_so_a_long_tag_list_does_not_win_on_count():
    # R/space.R normalizes each row before summing; the Python port must agree or every
    # cosine in the trace is off. A raw sum here would be [3, 5].
    assert tag_vector(a_space(), ["indie", "shoegaze"]).tolist() == [1.0, 1.0]


def test_tag_vector_ignores_tags_the_space_does_not_hold():
    # Last.fm routinely returns tags the vocabulary filtered out. Dropping them is correct;
    # raising would make an ordinary session fatal.
    assert tag_vector(a_space(), ["indie", "notaterm"]).tolist() == [1.0, 0.0]


def test_tag_vector_of_nothing_recognised_is_the_zero_vector():
    assert tag_vector(a_space(), ["notaterm"]).tolist() == [0.0, 0.0]


def test_a_zero_norm_term_contributes_nothing_rather_than_a_nan():
    assert tag_vector(a_space(), ["loud"]).tolist() == [0.0, 0.0]


def test_a_completed_track_adds_its_tags():
    state = session_step(
        session_new(a_space(), decay=0.5, w=2.0), {"outcome": "completed", "tags": ["indie"]}
    )
    assert state.v.tolist() == [2.0, 0.0]


def test_a_skipped_track_subtracts_its_tags_scaled_by_earliness():
    state = session_step(
        session_new(a_space(), decay=1.0, w=1.0),
        {"outcome": "skipped", "tags": ["indie"], "earliness": 0.25},
    )
    assert state.v.tolist() == [-0.25, 0.0]


def test_an_unknown_outcome_decays_without_updating():
    # An ambiguous record may not have been a skip, so it cannot found a negative claim.
    state = session_new(a_space(), decay=0.5)
    state.v[:] = [4.0, 0.0]
    stepped = session_step(state, {"outcome": "unknown", "tags": ["indie"]})
    assert stepped.v.tolist() == [2.0, 0.0]


def test_a_skip_with_no_earliness_raises_rather_than_assuming_a_full_penalty():
    with pytest.raises(ValueError, match="earliness"):
        session_step(session_new(a_space()), {"outcome": "skipped", "tags": ["indie"]})


def test_an_unrecognised_outcome_raises():
    with pytest.raises(ValueError, match="bogus"):
        session_step(session_new(a_space()), {"outcome": "bogus", "tags": []})


def test_earliness_is_clamped_to_the_unit_interval():
    state = session_step(
        session_new(a_space(), decay=1.0),
        {"outcome": "skipped", "tags": ["indie"], "earliness": 9.0},
    )
    assert state.v.tolist() == [-1.0, 0.0]


def test_session_run_applies_every_event_in_order_and_records_history():
    events = [
        {"outcome": "completed", "tags": ["indie"]},
        {"outcome": "completed", "tags": ["shoegaze"]},
    ]
    state = session_run(session_new(a_space(), decay=0.5, w=1.0), events)
    # The first event has been decayed once; the second was added whole.
    assert state.v.tolist() == [0.5, 1.0]
    assert len(state.history) == 2


def test_cosine_all_is_descending_and_breaks_ties_in_the_space_term_order():
    # R sorts with a stable sort, so equal cosines keep the space's own ordering. np.argsort
    # promises nothing there, and TagSpace.neighbours breaks ties by term NAME instead - a
    # different rule. Copying that rule here would desynchronise the trace.
    space = TagSpace(terms=("a", "b"), vectors=np.array([[1.0, 0.0], [1.0, 0.0]]), meta={})
    assert [term for term, _ in cosine_all(space, np.array([1.0, 0.0]))] == ["a", "b"]


def test_cosine_all_scores_a_zero_vector_at_zero_everywhere_rather_than_nan():
    assert [score for _, score in cosine_all(a_space(), np.zeros(2))] == [0.0, 0.0, 0.0]


@pytest.mark.skipif(not SPACE_PATH.exists(), reason="space.json is gitignored")
def test_the_python_engine_reproduces_the_golden_trace_r_is_held_to():
    golden = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    space = load_space(SPACE_PATH, exclude=EXCLUDED_TERMS)

    # The trace records cosines, so it pins the algorithm AND the space it was taken against.
    # Without this check a rebuilt vocabulary reads as "the engine changed" and sends you
    # hunting in the wrong file.
    assert len(space.terms) == golden["space_terms"], (
        f"space.json has {len(space.terms)} terms, the trace was taken against "
        f"{golden['space_terms']} - regenerate with tools/build-engine-trace.R; "
        "the engine is not at fault"
    )

    events = json.loads(SESSION_PATH.read_text(encoding="utf-8"))["events"]
    state = session_new(space, decay=golden["decay"], w=golden["w"])
    for i, event in enumerate(events):
        state = session_step(state, event)
        top = cosine_all(space, state.v)[:5]
        expected = golden["steps"][i]
        assert [term for term, _ in top] == expected["terms"], f"step {i + 1} term order"
        assert [round(score, 6) for _, score in top] == pytest.approx(
            expected["cos"], abs=1e-6
        ), f"step {i + 1} cosines"
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_engine.py -q
```

Expected: `ModuleNotFoundError: No module named 'mldj.engine'`.

- [ ] **Step 3: Implement**

Create `src/mldj/engine.py`:

```python
"""The session vector, in Python. The third implementation of one algorithm.

    completed  v <- v*decay + w * sum(unit(tags))
    skipped    v <- v*decay - w * sum(unit(tags)) * earliness
    unknown    v <- v*decay

R/engine.R is the original and `fixtures/engine-trace.json` is the contract between them.
Phase 4's TypeScript engine will be held to the same trace, so this port takes the trace from
guarding two implementations to guarding three - it strengthens the artifact rather than
diluting it. Any change to the arithmetic here must be made in R/engine.R in the same commit,
and the trace regenerated deliberately with tools/build-engine-trace.R.

An unknown outcome decays without updating: an ambiguous record may not have been a skip, so
it cannot found a negative claim. A skipped event missing earliness is the same kind of
ambiguity, not a license to assume a full-strength penalty, so it raises.

Negative updates subtract the skipped track's own tag vector. The parent spec calls for
projecting along antonym-derived axes instead; that is Phase 2 work and it replaces exactly
the one line marked below. Say it in beat 6 rather than hiding it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from mldj.space.space import TagSpace
from mldj.space.vocab import canonical_tag

DEFAULT_DECAY = 0.85
DEFAULT_W = 1.0


@dataclass
class SessionState:
    space: TagSpace
    decay: float
    w: float
    v: np.ndarray
    history: list[Mapping[str, object]] = field(default_factory=list)


def _unit_rows(space: TagSpace) -> np.ndarray:
    """Every term vector scaled to unit length, a zero row left as zero.

    R/space.R precomputes this at load. Recomputing per call is a few hundred rows of
    arithmetic and keeps TagSpace frozen and cache-free.
    """
    norms = np.linalg.norm(space.vectors, axis=1)
    safe = np.where(norms == 0, 1.0, norms)
    return space.vectors / safe[:, None]


def tag_vector(space: TagSpace, tags: Sequence[str]) -> np.ndarray:
    """Sum of the unit vectors of the recognised tags.

    Unit-normalized before summing so a six-tag track does not outweigh a two-tag one by
    sheer count. TagSpace.compose sums RAW vectors and is therefore not a substitute here:
    it would change every cosine in the trace.

    Unknown tags are dropped rather than raised - Last.fm returns tags the vocabulary
    filtered out, routinely.
    """
    index = space.index
    rows = [index[canonical_tag(tag)] for tag in tags if canonical_tag(tag) in index]
    if not rows:
        return np.zeros(space.vectors.shape[1], dtype=np.float64)
    return _unit_rows(space)[rows].sum(axis=0)


def cosine_all(space: TagSpace, v: np.ndarray) -> list[tuple[str, float]]:
    """Every term scored against v, descending. Ties keep the space's own term order.

    R sorts with a stable sort, so ties fall back to term order; TagSpace.neighbours breaks
    them by term NAME instead. Copying that rule here would desynchronise the trace.

    A zero vector scores zero everywhere rather than producing NaN.
    """
    norm = float(np.linalg.norm(v))
    if norm == 0:
        return [(term, 0.0) for term in space.terms]
    scores = _unit_rows(space) @ (v / norm)
    order = sorted(range(len(space.terms)), key=lambda i: (-scores[i], i))
    return [(space.terms[i], float(scores[i])) for i in order]


def session_new(
    space: TagSpace, decay: float = DEFAULT_DECAY, w: float = DEFAULT_W
) -> SessionState:
    return SessionState(
        space=space,
        decay=decay,
        w=w,
        v=np.zeros(space.vectors.shape[1], dtype=np.float64),
    )


def session_step(state: SessionState, event: Mapping[str, object]) -> SessionState:
    v = state.v * state.decay
    outcome = event.get("outcome")
    tags = list(event.get("tags") or [])

    if outcome == "completed":
        v = v + state.w * tag_vector(state.space, tags)
    elif outcome == "skipped":
        if event.get("earliness") is None:
            raise ValueError("skipped event has no earliness - malformed source data")
        earliness = max(0.0, min(1.0, float(event["earliness"])))
        # <- Phase 2 replaces this line with a projection along antonym axes
        v = v - state.w * tag_vector(state.space, tags) * earliness
    elif outcome != "unknown":
        raise ValueError(
            f"unknown outcome {outcome!r} - expected completed, skipped or unknown"
        )

    state.v = v
    state.history.append(event)
    return state


def session_run(
    state: SessionState, events: Iterable[Mapping[str, object]]
) -> SessionState:
    for event in events:
        state = session_step(state, event)
    return state
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest tests/test_engine.py -q
```

Expected: all pass, with the parity test **running** rather than skipped — `space.json` exists
locally. If it is skipped, stop: the parity test is this task's entire justification, and a skip
means it proved nothing. Then confirm R still agrees:

```bash
"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R
```

Expected: `[ FAIL 0 | WARN 0 | SKIP 0 | PASS 244 ]`. **Do not regenerate the trace.** If parity
fails, the port is wrong — the trace is the thing being conformed to.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/engine.py tests/test_engine.py
git commit -m "feat: port the session engine to Python, held to the golden trace"
```

---

### Task 4: `mldj/library.py` — your own tracks, with URIs attached

The pool. Two endpoints, both paginated at 50, cached to disk because a large library is many
requests and nothing about it changes between two runs on the same session.

**Files:**
- Create: `src/mldj/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `Transport`, `Response`.
- Produces:
  - `LibraryTrack` frozen dataclass: `uri: str`, `artist: str`, `title: str`
  - `SAVED_URL`, `TOP_URL`, `LIBRARY_PATH = Path("data/library.json")`
  - `fetch_library(transport: Transport, access_token: Callable[[], str]) -> list[LibraryTrack]`
  - `write_library(path: Path, tracks: Sequence[LibraryTrack]) -> None`
  - `read_library(path: Path) -> list[LibraryTrack]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_library.py`:

```python
import json

from fakes import FakeTransport
from mldj.library import LibraryTrack, fetch_library, read_library, write_library
from mldj.transport import Response


def ok(payload: dict) -> Response:
    return Response(200, json.dumps(payload).encode())


def saved(name: str, artist: str, uri: str) -> dict:
    # /v1/me/tracks wraps each row in `track`; /v1/me/top/tracks does not. The shapes differ
    # and a reader that assumes one silently returns nothing for the other.
    return {"track": {"uri": uri, "name": name, "artists": [{"name": artist}]}}


def top(name: str, artist: str, uri: str) -> dict:
    return {"uri": uri, "name": name, "artists": [{"name": artist}]}


def test_fetch_library_follows_pagination_to_the_end():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": "https://api/next"}),
        ok({"items": [saved("B", "X", "spotify:track:2")], "next": None}),
        ok({"items": [], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert [t.title for t in tracks] == ["A", "B"]


def test_fetch_library_reads_both_the_saved_and_the_top_endpoints():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("B", "Y", "spotify:track:2")], "next": None}),
    ])
    tracks = fetch_library(transport, lambda: "tok")
    assert {t.title for t in tracks} == {"A", "B"}


def test_fetch_library_deduplicates_on_uri_because_a_top_track_is_usually_also_saved():
    transport = FakeTransport([
        ok({"items": [saved("A", "X", "spotify:track:1")], "next": None}),
        ok({"items": [top("A", "X", "spotify:track:1")], "next": None}),
    ])
    assert len(fetch_library(transport, lambda: "tok")) == 1


def test_fetch_library_skips_rows_that_are_not_playable_spotify_tracks():
    # Local files and podcast episodes both appear in a saved-tracks page and neither can be
    # added to a playlist by URI.
    transport = FakeTransport([
        ok({"items": [
            {"track": {"uri": "spotify:local:x", "name": "L", "artists": [{"name": "X"}]}},
            {"track": None},
            saved("A", "X", "spotify:track:1"),
        ], "next": None}),
        ok({"items": [], "next": None}),
    ])
    assert [t.uri for t in fetch_library(transport, lambda: "tok")] == ["spotify:track:1"]


def test_fetch_library_sends_the_bearer_token():
    transport = FakeTransport([
        ok({"items": [], "next": None}),
        ok({"items": [], "next": None}),
    ])
    fetch_library(transport, lambda: "tok")
    _method, _url, headers = transport.requests[0]
    assert headers["Authorization"] == "Bearer tok"


def test_the_library_round_trips_through_its_cache_file(tmp_path):
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    path = tmp_path / "library.json"
    write_library(path, tracks)
    assert read_library(path) == tracks
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_library.py -q
```

Expected: `ModuleNotFoundError: No module named 'mldj.library'`.

- [ ] **Step 3: Implement**

Create `src/mldj/library.py`:

```python
"""The candidate pool: your own Spotify library, with URIs already attached.

The prototype's pool comes from Last.fm artist.getSimilar, which yields NAMES. Turning a name
into something playable needs a search plus a fuzzy match, and on the output side a bad match
puts the wrong song in your playlist - a failure nothing downstream can detect. Reading your
own library instead means every candidate arrives with its URI, and that class of bug cannot
happen.

The cost is that it can only recommend music you already have. That is not a compromise: the
thesis is session adaptation, not discovery.

data/ is gitignored, and the cache lives there because it is a list of what one person listens
to.
"""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mldj.transport import Transport

SAVED_URL = "https://api.spotify.com/v1/me/tracks?limit=50"
TOP_URL = "https://api.spotify.com/v1/me/top/tracks?limit=50&time_range=medium_term"
LIBRARY_PATH = Path("data/library.json")
PLAYABLE_PREFIX = "spotify:track:"


@dataclass(frozen=True)
class LibraryTrack:
    uri: str
    artist: str
    title: str


def _row_to_track(row: object) -> LibraryTrack | None:
    """One page item, from either endpoint, or None when it is not a playable track.

    /v1/me/tracks wraps the track in `track`; /v1/me/top/tracks returns it bare. Local files
    and podcast episodes appear in saved tracks and cannot be added to a playlist by URI.
    """
    if not isinstance(row, dict):
        return None
    item = row.get("track", row)
    if not isinstance(item, dict):
        return None
    uri = str(item.get("uri") or "")
    title = str(item.get("name") or "")
    artists = item.get("artists") or []
    artist = str(artists[0].get("name") or "") if artists else ""
    if not uri.startswith(PLAYABLE_PREFIX) or not title or not artist:
        return None
    return LibraryTrack(uri, artist, title)


def _pages(
    transport: Transport, access_token: Callable[[], str], url: str
) -> Iterable[dict]:
    """Follow Spotify's `next` links until they run out."""
    while url:
        response = transport.get(url, {"Authorization": f"Bearer {access_token()}"})
        if response.status != 200:
            raise RuntimeError(f"{url} returned {response.status}: {response.body[:200]!r}")
        payload = response.json()
        if not isinstance(payload, dict):
            return
        yield payload
        url = str(payload.get("next") or "")


def fetch_library(
    transport: Transport, access_token: Callable[[], str]
) -> list[LibraryTrack]:
    """Saved tracks then top tracks, deduplicated on URI, in first-seen order.

    A top track is usually also a saved track, so the two sources overlap heavily. First-seen
    order means the saved-tracks ordering survives, which keeps a rerun's output stable.
    """
    seen: set[str] = set()
    tracks: list[LibraryTrack] = []
    for url in (SAVED_URL, TOP_URL):
        for page in _pages(transport, access_token, url):
            for row in page.get("items") or []:
                track = _row_to_track(row)
                if track is None or track.uri in seen:
                    continue
                seen.add(track.uri)
                tracks.append(track)
    return tracks


def write_library(path: Path, tracks: Sequence[LibraryTrack]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tracks": [asdict(track) for track in tracks]}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def read_library(path: Path) -> list[LibraryTrack]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [LibraryTrack(**row) for row in raw["tracks"]]
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest tests/test_library.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/library.py tests/test_library.py
git commit -m "feat: read the Spotify library as a candidate pool, URIs attached"
```

---

### Task 5: Tagging the library, and reporting coverage before anything is ranked

The spec's own risk: corpus tag coverage is 98.2% but the library is a different set and the
figure does not transfer. A low number means the ranking is uninformative, and that must be
visible rather than inferred from a disappointing playlist.

**This is where the cache-key mismatch is handled.** `lastfm._cache_path` hashes the raw
`artist\ttitle`, and the cache was filled from Last.fm's scrobble strings. The library's strings
come from Spotify. So the lookup goes through `match.track_key` — the same normalization the rest
of the project joins on.

**Decision, stated rather than assumed:** the default run reads the cache only and makes no
network call. A library track with no cached track-tier tags falls back to the artist tier, and
with neither it is **excluded and counted**, never entered at a zero vector. Pulling missing tags
from Last.fm is opt-in (`--pull-tags`, Task 9) because a 2,000-track library of mostly uncached
tracks is thousands of rate-limited requests and must not happen behind an unsuspecting run.

**Files:**
- Modify: `src/mldj/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `LibraryTrack` (Task 4), `match.track_key`, `match.normalize_artist`,
  `space.vocab.canonical_tag`, `lastfm._cache_path`, `lastfm._read_cached`.
- Produces:
  - `ScorableTrack` frozen dataclass: `uri: str`, `artist: str`, `title: str`,
    `tags: tuple[str, ...]`, `tier: str`, `novel: bool`
  - `LibraryCoverage` frozen dataclass: `tracks: int`, `track_tier: int`, `artist_tier: int`,
    `untagged: int`, plus properties `scorable: int` and `coverage: float`
  - `tag_library(tracks, track_tags, artist_tags, was_heard=None) -> tuple[list[ScorableTrack], LibraryCoverage]`
    where `track_tags: Mapping[tuple[str, str], Sequence[str]]` is keyed by `track_key` and
    `artist_tags: Mapping[str, Sequence[str]]` by `normalize_artist`
  - `cached_tag_index(tracks, tags_dir=TAGS_DIR, artist_tags_dir=ARTIST_TAGS_DIR) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]`
  - `render_coverage(coverage: LibraryCoverage) -> str`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_library.py`:

```python
from mldj.library import LibraryCoverage, render_coverage, tag_library
from mldj.match import track_key


def test_tag_library_finds_tags_through_the_normalized_key_not_the_raw_string():
    # The cache was filled from Last.fm's strings; the library carries Spotify's. "Blue Monday
    # - 2016 Remaster" and "Blue Monday" are one track, and only track_key knows that. A raw
    # string lookup here would report a well-tagged library as untagged.
    tracks = [LibraryTrack("spotify:track:1", "New Order", "Blue Monday - 2016 Remaster")]
    scorable, coverage = tag_library(
        tracks, {track_key("New Order", "Blue Monday"): ["newwave"]}, {}
    )
    assert [t.tags for t in scorable] == [("newwave",)]
    assert coverage.track_tier == 1


def test_tag_library_backs_off_to_the_artist_tier_and_records_the_tier():
    tracks = [LibraryTrack("spotify:track:1", "New Order", "Temptation")]
    scorable, coverage = tag_library(tracks, {}, {"neworder": ["newwave"]})
    assert scorable[0].tier == "artist"
    assert coverage.artist_tier == 1


def test_an_untaggable_track_is_excluded_and_counted_rather_than_scored_at_zero():
    # A zero vector entered at rank 0 invents a rank for a track nothing is known about, and
    # inflates the denominator of "ranked Nth of M".
    tracks = [LibraryTrack("spotify:track:1", "Nobody", "Untagged")]
    scorable, coverage = tag_library(tracks, {}, {})
    assert scorable == []
    assert coverage.untagged == 1


def test_tag_library_canonicalizes_tags_so_they_match_the_space_terms():
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    tagged = {track_key("X", "A"): ["New Wave", "", "Post-Punk"]}
    scorable, _ = tag_library(tracks, tagged, {})
    assert scorable[0].tags == ("newwave", "postpunk")


def test_novelty_comes_from_the_supplied_history_and_defaults_to_not_novel():
    tracks = [LibraryTrack("spotify:track:1", "X", "A")]
    tagged = {track_key("X", "A"): ["rock"]}
    heard, _ = tag_library(tracks, tagged, {}, was_heard=lambda a, t: True)
    unheard, _ = tag_library(tracks, tagged, {}, was_heard=lambda a, t: False)
    default, _ = tag_library(tracks, tagged, {})
    assert (heard[0].novel, unheard[0].novel, default[0].novel) == (False, True, False)


def test_coverage_reports_the_scorable_share_of_the_library():
    coverage = LibraryCoverage(tracks=4, track_tier=1, artist_tier=2, untagged=1)
    assert coverage.scorable == 3
    assert coverage.coverage == 0.75


def test_coverage_of_an_empty_library_is_zero_rather_than_a_division_error():
    assert LibraryCoverage(0, 0, 0, 0).coverage == 0.0


def test_render_coverage_names_every_tier_so_a_thin_pool_is_attributable():
    text = render_coverage(LibraryCoverage(tracks=4, track_tier=1, artist_tier=2, untagged=1))
    assert "4" in text and "track 1" in text and "artist 2" in text and "75.0%" in text
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_library.py -q
```

Expected: `ImportError: cannot import name 'LibraryCoverage' from 'mldj.library'`.

- [ ] **Step 3: Implement**

Add these imports to `src/mldj/library.py`:

```python
from mldj.lastfm import ARTIST_TAGS_DIR, TAGS_DIR, _cache_path, _read_cached
from mldj.match import normalize_artist, track_key
from mldj.space.vocab import canonical_tag
```

Then append:

```python
@dataclass(frozen=True)
class ScorableTrack:
    uri: str
    artist: str
    title: str
    tags: tuple[str, ...]
    tier: str
    novel: bool


@dataclass(frozen=True)
class LibraryCoverage:
    """How much of the library can be scored at all, by tier.

    Corpus coverage is 98.2%, but the library is a different set and that figure does not
    transfer. A low number here means the pool is thin and the ranking uninformative, which
    has to be visible before the playlist is written rather than inferred afterwards from a
    disappointing result.
    """

    tracks: int
    track_tier: int
    artist_tier: int
    untagged: int

    @property
    def scorable(self) -> int:
        return self.track_tier + self.artist_tier

    @property
    def coverage(self) -> float:
        return self.scorable / self.tracks if self.tracks else 0.0


def _canonical(tags: Sequence[str]) -> tuple[str, ...]:
    return tuple(t for t in (canonical_tag(tag) for tag in tags) if t)


def tag_library(
    tracks: Sequence[LibraryTrack],
    track_tags: Mapping[tuple[str, str], Sequence[str]],
    artist_tags: Mapping[str, Sequence[str]],
    was_heard: Callable[[str, str], bool] | None = None,
) -> tuple[list[ScorableTrack], LibraryCoverage]:
    """Attach tags to library rows, dropping what cannot be scored.

    Lookups go through match.track_key and normalize_artist, never raw strings: the tag cache
    was filled from Last.fm's names and these rows carry Spotify's. A raw lookup would miss
    every remaster suffix and report a well-tagged library as untagged.

    The artist-tier backoff is the same 24.5%-vs-95% trade export.session_events makes. It
    costs precision - artist-tier tags are identical for every track by that artist, so those
    tracks all score alike - and `tier` records it so the thinning and beat 6 can both say so.
    """
    scorable: list[ScorableTrack] = []
    track_tier = artist_tier = untagged = 0

    for track in tracks:
        tags = _canonical(track_tags.get(track_key(track.artist, track.title), ()))
        tier = "track"
        if not tags:
            tags = _canonical(artist_tags.get(normalize_artist(track.artist), ()))
            tier = "artist"
        if not tags:
            untagged += 1
            continue
        if tier == "track":
            track_tier += 1
        else:
            artist_tier += 1
        heard = was_heard(track.artist, track.title) if was_heard is not None else True
        scorable.append(
            ScorableTrack(
                uri=track.uri,
                artist=track.artist,
                title=track.title,
                tags=tags,
                tier=tier,
                novel=not heard,
            )
        )

    return scorable, LibraryCoverage(len(tracks), track_tier, artist_tier, untagged)


def cached_tag_index(
    tracks: Sequence[LibraryTrack],
    tags_dir: Path = TAGS_DIR,
    artist_tags_dir: Path = ARTIST_TAGS_DIR,
) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    """Tags for these tracks from the on-disk cache alone, making no request.

    The cache is keyed on the raw strings it was fetched with, so a library row can only hit
    it when the same raw strings were fetched. That is why the artist tier matters so much
    here: artist names diverge between Spotify and Last.fm far less than titles do.
    """
    track_tags: dict[tuple[str, str], list[str]] = {}
    artist_tags: dict[str, list[str]] = {}
    for track in tracks:
        rows = _read_cached(_cache_path(tags_dir, track.artist, track.title))
        if rows:
            track_tags[track_key(track.artist, track.title)] = [name for name, _ in rows]
        norm = normalize_artist(track.artist)
        if norm not in artist_tags:
            artist_rows = _read_cached(_cache_path(artist_tags_dir, track.artist, ""))
            if artist_rows:
                artist_tags[norm] = [name for name, _ in artist_rows]
    return track_tags, artist_tags


def render_coverage(coverage: LibraryCoverage) -> str:
    return (
        f"library: {coverage.tracks} tracks; tagged track {coverage.track_tier}, "
        f"artist {coverage.artist_tier}, none {coverage.untagged} "
        f"-> {coverage.coverage:.1%} scorable"
    )
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest tests/test_library.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/library.py tests/test_library.py
git commit -m "feat: tag the library through the normalized key, and report coverage first"
```

---

### Task 6: Ranking and thinning

Cosine against the final session vector, with the prototype's `ε · novelty` term so the two agree
on what "next" means, then capped per artist.

**Files:**
- Create: `src/mldj/playlist.py`
- Test: `tests/test_playlist.py`

**Interfaces:**
- Consumes: `engine.tag_vector` (Task 3), `ScorableTrack` (Task 5), `match.track_key`.
- Produces:
  - `Ranked` frozen dataclass: `rank: int`, `uri: str`, `artist: str`, `title: str`,
    `score: float`, `novel: bool`
  - `exclude_played(tracks: Sequence[ScorableTrack], events: Sequence[Mapping[str, object]]) -> list[ScorableTrack]`
  - `rank_library(space: TagSpace, v: np.ndarray, tracks: Sequence[ScorableTrack], epsilon: float = 0.0) -> list[Ranked]`
  - `thin_by_artist(ranked: Sequence[Ranked], limit: int, per_artist: int) -> list[Ranked]`
  - `DEFAULT_LIMIT = 30`, `DEFAULT_PER_ARTIST = 2`, `DEFAULT_EPSILON = 0.0`

- [ ] **Step 1: Write the failing test**

Create `tests/test_playlist.py`:

```python
import numpy as np
import pytest

from mldj.library import ScorableTrack
from mldj.playlist import Ranked, exclude_played, rank_library, thin_by_artist
from mldj.space.space import TagSpace


def a_space() -> TagSpace:
    return TagSpace(
        terms=("indie", "shoegaze"),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
        meta={},
    )


def track(uri: str, artist: str, title: str, tags=("indie",), novel=False) -> ScorableTrack:
    return ScorableTrack(uri, artist, title, tuple(tags), "track", novel)


def test_a_track_played_in_the_session_is_excluded_from_the_pool():
    # A session-adaptive playlist that opens with the track you just skipped is self-evidently
    # broken.
    tracks = [track("spotify:track:1", "X", "A"), track("spotify:track:2", "Y", "B")]
    events = [{"key": ["x", "a"]}]
    assert [t.title for t in exclude_played(tracks, events)] == ["B"]


def test_exclusion_joins_on_the_normalized_key_so_a_remaster_suffix_cannot_slip_through():
    tracks = [track("spotify:track:1", "New Order", "Blue Monday - 2016 Remaster")]
    events = [{"key": ["neworder", "bluemonday"]}]
    assert exclude_played(tracks, events) == []


def test_ranking_orders_by_cosine_against_the_session_vector():
    tracks = [
        track("spotify:track:1", "X", "Shoegazey", tags=("shoegaze",)),
        track("spotify:track:2", "Y", "Indieish", tags=("indie",)),
    ]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["Indieish", "Shoegazey"]
    assert [r.rank for r in ranked] == [1, 2]


def test_epsilon_lifts_a_novel_track_and_zero_epsilon_leaves_the_order_alone():
    tracks = [
        track("spotify:track:1", "X", "Known", tags=("indie",), novel=False),
        track("spotify:track:2", "Y", "New", tags=("shoegaze",), novel=True),
    ]
    v = np.array([1.0, 0.4])
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=0.0)] == ["Known", "New"]
    assert [r.title for r in rank_library(a_space(), v, tracks, epsilon=1.0)] == ["New", "Known"]


def test_a_zero_session_vector_scores_everything_at_zero_rather_than_nan():
    ranked = rank_library(a_space(), np.zeros(2), [track("spotify:track:1", "X", "A")])
    assert ranked[0].score == 0.0


def test_ties_keep_the_pool_order_so_a_rerun_produces_the_same_playlist():
    tracks = [track(f"spotify:track:{i}", "X", f"T{i}") for i in range(3)]
    ranked = rank_library(a_space(), np.array([1.0, 0.0]), tracks)
    assert [r.title for r in ranked] == ["T0", "T1", "T2"]


def test_thinning_caps_tracks_per_artist():
    # Artist-tier tags are identical across an artist's tracks, so they all score alike and a
    # stable sort keeps the block together. A 30-track playlist from six artists is the bug
    # the prototype's top_by_artist already found, wearing a different hat.
    ranked = [
        Ranked(1, "spotify:track:1", "X", "A", 0.9, False),
        Ranked(2, "spotify:track:2", "X", "B", 0.9, False),
        Ranked(3, "spotify:track:3", "X", "C", 0.9, False),
        Ranked(4, "spotify:track:4", "Y", "D", 0.5, False),
    ]
    assert [r.title for r in thin_by_artist(ranked, limit=10, per_artist=2)] == ["A", "B", "D"]


def test_thinning_returns_what_exists_rather_than_padding_to_the_limit():
    ranked = [Ranked(1, "spotify:track:1", "X", "A", 0.9, False)]
    assert len(thin_by_artist(ranked, limit=30, per_artist=2)) == 1


def test_thinning_stops_at_the_limit():
    ranked = [
        Ranked(i + 1, f"spotify:track:{i}", f"A{i}", f"T{i}", 1.0 - i / 10, False)
        for i in range(5)
    ]
    assert len(thin_by_artist(ranked, limit=3, per_artist=1)) == 3
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_playlist.py -q
```

Expected: `ModuleNotFoundError: No module named 'mldj.playlist'`.

- [ ] **Step 3: Implement**

Create `src/mldj/playlist.py`:

```python
"""Rank a library against a session vector and write the result as a new playlist.

The ranking uses the session's FINAL vector: one vector, one playlist. A per-step variant -
each track chosen against the vector as it stood - would narrate the session rather than
summarise it, and is the spec's deferred open question rather than an oversight.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from mldj.engine import tag_vector
from mldj.library import ScorableTrack
from mldj.match import track_key
from mldj.space.space import TagSpace

DEFAULT_LIMIT = 30
DEFAULT_PER_ARTIST = 2
DEFAULT_EPSILON = 0.0


@dataclass(frozen=True)
class Ranked:
    rank: int
    uri: str
    artist: str
    title: str
    score: float
    novel: bool


def exclude_played(
    tracks: Sequence[ScorableTrack], events: Sequence[Mapping[str, object]]
) -> list[ScorableTrack]:
    """The pool, minus every track the session played.

    Joined on the normalized key both sides already carry, so a remaster suffix cannot smuggle
    a just-skipped track back into the playlist.
    """
    played = {tuple(event.get("key") or ()) for event in events}
    return [t for t in tracks if track_key(t.artist, t.title) not in played]


def rank_library(
    space: TagSpace,
    v: np.ndarray,
    tracks: Sequence[ScorableTrack],
    epsilon: float = DEFAULT_EPSILON,
) -> list[Ranked]:
    """Every track scored by cosine against v, plus epsilon for a novel one, descending.

    Ties keep the pool's order - Python's sort is stable - so two runs on one session produce
    the same playlist. Novelty is an upper bound while the scrobble hole stands, so epsilon
    amplifies a number that is already generous: default it to zero.
    """
    norm = float(np.linalg.norm(v))
    scored: list[Ranked] = []
    for track in tracks:
        cv = tag_vector(space, track.tags)
        cnorm = float(np.linalg.norm(cv))
        cos = 0.0 if norm == 0 or cnorm == 0 else float(cv @ v / (cnorm * norm))
        scored.append(
            Ranked(
                0, track.uri, track.artist, track.title, cos + epsilon * track.novel,
                track.novel,
            )
        )
    ordered = sorted(scored, key=lambda r: -r.score)
    return [
        Ranked(i + 1, r.uri, r.artist, r.title, r.score, r.novel)
        for i, r in enumerate(ordered)
    ]


def thin_by_artist(ranked: Sequence[Ranked], limit: int, per_artist: int) -> list[Ranked]:
    """At most `per_artist` tracks by any one artist, then at most `limit` rows.

    Artist-tier tags are identical for every track by that artist, so every such track scores
    identically and a stable sort keeps the whole block together. Without this cap a 30-track
    playlist comes from six artists - the prototype measured exactly that on a real pool.

    Ranks are the true ones from the full pool. Renumbering would erase the gaps, and the gaps
    are the tie structure made visible.
    """
    counts: dict[str, int] = {}
    kept: list[Ranked] = []
    for row in ranked:
        if counts.get(row.artist, 0) >= per_artist:
            continue
        counts[row.artist] = counts.get(row.artist, 0) + 1
        kept.append(row)
        if len(kept) == limit:
            break
    return kept
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest tests/test_playlist.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/playlist.py tests/test_playlist.py
git commit -m "feat: rank the library against the session vector, thinned per artist"
```

---

### Task 7: Writing the playlist

The first thing in this project that writes to the account. Every run creates a new playlist and
never touches an existing one, so the worst case of a mistaken run is a stray private playlist.

**Files:**
- Modify: `src/mldj/playlist.py`
- Test: `tests/test_playlist.py`

**Interfaces:**
- Consumes: `Transport.post_json` (Task 1), `Ranked` (Task 6).
- Produces:
  - `PlaylistError(RuntimeError)`
  - `API = "https://api.spotify.com/v1"`, `ADD_CHUNK = 100`, `WRITE_SCOPES`
  - `current_user_id(transport, access_token) -> str`
  - `playlist_description(session: str, pool_size: int, decay: float, w: float, epsilon: float, meta: Mapping[str, object]) -> str`
  - `create_playlist(transport, access_token, user_id, name, description, on_unauthorized=None) -> str`
  - `add_tracks(transport, access_token, playlist_id, uris, on_unauthorized=None) -> int`
  - `publish_playlist(transport, access_token, *, name, description, uris, dry_run, on_unauthorized=None) -> str | None`
    — the whole write, or nothing at all. `dry_run` lives here rather than in `_run` so that
    "dry-run makes neither call" is a test rather than a promise.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_playlist.py`:

```python
import json

from fakes import FakeTransport
from mldj.playlist import (
    ADD_CHUNK,
    PlaylistError,
    add_tracks,
    create_playlist,
    current_user_id,
    playlist_description,
    publish_playlist,
)
from mldj.transport import Response


def ok(payload: dict) -> Response:
    return Response(200, json.dumps(payload).encode())


def test_create_playlist_posts_a_private_playlist_and_returns_its_id():
    transport = FakeTransport([ok({"id": "pl1"})])
    pid = create_playlist(transport, lambda: "tok", "me", "ml-dj - s1", "provenance")
    assert pid == "pl1"
    method, url, payload = transport.requests[0]
    assert (method, url) == ("POST_JSON", "https://api.spotify.com/v1/users/me/playlists")
    assert payload == {"name": "ml-dj - s1", "public": False, "description": "provenance"}


def test_add_tracks_chunks_at_the_api_limit():
    uris = [f"spotify:track:{i}" for i in range(ADD_CHUNK + 5)]
    transport = FakeTransport([ok({"snapshot_id": "a"}), ok({"snapshot_id": "b"})])
    assert add_tracks(transport, lambda: "tok", "pl1", uris) == ADD_CHUNK + 5
    assert len(transport.requests) == 2
    assert len(transport.requests[0][2]["uris"]) == ADD_CHUNK
    assert len(transport.requests[1][2]["uris"]) == 5


def test_add_tracks_makes_no_request_for_an_empty_list():
    transport = FakeTransport([])
    assert add_tracks(transport, lambda: "tok", "pl1", []) == 0
    assert transport.requests == []


def test_a_401_refreshes_once_and_retries():
    transport = FakeTransport([Response(401, b""), ok({"id": "pl1"})])
    refreshed = []
    pid = create_playlist(
        transport, lambda: "tok", "me", "n", "d",
        on_unauthorized=lambda: refreshed.append(True),
    )
    assert pid == "pl1"
    assert refreshed == [True]


def test_a_second_401_raises_rather_than_looping():
    transport = FakeTransport([Response(401, b""), Response(401, b"")])
    with pytest.raises(PlaylistError, match="401"):
        create_playlist(
            transport, lambda: "tok", "me", "n", "d", on_unauthorized=lambda: None
        )


def test_a_403_names_the_scope_because_forbidden_alone_sends_you_to_the_wrong_place():
    transport = FakeTransport([Response(403, b'{"error":{"message":"Forbidden"}}')])
    with pytest.raises(PlaylistError, match="playlist-modify-private"):
        create_playlist(transport, lambda: "tok", "me", "n", "d")


def test_current_user_id_reads_the_profile():
    transport = FakeTransport([ok({"id": "me"})])
    assert current_user_id(transport, lambda: "tok") == "me"
    assert transport.requests[0][1] == "https://api.spotify.com/v1/me"


def test_a_dry_run_makes_no_request_at_all_and_returns_no_playlist_id():
    # The guard the spec leans on when it makes --dry-run opt-in: the worst case of a mistaken
    # real run is a stray private playlist, and the worst case of a dry run is nothing.
    transport = FakeTransport([])
    result = publish_playlist(
        transport, lambda: "tok",
        name="n", description="d", uris=["spotify:track:1"], dry_run=True,
    )
    assert result is None
    assert transport.requests == []


def test_publishing_for_real_reads_the_profile_creates_the_playlist_and_adds_the_tracks():
    transport = FakeTransport([ok({"id": "me"}), ok({"id": "pl1"}), ok({"snapshot_id": "s"})])
    result = publish_playlist(
        transport, lambda: "tok",
        name="n", description="d", uris=["spotify:track:1"], dry_run=False,
    )
    assert result == "pl1"
    assert [r[0] for r in transport.requests] == ["GET", "POST_JSON", "POST_JSON"]


def test_the_description_records_what_produced_the_playlist():
    # A playlist that cannot say which space produced it is not reproducible, and the space is
    # rebuilt often enough for that to matter: the 2026-09-30 stoplist moved the vocabulary
    # from 371 terms to 323 and shifted every cosine.
    text = playlist_description(
        "dj-20260930T142116Z", 1504, 0.85, 1.0, 0.0,
        {"vocabulary_size": 323, "built_utc": "2026-09-30T10:19:00+00:00"},
    )
    for fragment in ("dj-20260930T142116Z", "1504", "0.85", "323", "2026-09-30"):
        assert fragment in text
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_playlist.py -q
```

Expected: `ImportError: cannot import name 'ADD_CHUNK' from 'mldj.playlist'`.

- [ ] **Step 3: Implement**

Widen the `collections.abc` import in `src/mldj/playlist.py` to
`from collections.abc import Callable, Mapping, Sequence` (Task 6 added the last two), add
`from mldj.transport import Response, Transport`, then append:

```python
API = "https://api.spotify.com/v1"
ADD_CHUNK = 100  # Spotify's per-request ceiling for playlist additions
WRITE_SCOPES = "playlist-modify-private, user-library-read, user-top-read"


class PlaylistError(RuntimeError):
    pass


def _headers(access_token: Callable[[], str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token()}"}


def _check(response: Response, url: str) -> Response:
    if response.status == 403:
        raise PlaylistError(
            f"403 Forbidden from {url}. This is almost always a missing scope rather than a "
            f"bad request: the token needs {WRITE_SCOPES}. Widening SCOPE invalidates the "
            "cached token, so delete data/.spotify-tokens.json and re-run to re-authorize - "
            "between capture sessions, never during one."
        )
    if response.status >= 400 or response.status == 0:
        raise PlaylistError(f"{response.status} from {url}: {response.body[:200]!r}")
    return response


def _post_json(
    transport: Transport,
    access_token: Callable[[], str],
    url: str,
    payload: Mapping[str, object],
    on_unauthorized: Callable[[], None] | None = None,
) -> Response:
    """POST, refreshing and retrying exactly once on a 401.

    Once, not in a loop: a 401 that survives a refresh is a bad or revoked token, and retrying
    further only hides that behind a hang.
    """
    response = transport.post_json(url, payload, _headers(access_token))
    if response.status == 401 and on_unauthorized is not None:
        on_unauthorized()
        response = transport.post_json(url, payload, _headers(access_token))
    return _check(response, url)


def current_user_id(transport: Transport, access_token: Callable[[], str]) -> str:
    """The account's id, needed to address the playlist-creation endpoint.

    If this ever 403s, the token is missing `user-read-private`; add it to auth.SCOPE rather
    than guessing at the playlist endpoint.
    """
    url = f"{API}/me"
    payload = _check(transport.get(url, _headers(access_token)), url).json()
    if not isinstance(payload, dict) or not payload.get("id"):
        raise PlaylistError(f"{url} returned no id")
    return str(payload["id"])


def playlist_description(
    session: str,
    pool_size: int,
    decay: float,
    w: float,
    epsilon: float,
    meta: Mapping[str, object],
) -> str:
    """Provenance, in the one field that travels with the playlist.

    A playlist that cannot say which space produced it is not reproducible, and the space is
    rebuilt often enough for that to matter.
    """
    built = str(meta.get("built_utc", "unknown"))
    return (
        f"ml-dj · session {session}; pool {pool_size}; decay {decay}, w {w}, "
        f"epsilon {epsilon}; space {meta.get('vocabulary_size', '?')} terms built {built}"
    )


def create_playlist(
    transport: Transport,
    access_token: Callable[[], str],
    user_id: str,
    name: str,
    description: str,
    on_unauthorized: Callable[[], None] | None = None,
) -> str:
    """Create a NEW private playlist and return its id.

    Never updates an existing playlist. Appending to or rewriting one the listener may have
    edited is destructive with no undo, and the saving in clutter does not buy that class of
    bug.
    """
    url = f"{API}/users/{user_id}/playlists"
    payload = {"name": name, "public": False, "description": description}
    body = _post_json(transport, access_token, url, payload, on_unauthorized).json()
    if not isinstance(body, dict) or not body.get("id"):
        raise PlaylistError(f"{url} returned no playlist id")
    return str(body["id"])


def add_tracks(
    transport: Transport,
    access_token: Callable[[], str],
    playlist_id: str,
    uris: Sequence[str],
    on_unauthorized: Callable[[], None] | None = None,
) -> int:
    """Add the URIs in order, chunked at the API's limit. Returns how many were added."""
    url = f"{API}/playlists/{playlist_id}/tracks"
    for start in range(0, len(uris), ADD_CHUNK):
        chunk = list(uris[start : start + ADD_CHUNK])
        _post_json(transport, access_token, url, {"uris": chunk}, on_unauthorized)
    return len(uris)


def publish_playlist(
    transport: Transport,
    access_token: Callable[[], str],
    *,
    name: str,
    description: str,
    uris: Sequence[str],
    dry_run: bool,
    on_unauthorized: Callable[[], None] | None = None,
) -> str | None:
    """The whole write, or nothing at all. Returns the playlist id, or None for a dry run.

    `dry_run` lives here rather than in the argparse handler so that "a dry run makes neither
    call" is a test rather than a promise - it is the guard the spec leans on when it makes
    --dry-run opt-in rather than the default.
    """
    if dry_run:
        return None
    user_id = current_user_id(transport, access_token)
    playlist_id = create_playlist(
        transport, access_token, user_id, name, description, on_unauthorized
    )
    add_tracks(transport, access_token, playlist_id, uris, on_unauthorized)
    return playlist_id
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest tests/test_playlist.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/playlist.py tests/test_playlist.py
git commit -m "feat: create a new private playlist and add the ranked tracks"
```

---

### Task 8: Widening the token, and only by what is needed

**Operational warning, and it is the reason this task is here rather than first:** widening `SCOPE`
invalidates `data/.spotify-tokens.json`. The next command needing a token re-runs the PKCE
browser flow. **Capture is the long pole, so do this between sessions, never during
one** — if a capture is running, finish this task after it stops.

**Files:**
- Modify: `src/mldj/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `auth.SCOPE` as a space-separated four-scope string.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_auth.py`:

```python
from mldj.auth import SCOPE


def test_the_token_carries_exactly_the_scopes_the_project_needs():
    assert set(SCOPE.split()) == {
        "user-read-currently-playing",
        "playlist-modify-private",
        "user-library-read",
        "user-top-read",
    }


def test_the_token_never_carries_playback_control():
    # Nothing in this project touches playback. The narrower the token, the smaller the blast
    # radius of a bug in a tool that is one typo from writing to a real account. Queue writing
    # is Phase 4 and stays out until the pitch is delivered.
    assert "user-modify-playback-state" not in SCOPE
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_auth.py -q
```

Expected: the first test fails — `SCOPE` is the single read scope.

- [ ] **Step 3: Implement**

In `src/mldj/auth.py`, replace the `SCOPE` line:

```python
# Capture reads what is playing; `mldj playlist` reads the library and creates one playlist.
# user-modify-playback-state is deliberately absent: nothing here touches playback, and the
# narrower the token the smaller the blast radius of a bug in a tool that is one typo from
# writing to a real account. Queue writing is Phase 4, after the pitch.
SCOPE = " ".join(
    (
        "user-read-currently-playing",  # capture
        "playlist-modify-private",  # playlist creation
        "user-library-read",  # /v1/me/tracks
        "user-top-read",  # /v1/me/top/tracks
    )
)
```

And replace the module docstring's last paragraph with:

```
Phase 0 reads what is playing. `mldj playlist` adds three scopes - the two library reads and
playlist-modify-private - and that is the whole widening. Do not add
user-modify-playback-state: queue writing is Phase 4, after the pitch. Widening SCOPE
invalidates the cached token and forces the PKCE flow again, so change it between capture
sessions, never during one.
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git status --porcelain
git add src/mldj/auth.py tests/test_auth.py
git commit -m "feat: widen the token by three scopes, and not by playback control"
```

---

### Task 9: `mldj playlist` — the subcommand, and a real run

**Files:**
- Modify: `src/mldj/playlist.py`
- Modify: `src/mldj/cli.py`
- Modify: `docs/superpowers/plans/2026-10-02-playlist-export.md` (record what the real run showed)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `playlist.register(subparsers) -> None`, `playlist._run(args) -> int`, and
  `playlist.force_refresh(transport, clock, client_id, path=None) -> None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_the_playlist_subcommand_is_registered_with_its_defaults():
    from mldj.cli import build_parser

    args = build_parser().parse_args(["playlist", "--session", "data/exports/s.json"])
    assert args.command == "playlist"
    assert (args.limit, args.per_artist, args.epsilon) == (30, 2, 0.0)
    assert (args.decay, args.w) == (0.85, 1.0)
    assert args.dry_run is False
    assert args.refresh_library is False
    assert args.pull_tags is False
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_cli.py -q
```

Expected: an `argparse` error — `invalid choice: 'playlist'`.

- [ ] **Step 3: Implement**

Add `from collections import Counter` and widen the engine import to
`from mldj.engine import DEFAULT_DECAY, DEFAULT_W, tag_vector`, and the library import to
`from mldj.library import LIBRARY_PATH, ScorableTrack`. Then append to `src/mldj/playlist.py`:

```python
def force_refresh(transport: Transport, clock, client_id: str, path=None) -> None:
    """Refresh the access token now, rather than waiting for the expiry margin.

    token_provider refreshes on a clock; a 401 mid-run means the token is dead regardless of
    what the clock says.
    """
    from mldj.auth import TOKENS_PATH, load_tokens, refresh_tokens, save_tokens

    path = TOKENS_PATH if path is None else path
    tokens = load_tokens(path)
    if tokens is None:
        raise PlaylistError("no cached token to refresh - run any command to authorize")
    save_tokens(refresh_tokens(transport, clock, client_id, tokens), path)


def _run(args) -> int:
    import json
    from pathlib import Path

    from mldj.auth import token_provider
    from mldj.clock import SystemClock
    from mldj.engine import session_new, session_run
    from mldj.env import load_env, require
    from mldj.library import (
        cached_tag_index,
        fetch_library,
        read_library,
        render_coverage,
        tag_library,
        write_library,
    )
    from mldj.measure.novelty import build_history
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.space.space import DEFAULT_SPACE_PATH, EXCLUDED_TERMS, load_space
    from mldj.transport import UrllibTransport

    export = Path(args.session)
    if not export.exists():
        raise SystemExit(f"no export at {export} - run `mldj export-session` first")
    payload = json.loads(export.read_text(encoding="utf-8"))
    events = payload["events"]

    space = load_space(DEFAULT_SPACE_PATH, exclude=EXCLUDED_TERMS)
    transport = UrllibTransport()
    clock = SystemClock()
    env = load_env()
    client_id = require(env, "SPOTIFY_CLIENT_ID")
    access_token = token_provider(transport, clock, client_id)

    library_path = Path(args.library)
    if args.refresh_library or not library_path.exists():
        tracks = fetch_library(transport, access_token)
        write_library(library_path, tracks)
        print(f"{library_path}: {len(tracks)} library tracks")
    else:
        tracks = read_library(library_path)
        print(
            f"{library_path}: {len(tracks)} library tracks "
            "(cached; --refresh-library to refetch)"
        )

    if args.pull_tags:
        print("--pull-tags is not implemented; this run reads the tag cache only")

    track_tags, artist_tags = cached_tag_index(tracks)
    history = build_history(read_scrobbles(SCROBBLES_PATH))
    scorable, coverage = tag_library(
        tracks, track_tags, artist_tags, lambda a, t: history.contains(a, t)
    )
    # Coverage before ranking, per the spec: a thin pool must be visible here rather than
    # inferred later from a disappointing playlist.
    print(render_coverage(coverage))

    pool = exclude_played(scorable, events)
    outcomes = Counter(str(e.get("outcome")) for e in events)
    print(f"session {payload['session']}: {len(events)} events {dict(outcomes)}")
    print(f"pool: {len(pool)} candidates after dropping what the session played")

    state = session_run(session_new(space, decay=args.decay, w=args.w), events)
    ranked = rank_library(space, state.v, pool, epsilon=args.epsilon)
    chosen = thin_by_artist(ranked, limit=args.limit, per_artist=args.per_artist)

    for row in chosen:
        flag = " *novel" if row.novel else ""
        print(f"  {row.rank:>4}  {row.score:+.4f}  {row.artist} - {row.title}{flag}")

    if args.dry_run:
        print(f"--dry-run: {len(chosen)} tracks, nothing created")
        return 0

    name = args.name or f"ml-dj · {payload['session']}"
    description = playlist_description(
        payload["session"], len(pool), args.decay, args.w, args.epsilon, space.meta
    )

    def on_unauthorized() -> None:
        force_refresh(transport, clock, client_id)

    playlist_id = publish_playlist(
        transport,
        access_token,
        name=name,
        description=description,
        uris=[r.uri for r in chosen],
        dry_run=False,
        on_unauthorized=on_unauthorized,
    )
    print(
        f"created {name}: {len(chosen)} tracks - "
        f"https://open.spotify.com/playlist/{playlist_id}"
    )
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("playlist", help="turn a session into a private playlist")
    p.add_argument("--session", required=True, help="path to a `mldj export-session` JSON file")
    p.add_argument("--name", default=None, help="playlist name; default ml-dj · <session>")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--per-artist", type=int, default=DEFAULT_PER_ARTIST)
    p.add_argument("--decay", type=float, default=DEFAULT_DECAY)
    p.add_argument("--w", type=float, default=DEFAULT_W)
    p.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    p.add_argument("--library", default=str(LIBRARY_PATH))
    p.add_argument("--refresh-library", action="store_true", help="refetch instead of caching")
    p.add_argument("--pull-tags", action="store_true", help="reserved; not implemented")
    p.add_argument("--dry-run", action="store_true", help="print the tracklist, create nothing")
    p.set_defaults(handler=_run)
```

In `src/mldj/cli.py`, add `playlist` to the module import line and
`playlist.register(subparsers)` after `candidates.register(subparsers)`.

- [ ] **Step 4: Run the tests, then run it for real**

```bash
.venv\Scripts\python.exe -m pytest -q
"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R
```

Expected: both suites green, nothing skipped.

Then, **with no capture running** (Task 8 invalidated the token, so this re-runs the browser
flow), dry-run first:

```bash
.venv\Scripts\python.exe -m mldj playlist --session data/exports/<name>.json --dry-run
git status --porcelain
```

Expected: a coverage line, a pool size, up to 30 rows. **`git status` must show nothing under
`data/`** — `data/library.json` is a new path, so confirm `.gitignore` covers it before going
further. Then, for real:

```bash
.venv\Scripts\python.exe -m mldj playlist --session data/exports/<name>.json
```

- [ ] **Step 5: Record what the real run showed, and commit**

Write into this plan, below this task: the library size, the coverage figure by tier, the pool
size after exclusions, whether the 30 picks read as a listenable set or as one artist wearing
hats, and whether the artist-tier share is high enough that the ranking is really responding to
artists rather than to tracks. **A disappointing result is a finding, not something to hide** —
beat 6 is graded on honesty.

```bash
git status --porcelain
git add src/mldj/playlist.py src/mldj/cli.py tests/test_cli.py \
  docs/superpowers/plans/2026-10-02-playlist-export.md
git commit -m "feat: mldj playlist - a session as a private Spotify playlist"
```

---

## Definition of done

- [ ] `.venv\Scripts\python.exe -m pytest -q` passes with nothing skipped
- [ ] `"C:\Program Files\R\R-4.5.3\bin\Rscript.exe" run-tests.R` still passes — R was not touched
- [ ] The Python engine reproduces `fixtures/engine-trace.json`, and that test **ran** rather than
      skipping for a missing `space.json`
- [ ] `git status --porcelain` shows nothing under `data/`, `data/library.json` included
- [ ] `space.json` is still uncommitted
- [ ] None of `radiohead`, `kanyewest`, `kendricklamar`, `timbaland` can reach any surface
- [ ] `auth.SCOPE` carries four scopes and not `user-modify-playback-state`
- [ ] A real playlist exists in the account, created from a real captured session
- [ ] Library tag coverage is recorded in this plan, by tier
- [ ] No existing playlist was modified by any run

## Deferred, deliberately

- **The per-step vector** — ranking each slot against the vector as it stood rather than against
  the final one. Spec open question 1: a playlist that narrates the session rather than
  summarising it. A different and larger design.
- **`--pull-tags`** — fetching Last.fm tags for library tracks the cache has never seen. The flag
  is registered and prints that it is unimplemented, so a run is never silently different from
  what was asked. Worth building only if Task 9's coverage figure comes back low.
- **A Last.fm discovery pool** as a second, separately labelled source. Out of scope by the spec.
- **Queue writes and playback control.** One endpoint away, and they stay out until the pitch is
  delivered.

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

    Deduplicated by canonical term, first occurrence kept: R's equivalent is
    `intersect(tags, space$terms)`, and R's `intersect` returns unique matches, so a tag list
    with the same canonical term twice (e.g. "Hip-Hop" and "hip hop") must count it once here
    too, or Python and R diverge on real Last.fm data that is routinely this repetitive. Do
    not "optimize" this dedupe away - the two ports must keep matching.
    """
    index = space.index
    seen: set[int] = set()
    rows: list[int] = []
    for tag in tags:
        term = canonical_tag(tag)
        i = index.get(term)
        if i is not None and i not in seen:
            seen.add(i)
            rows.append(i)
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
    """The state after one event. The input state is left untouched.

    R's version copies on assignment, so returning a new state is what actually matches it -
    mutating in place would alias every step to one object and make a list of per-step states
    impossible. R's scrubber keeps exactly such a list, and the spec's deferred per-step
    ranking would need one too.
    """
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

    return SessionState(
        space=state.space,
        decay=state.decay,
        w=state.w,
        v=v,
        history=[*state.history, event],
    )


def session_run(
    state: SessionState, events: Iterable[Mapping[str, object]]
) -> SessionState:
    for event in events:
        state = session_step(state, event)
    return state

"""TagSpace: the queryable space, and the versioned file that crosses into TypeScript.

`space.json` is the whole boundary between the two halves of the project - Python trains,
TypeScript serves - so it carries everything the live client needs and nothing else.

**`compose` is the session vector's primitive** and lives here rather than in Phase 3,
because it is a property of the space, not of the engine. A weighted sum of tag vectors is
compositional distributional semantics in one line: a played-through track adds its tags, a
skip subtracts them, and "what I want right now" is the result. Negative weights are
therefore first-class, not an edge case.

**The privacy gate.** CLAUDE.md permits committing `space.json` only if it *provably*
contains no raw listening history, and "provably" means a test rather than a glance. The
export holds tag strings and floats - no titles, no timestamps, no per-item counts. That
leaves one real leak: Last.fm users tag tracks with artist names, so a term like
`Fleetwood Mac` can survive into the vocabulary and publish who the listener listens to.
`leaking_terms` is the check, and it compares canonical forms so a difference in spacing or
case cannot slip past.

**Meta is mandatory, not decorative.** A space whose build settings are unknown cannot be
rebuilt, so an evaluation run against it cannot be defended. `save_space` refuses to write
without every key in REQUIRED_META - including `seed`, because the real matrix's spectrum is
near-degenerate and the basis is only reproducible per-seed.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mldj.space.vocab import canonical_tag

SPACE_FORMAT_VERSION = 1
DEFAULT_SPACE_PATH = Path("space.json")

# Everything needed to rebuild the space from the corpus. `built_utc` is added on save.
REQUIRED_META = (
    "rank",
    "eigenvalue_weighting",
    "shift",
    "context_smoothing",
    "min_count",
    "min_artists",
    "include_artists",
    "seed",
    "vocabulary_size",
    "item_counts",
    "tier_counts",
)


@dataclass(frozen=True)
class TagSpace:
    terms: tuple[str, ...]
    vectors: np.ndarray  # shape (len(terms), rank)
    meta: Mapping[str, object]
    display: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.vectors.shape[0] != len(self.terms):
            raise ValueError(
                f"vectors has {self.vectors.shape[0]} rows for {len(self.terms)} terms"
            )

    @property
    def index(self) -> dict[str, int]:
        return {term: i for i, term in enumerate(self.terms)}

    def _row(self, tag: str) -> int | None:
        return self.index.get(canonical_tag(tag))

    def vector(self, tag: str) -> np.ndarray | None:
        """The tag's vector, or None when the space does not hold it."""
        row = self._row(tag)
        return None if row is None else self.vectors[row]

    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity. Zero when either tag is absent, or either vector is zero."""
        first, second = self.vector(a), self.vector(b)
        if first is None or second is None:
            return 0.0
        norms = float(np.linalg.norm(first) * np.linalg.norm(second))
        return float(first @ second / norms) if norms else 0.0

    def neighbours(self, tag: str, k: int = 10) -> list[tuple[str, float]]:
        """The k most similar other tags, descending. Empty when the tag is absent."""
        row = self._row(tag)
        if row is None:
            return []
        norms = np.linalg.norm(self.vectors, axis=1)
        safe = np.where(norms == 0, 1.0, norms)
        sims = (self.vectors @ self.vectors[row]) / (safe * safe[row])
        # Ties are broken by term so the ordering is fully determined; np.argsort makes no
        # promise there, and a neighbour list that reorders between runs would make any
        # report built from it irreproducible.
        pairs = [
            (self.terms[i], float(sims[i]))
            for i in range(len(self.terms))
            if i != row and np.isfinite(sims[i])
        ]
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return pairs[:k]

    def compose(
        self, tags: Sequence[str], weights: Sequence[float] | None = None
    ) -> np.ndarray:
        """Weighted sum of tag vectors - the session vector, in one operation.

        Unknown tags are skipped with their weight, so dropping a tag never silently
        reassigns its weight to the next one.
        """
        if weights is not None and len(weights) != len(tags):
            raise ValueError(
                f"weights has {len(weights)} entries for {len(tags)} tags; they must match"
            )
        total = np.zeros(self.vectors.shape[1], dtype=np.float64)
        for position, tag in enumerate(tags):
            vector = self.vector(tag)
            if vector is None:
                continue
            total += vector * (1.0 if weights is None else float(weights[position]))
        return total


def leaking_terms(space: TagSpace, forbidden: set[str]) -> list[str]:
    """Terms whose canonical form matches a name the export should not be publishing.

    **Pass artist names only, never track titles.** Titles are frequently single ordinary
    words - `Love`, `Happy`, `Disco`, `Summer`, `Perfect` - so comparing against them flags
    about 25 pure false positives on the real corpus and makes the check useless.

    **This produces a review list, not a verdict.** A tag matching an artist name is usually
    a genuine leak: Last.fm users tag tracks with the artist, so `radiohead` in the export
    publishes who the listener listens to. But bands named with ordinary words - Electronic,
    Love, fun., Lush - are indistinguishable from descriptors by string comparison, and
    dropping `love` or `electronic` would gut the vocabulary. No mechanical rule separates
    them, and the decision carries privacy consequences, so a person confirms each one.

    Raising `min_artists` is the blunter but principled lever: on the real corpus it cuts
    matches from 19 at 2 to 9 at 3, of which only about 5 are real.

    Canonical forms are compared, so a difference in spacing or case cannot hide a match.
    """
    banned = {canonical_tag(item) for item in forbidden}
    banned.discard("")
    leaks = []
    for term in space.terms:
        shown = space.display.get(term, term)
        if canonical_tag(shown) in banned or canonical_tag(term) in banned:
            leaks.append(shown)
    return leaks


def save_space(space: TagSpace, path: Path = DEFAULT_SPACE_PATH) -> None:
    """Write the versioned export, refusing to produce one that cannot be reproduced."""
    missing = [key for key in REQUIRED_META if key not in space.meta]
    if missing:
        raise ValueError(
            f"meta is missing {', '.join(missing)}; a space whose build settings are "
            "unknown cannot be rebuilt, so an evaluation against it cannot be defended"
        )

    payload = {
        "format_version": SPACE_FORMAT_VERSION,
        "meta": {**space.meta, "built_utc": datetime.now(UTC).isoformat()},
        "terms": list(space.terms),
        "display": dict(space.display),
        # repr of a float round-trips exactly in both Python and JavaScript, so json's
        # default float encoding is enough; no precision is lost crossing the boundary.
        "vectors": [[float(value) for value in row] for row in space.vectors],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_space(path: Path = DEFAULT_SPACE_PATH) -> TagSpace:
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("format_version")
    if version != SPACE_FORMAT_VERSION:
        raise ValueError(
            f"format_version {version!r} is not the expected {SPACE_FORMAT_VERSION}; "
            "rebuild the space rather than reading it with the wrong reader"
        )
    return TagSpace(
        terms=tuple(raw["terms"]),
        vectors=np.array(raw["vectors"], dtype=np.float64),
        meta=raw["meta"],
        display=raw.get("display", {}),
    )

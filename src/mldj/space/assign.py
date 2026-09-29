"""Give every track a tag set, and record where those tags came from.

Measured coverage forces this: about 24.5% of distinct tracks carry Last.fm tags of their
own, against about 95% of artists. Phase 3 needs a vector for every candidate, so the other
75% have to inherit - **track tags, then tagged album siblings, then artist tags**. An
untagged LCD Soundsystem album track is far better described by its album-mates than by
nothing, and better by its album-mates than by the artist's whole career.

**The tier is recorded, and that is load-bearing rather than bookkeeping:**

- Phase 0's post-skip persistence compares two tracks' tags. If both inherited from the
  same artist their overlap is 1.0 *by construction*, so that metric must count only
  track-tier pairs or it measures this module instead of the DJ. `track_tier_keys` is what
  it filters on.
- The learning matrix (Task 4) uses **only** track-tier assignments. Letting every track by
  one artist carry that artist's tags would have PPMI read a single human annotation as
  hundreds of independent observations, and the space would learn the shape of this backoff
  rather than a fact about language.
- Phase 3 needs to tell mellow LCD Soundsystem from dancey LCD Soundsystem, which is
  impossible for two tracks holding one inherited vector. Knowing a vector is inherited is
  what lets the session engine discount it.
- "N of 5,831 tracks have no tags of their own" is a beat 6 number, and only sayable if the
  tiers are counted.

An empty album string is **not** an album. Pooling on it would join every album-less track
by an artist into one bucket, which is the artist tier wearing a disguise - and it would
report as `album` provenance, hiding how coarse the evidence really is.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from mldj.match import normalize_artist
from mldj.scrobbles import Scrobble
from mldj.space.vocab import Vocabulary, canonical_tag
from mldj.tags import TrackKey, index_corpus

Tier = Literal["track", "album", "artist", "none"]
TIERS: tuple[Tier, ...] = ("track", "album", "artist", "none")
DEFAULT_TOP_N = 10

TagRows = Sequence[tuple[str, int]]


@dataclass(frozen=True)
class TrackTags:
    key: TrackKey
    tags: tuple[str, ...]
    tier: Tier
    source: str  # human-readable provenance, for auditing a surprising vector


def usable_tags(
    rows: TagRows | None, vocab: Vocabulary, top_n: int = DEFAULT_TOP_N
) -> tuple[str, ...]:
    """Canonicalize, drop anything outside the vocabulary, dedupe, cap at top_n.

    Rows arrive sorted by Last.fm count, and that order is kept: it is the only signal of
    which tags the crowd thought mattered most.
    """
    kept: list[str] = []
    for name, _ in rows or ():
        term = canonical_tag(name)
        if term and term in vocab.index and term not in kept:
            kept.append(term)
            if len(kept) >= top_n:
                break
    return tuple(kept)


def assign_tags(
    scrobbles: Iterable[Scrobble],
    track_tags: Mapping[TrackKey, TagRows],
    artist_tags: Mapping[str, TagRows],
    vocab: Vocabulary,
    top_n: int = DEFAULT_TOP_N,
) -> dict[TrackKey, TrackTags]:
    """One TrackTags per distinct track, with its tier and provenance."""
    index = index_corpus(scrobbles)

    # Track-tier resolution first: album pooling needs to know which siblings are usable,
    # and a tag outside the vocabulary is no tag at all for that purpose.
    own = {key: usable_tags(track_tags.get(key), vocab, top_n) for key in index.track_reps}

    # Albums are keyed by (normalized artist, album) so two artists sharing an album title
    # never pool into each other.
    by_album: dict[tuple[str, str], list[TrackKey]] = {}
    for key, (artist, _) in index.track_reps.items():
        album = index.album_of.get(key, "")
        if album:
            by_album.setdefault((normalize_artist(artist), album), []).append(key)

    assignments: dict[TrackKey, TrackTags] = {}
    for key, (artist, _) in index.track_reps.items():
        if own[key]:
            assignments[key] = TrackTags(key, own[key], "track", "own tags")
            continue

        album = index.album_of.get(key, "")
        if album:
            siblings = [
                sibling
                for sibling in by_album[(normalize_artist(artist), album)]
                if sibling != key and own[sibling]
            ]
            if siblings:
                # Rank by how many siblings carry the tag, then alphabetically so the result
                # is deterministic rather than dict-order dependent.
                shared: Counter[str] = Counter(t for s in siblings for t in own[s])
                pooled = tuple(
                    sorted(shared, key=lambda term: (-shared[term], term))[:top_n]
                )
                assignments[key] = TrackTags(
                    key,
                    pooled,
                    "album",
                    f"album {album!r}, {len(siblings)} tagged sibling(s)",
                )
                continue

        inherited = usable_tags(artist_tags.get(normalize_artist(artist)), vocab, top_n)
        if inherited:
            assignments[key] = TrackTags(key, inherited, "artist", f"artist {artist!r}")
            continue

        assignments[key] = TrackTags(key, (), "none", "no tags at any tier")

    return assignments


def tier_counts(assignments: Mapping[TrackKey, TrackTags]) -> dict[str, int]:
    """Every tier present, zeros included, so a report never omits an empty one."""
    counts = Counter(a.tier for a in assignments.values())
    return {tier: counts.get(tier, 0) for tier in TIERS}


def track_tier_keys(assignments: Mapping[TrackKey, TrackTags]) -> set[TrackKey]:
    """Tracks with tags genuinely their own.

    The learning matrix is built from exactly these, and Phase 0's tag-persistence metric
    counts only transitions where both sides are in here.
    """
    return {key for key, a in assignments.items() if a.tier == "track"}

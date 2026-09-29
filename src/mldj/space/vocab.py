"""Tag vocabulary normalization - the folksonomy problem, handled conservatively.

Last.fm tags are an uncontrolled vocabulary: `chill`, `chillout`, `chill-out`, `mellow`,
`laid back`, `lo-fi`, `lofi` are seven strings covering maybe three meanings. A bag-of-tags
model treats them as seven orthogonal dimensions, which is a semantic failure rather than a
modelling one.

**This module collapses orthography only.** `hip hop` / `hip-hop` / `hiphop` are one string
written three ways, so they become one term. `chill` and `mellow` stay separate, and so do
`chill` and `chillout`: deciding that two different words mean the same thing is the
semantic space's job, and hard-coding it here would pre-empt the very result the project
exists to test. Getting this boundary wrong in the generous direction would let the
evaluation in Task 8 grade the normalizer's assumptions instead of the space.

**No stemming.** `remaster`/`remastered` would be safe to fuse, `dance`/`dancing` is
arguable, and a stemmer would also fuse `mellow`/`mellowed`. VARIANTS is a curated map
instead, because a map is auditable and a stemmer is not - every entry is there because a
gold-set pair demanded it.

The contract is fixtures/tag-vocab-gold.json: every variant group must collapse to one
term, and every near-miss pair must stay two.
"""

import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_MIN_COUNT = 5

# Curated variant map, keyed and valued on *normalized* forms. Entries exist only where
# normalization alone cannot collapse spellings of the same string.
VARIANTS: Mapping[str, str] = {
    # Ampersands and elisions survive normalization differently: "r&b" -> "rb",
    # "drum'n'bass" -> "drumnbass", "drum & bass" -> "drumbass".
    "rb": "rnb",
    "rhythmandblues": "rnb",
    "rhythmblues": "rnb",
    "randb": "rnb",
    "dnb": "drumandbass",
    "drumnbass": "drumandbass",
    "drumbass": "drumandbass",
    "dandb": "drumandbass",
    # Decades, written three ways.
    "1980s": "80s",
    "eighties": "80s",
    "1990s": "90s",
    "nineties": "90s",
    "1970s": "70s",
    "seventies": "70s",
    "1960s": "60s",
    "sixties": "60s",
    "2000s": "00s",
    "noughties": "00s",
    # Plurals of the handful of tags that are routinely written both ways. Listed rather
    # than stemmed, so the set stays auditable.
    "femalevocalists": "femalevocalist",
    "malevocalists": "malevocalist",
    "femalevocals": "femalevocalist",
    "malevocals": "malevocalist",
    "singersongwriters": "singersongwriter",
    "instrumentals": "instrumental",
    "soundtracks": "soundtrack",
    "classics": "classic",
    "oldies": "oldie",
    # -ing forms of genre names that name the same genre, not an activity.
    "shoegazing": "shoegaze",
    # Common abbreviations.
    "altrock": "alternativerock",
    "alt": "alternative",
    "electro": "electronic",
    "prog": "progressive",
    "psych": "psychedelic",
}


def normalize_tag(tag: str) -> str:
    """Casefold, strip diacritics, and drop every separator and punctuation mark.

    Separators are removed rather than unified, because that is the only way `hiphop` and
    `hip hop` land on the same string without an entry per case. Alphanumeric is tested per
    Unicode rather than against [a-z0-9]: restricting to ASCII would erase a Japanese or
    Cyrillic tag entirely and silently merge every one of them into a single empty term.
    """
    decomposed = unicodedata.normalize("NFKD", tag)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in without_marks.casefold() if c.isalnum())


def canonical_tag(tag: str) -> str:
    """normalize_tag, then the curated variant map. This is the term a vocabulary holds."""
    normalized = normalize_tag(tag)
    return VARIANTS.get(normalized, normalized)


@dataclass(frozen=True)
class Vocabulary:
    terms: tuple[str, ...]
    index: Mapping[str, int]
    counts: Mapping[str, int]
    # Canonical -> most frequent original spelling. The canonical form is squashed
    # ("malevocalist"), which is fine as an identifier and poor to read; this keeps the
    # export and the gold-set reports legible.
    display: Mapping[str, str] = field(default_factory=dict)
    dropped: int = 0

    def id(self, tag: str) -> int | None:
        """Id for a raw or canonical tag, or None when it is not in the vocabulary."""
        return self.index.get(canonical_tag(tag))

    def __len__(self) -> int:
        return len(self.terms)


def build_vocabulary(
    tag_counts: Mapping[str, int], min_count: int = DEFAULT_MIN_COUNT
) -> Vocabulary:
    """Fold raw tag counts onto canonical terms and drop the ones too rare to inform PPMI.

    A tag appearing on a single item carries no co-occurrence information but still adds a
    row of noise to the matrix, so min_count trims the hapax tail. Terms are ordered by
    descending count then alphabetically, which makes ids deterministic for a given input -
    without that the space cannot be reproduced, and an irreproducible space cannot be
    evaluated.
    """
    totals: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}

    for raw, count in tag_counts.items():
        term = canonical_tag(raw)
        if not term:  # a tag that was entirely punctuation
            continue
        totals[term] += count
        spellings.setdefault(term, Counter())[raw] += count

    kept = {term: total for term, total in totals.items() if total >= min_count}
    ordered = tuple(sorted(kept, key=lambda term: (-kept[term], term)))

    return Vocabulary(
        terms=ordered,
        index={term: i for i, term in enumerate(ordered)},
        counts={term: kept[term] for term in ordered},
        display={term: spellings[term].most_common(1)[0][0] for term in ordered},
        dropped=len(totals) - len(kept),
    )

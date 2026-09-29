"""Match Spotify track strings against Last.fm scrobble strings.

This is the one unsolved problem in Phase 0. Novelty rate is only as trustworthy as this
module, because the pitch's claim is "you had never heard this before".

Error direction matters more than accuracy here. Over-matching maps a genuinely new DJ
track onto something already in the history, counts it as familiar, and *lowers* measured
novelty - which makes the DJ look worse and flatters the argument. So the design is
conservative: a trailing segment is dropped only when it is recognisably a version
qualifier, never merely because it sits in brackets. `(Don't Fear) The Reaper` survives.

Stated assumption: the unit is the song, not the recording. Remasters, edits, live takes
and acoustic versions match; a remix or cover credited to someone else does not. The gold
set at fixtures/match-gold.json is the contract, and every word set below is extended in
response to a gold-set failure rather than from imagination.
"""

import re
import unicodedata

# A trailing segment is dropped if every word is one of these (a bare 4-digit year allowed).
QUALIFIER_WORDS = frozenset(
    {
        "remaster", "remastered", "remasters", "remastering", "master", "mastered",
        "version", "edit", "radio", "single", "album", "deluxe", "expanded", "edition",
        "reissue", "mono", "stereo", "live", "acoustic", "demo", "instrumental",
        "bonus", "track", "explicit", "clean", "anniversary", "original", "digital",
        "take", "alternate", "extended", "the", "of", "from", "a", "an", "and",
        "in", "at", "on", "for", "feat", "ft", "featuring",
    }
)

# If a trailing segment *starts* with one of these, the whole segment goes, however it
# continues - this is what makes "Live at the Bell House" a qualifier rather than a title.
STRONG_QUALIFIERS = frozenset(
    {"remaster", "remastered", "live", "acoustic", "demo", "instrumental", "reissue"}
)

# Any of these anywhere in a segment forbids dropping it: they mark a different recording
# or a different piece, not a different master of the same one.
NEVER_DROP = frozenset(
    {
        "remix", "rework", "cover", "reprise", "part", "pt", "vip", "dub", "mashup",
        "interlude", "sessions", "session", "medley", "continuous",
    }
)

# U+0027 apostrophe, U+2019 right single quote, U+02BC modifier letter apostrophe, backtick.
_APOSTROPHES = str.maketrans(dict.fromkeys("'’ʼ`", ""))

_TRAILING_BRACKET = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]\s*$")
_TRAILING_DASH = re.compile(r"\s+-\s+([^-]+)$")
_YEAR = re.compile(r"^\d{4}$")
_FEAT = re.compile(r"\s*[\(\[]?\s*\b(?:feat|ft|featuring)\b\.?\s+.*$", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[\s/,]+")


def _is_qualifier(segment: str) -> bool:
    words = [w.strip(".") for w in _WORD_SPLIT.split(segment.lower().strip()) if w.strip(".")]
    if not words:
        return False
    if any(word in NEVER_DROP for word in words):
        return False
    if words[0] in STRONG_QUALIFIERS:
        return True
    return all(_YEAR.match(word) or word in QUALIFIER_WORDS for word in words)


def _strip_qualifiers(title: str) -> str:
    """Peel recognised version qualifiers off the end. Titles rarely stack more than a few."""
    current = title.strip()
    for _ in range(4):
        for pattern in (_TRAILING_BRACKET, _TRAILING_DASH):
            match = pattern.search(current)
            if match and _is_qualifier(match.group(1)):
                stripped = current[: match.start()].strip()
                if stripped:  # never strip a title down to nothing
                    current = stripped
                    break
        else:
            break
    return current


def normalize_text(value: str) -> str:
    """Casefold, drop diacritics and punctuation, spell out &, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Apostrophes are deleted, not spaced. Spotify and Last.fm disagree about whether
    # "Don't" carries one, and NFKD leaves the typographic U+2019 alone, so spacing them
    # would leave "don t" unable to match "dont". Other punctuation becomes a space,
    # because there it separates words rather than sitting inside one.
    unapostrophed = without_marks.translate(_APOSTROPHES)
    spelled_out = unapostrophed.casefold().replace("&", " and ")
    alnum_only = "".join(c if (c.isalnum() or c.isspace()) else " " for c in spelled_out)
    return " ".join(alnum_only.split())


def normalize_title(title: str) -> str:
    return normalize_text(_FEAT.sub("", _strip_qualifiers(title))) or normalize_text(title)


def normalize_artist(artist: str) -> str:
    """Artist names keep their qualifiers; only a featured credit is dropped."""
    return normalize_text(_FEAT.sub("", artist)) or normalize_text(artist)


def track_key(artist: str, title: str) -> tuple[str, str]:
    return (normalize_artist(artist), normalize_title(title))


def same_track(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a == b

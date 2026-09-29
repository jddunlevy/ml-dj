from mldj.scrobbles import Scrobble
from mldj.space.assign import assign_tags, tier_counts, track_tier_keys
from mldj.space.vocab import build_vocabulary, canonical_tag

VOCAB = build_vocabulary(
    dict.fromkeys(
        ["mellow", "dream pop", "shoegaze", "synthpop", "electronic", "loud", "quiet"], 9
    ),
    min_count=1,
)


def scrobble(artist, title, album=""):
    return Scrobble(uts=1, artist=artist, title=title, album=album)


def key(artist, title):
    from mldj.match import track_key

    return track_key(artist, title)


def rows(*names):
    """Tag rows as Last.fm returns them: (name, count), highest first."""
    return [(n, 100 - i) for i, n in enumerate(names)]


def test_a_tagged_track_uses_its_own_tags_at_track_tier():
    scrobbles = [scrobble("Odell", "Static Bloom", "Record")]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("Odell", "Static Bloom"): rows("mellow", "dream pop")},
        artist_tags={"odell": rows("shoegaze")},
        vocab=VOCAB,
    )
    got = assignments[key("Odell", "Static Bloom")]
    assert got.tier == "track"
    assert got.tags == (canonical_tag("mellow"), canonical_tag("dream pop"))


def test_an_untagged_track_pools_its_tagged_album_siblings():
    # The user's example: american dream is untagged, but its album-mates are not.
    scrobbles = [
        scrobble("LCD", "tagged one", "American Dream"),
        scrobble("LCD", "american dream", "American Dream"),
    ]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("LCD", "tagged one"): rows("electronic", "mellow")},
        artist_tags={"lcd": rows("shoegaze")},
        vocab=VOCAB,
    )
    got = assignments[key("LCD", "american dream")]
    assert got.tier == "album"
    assert set(got.tags) == {canonical_tag("electronic"), canonical_tag("mellow")}


def test_album_pooling_ranks_by_sibling_count():
    scrobbles = [
        scrobble("LCD", "a", "Record"),
        scrobble("LCD", "b", "Record"),
        scrobble("LCD", "bare", "Record"),
    ]
    assignments = assign_tags(
        scrobbles,
        track_tags={
            key("LCD", "a"): rows("electronic", "mellow"),
            key("LCD", "b"): rows("electronic", "shoegaze"),
        },
        artist_tags={},
        vocab=VOCAB,
    )
    # electronic is on both siblings, so it leads.
    assert assignments[key("LCD", "bare")].tags[0] == canonical_tag("electronic")


def test_an_empty_album_string_never_pools():
    # An absent album is not an album; pooling on it would join everything by that artist.
    scrobbles = [scrobble("LCD", "tagged", ""), scrobble("LCD", "bare", "")]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("LCD", "tagged"): rows("electronic")},
        artist_tags={"lcd": rows("shoegaze")},
        vocab=VOCAB,
    )
    got = assignments[key("LCD", "bare")]
    assert got.tier == "artist"
    assert got.tags == (canonical_tag("shoegaze"),)


def test_album_pooling_never_crosses_two_albums():
    scrobbles = [scrobble("LCD", "tagged", "One"), scrobble("LCD", "bare", "Two")]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("LCD", "tagged"): rows("electronic")},
        artist_tags={"lcd": rows("shoegaze")},
        vocab=VOCAB,
    )
    assert assignments[key("LCD", "bare")].tier == "artist"


def test_album_pooling_never_crosses_two_artists_sharing_an_album_name():
    scrobbles = [
        scrobble("Odell", "tagged", "Greatest Hits"),
        scrobble("LCD", "bare", "Greatest Hits"),
    ]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("Odell", "tagged"): rows("electronic")},
        artist_tags={},
        vocab=VOCAB,
    )
    assert assignments[key("LCD", "bare")].tier == "none"


def test_artist_tier_is_used_only_when_no_album_sibling_is_tagged():
    scrobbles = [
        scrobble("LCD", "bare one", "Record"),
        scrobble("LCD", "bare two", "Record"),
    ]
    assignments = assign_tags(
        scrobbles, track_tags={}, artist_tags={"lcd": rows("shoegaze")}, vocab=VOCAB
    )
    assert {a.tier for a in assignments.values()} == {"artist"}


def test_a_track_with_nothing_anywhere_is_tier_none():
    assignments = assign_tags(
        [scrobble("Nobody", "Nothing", "Album")], track_tags={}, artist_tags={}, vocab=VOCAB
    )
    got = assignments[key("Nobody", "Nothing")]
    assert got.tier == "none"
    assert got.tags == ()


def test_tags_outside_the_vocabulary_are_dropped():
    assignments = assign_tags(
        [scrobble("Odell", "Static Bloom")],
        track_tags={key("Odell", "Static Bloom"): rows("mellow", "not-in-vocab-at-all")},
        artist_tags={},
        vocab=VOCAB,
    )
    assert assignments[key("Odell", "Static Bloom")].tags == (canonical_tag("mellow"),)


def test_a_track_whose_every_tag_is_out_of_vocabulary_falls_back():
    scrobbles = [scrobble("Odell", "Static Bloom", "Record")]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("Odell", "Static Bloom"): rows("nonsense", "gibberish")},
        artist_tags={"odell": rows("shoegaze")},
        vocab=VOCAB,
    )
    # Tags it cannot use are no tags at all, so the backoff must engage.
    assert assignments[key("Odell", "Static Bloom")].tier == "artist"


def test_top_n_caps_the_tag_count():
    assignments = assign_tags(
        [scrobble("Odell", "Static Bloom")],
        track_tags={
            key("Odell", "Static Bloom"): rows("mellow", "dream pop", "shoegaze", "synthpop")
        },
        artist_tags={},
        vocab=VOCAB,
        top_n=2,
    )
    assert len(assignments[key("Odell", "Static Bloom")].tags) == 2


def test_duplicate_spellings_do_not_double_count():
    assignments = assign_tags(
        [scrobble("Odell", "Static Bloom")],
        track_tags={key("Odell", "Static Bloom"): rows("synth pop", "synthpop", "mellow")},
        artist_tags={},
        vocab=VOCAB,
    )
    tags = assignments[key("Odell", "Static Bloom")].tags
    assert len(tags) == len(set(tags)) == 2


def test_provenance_records_what_was_inherited_from():
    scrobbles = [
        scrobble("LCD", "tagged", "American Dream"),
        scrobble("LCD", "bare", "American Dream"),
        scrobble("Odell", "orphan", "Solo"),
    ]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("LCD", "tagged"): rows("electronic")},
        artist_tags={"odell": rows("shoegaze")},
        vocab=VOCAB,
    )
    assert "American Dream" in assignments[key("LCD", "bare")].source
    assert "Odell" in assignments[key("Odell", "orphan")].source
    assert assignments[key("LCD", "tagged")].source == "own tags"


def test_tier_counts_sum_to_the_number_of_tracks():
    scrobbles = [
        scrobble("LCD", "tagged", "Record"),
        scrobble("LCD", "sibling", "Record"),
        scrobble("Odell", "artist only", "Other"),
        scrobble("Nobody", "nothing", "None"),
    ]
    assignments = assign_tags(
        scrobbles,
        track_tags={key("LCD", "tagged"): rows("electronic")},
        artist_tags={"odell": rows("shoegaze")},
        vocab=VOCAB,
    )
    counts = tier_counts(assignments)
    assert counts == {"track": 1, "album": 1, "artist": 1, "none": 1}
    assert sum(counts.values()) == len(assignments)


def test_track_tier_keys_returns_only_genuinely_annotated_tracks():
    # This is what the learning matrix is built from, and what Phase 0's tag-persistence
    # metric must filter on.
    scrobbles = [scrobble("LCD", "tagged", "Record"), scrobble("LCD", "sibling", "Record")]
    assignments = assign_tags(
        scrobbles, track_tags={key("LCD", "tagged"): rows("electronic")}, artist_tags={},
        vocab=VOCAB,
    )
    assert track_tier_keys(assignments) == {key("LCD", "tagged")}

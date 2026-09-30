import json

from mldj.candidates import candidate_pool, write_pool


def _events():
    return [
        {"artist": "A", "title": "1", "tags": ["dreampop"], "outcome": "completed"},
        {"artist": "B", "title": "2", "tags": ["dance"], "outcome": "skipped"},
    ]


def test_pool_excludes_tracks_already_played_in_the_session():
    similar = {"A": [("A", "1"), ("C", "3")], "B": [("B", "2")]}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert ("A", "1") not in [(c["artist"], c["title"]) for c in pool]
    assert ("B", "2") not in [(c["artist"], c["title"]) for c in pool]
    assert ("C", "3") in [(c["artist"], c["title"]) for c in pool]


def test_pool_deduplicates_tracks_reached_from_two_seeds():
    similar = {"A": [("C", "3")], "B": [("C", "3")]}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert len(pool) == 1


def test_pool_carries_canonical_tags():
    similar = {"A": [("C", "3")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["Dream Pop"])
    assert pool[0]["tags"] == ["dreampop"]


def test_a_candidate_with_no_tags_is_dropped():
    # An untagged candidate can never be scored, so it is noise in the pool.
    similar = {"A": [("C", "3")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: [])
    assert pool == []


# The four tests above are the plan's. The three below cover `novel` and `write_pool`, which
# the plan leaves entirely unasserted - and `novel` is the field feeding the user-visible
# novelty knob, decided by the Spotify-to-Last.fm join the spec calls load-bearing.


def test_novel_reflects_was_heard_per_track_not_per_pool():
    similar = {"A": [("C", "3"), ("D", "4")], "B": []}
    heard = {("C", "3")}
    pool = candidate_pool(
        _events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"],
        lambda a, t: (a, t) in heard,
    )
    by_track = {(c["artist"], c["title"]): c["novel"] for c in pool}
    assert by_track[("C", "3")] is False
    assert by_track[("D", "4")] is True


def test_every_candidate_is_novel_when_no_history_is_supplied():
    # was_heard=None means "no scrobble history available", which must not silently read as
    # "everything has been heard" - that would zero out novelty rather than disable it.
    similar = {"A": [("C", "3")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert pool[0]["novel"] is True


def test_write_pool_roundtrips_through_a_nested_directory(tmp_path):
    out = tmp_path / "nested" / "s1.json"
    pool = [{"artist": "C", "title": "3", "tags": ["dreampop"], "novel": True}]
    write_pool(out, "s1", pool)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == {"session": "s1", "candidates": pool}


def test_similar_for_is_called_once_per_distinct_artist_not_once_per_event():
    # Each similar_for call fans out to ~21 Last.fm requests under the CLI, and a session
    # plays the same artist more than once. The `seen` set already made repeat calls produce
    # nothing, so they only cost latency and rate-limit budget.
    events = [
        {"artist": "A", "title": "1", "tags": ["dreampop"], "outcome": "completed"},
        {"artist": "A", "title": "9", "tags": ["dreampop"], "outcome": "skipped"},
        {"artist": "B", "title": "2", "tags": ["dance"], "outcome": "completed"},
    ]
    calls = []

    def similar_for(artist):
        calls.append(artist)
        return {"A": [("C", "3")], "B": [("D", "4")]}.get(artist, [])

    pool = candidate_pool(events, similar_for, lambda a, t: ["dreampop"])
    assert calls == ["A", "B"]
    # Deduplicating the seeds must not change the result, only the number of calls.
    assert [(c["artist"], c["title"]) for c in pool] == [("C", "3"), ("D", "4")]


def test_each_candidate_carries_the_normalized_join_key():
    # The pool's strings come from Last.fm; `actual` comes from Spotify capture. R joins the
    # two to flag "the DJ played the one this engine ranked 47th", and R has no matcher -
    # porting match.py would be a second implementation free to drift. So the key travels
    # with the data, computed once, here.
    similar = {"A": [("New Order", "Blue Monday")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    assert pool[0]["key"] == ["new order", "blue monday"]


def test_the_join_key_survives_a_remaster_suffix_on_either_side():
    from mldj.match import track_key

    similar = {"A": [("New Order", "Blue Monday - 2016 Remaster")], "B": []}
    pool = candidate_pool(_events(), lambda a: similar.get(a, []), lambda a, t: ["dreampop"])
    # The pool's suffixed title and a bare Spotify title must land on the same key, or the
    # pitch's headline claim silently reads "the DJ's pick was not in the pool".
    assert pool[0]["key"] == list(track_key("New Order", "Blue Monday"))

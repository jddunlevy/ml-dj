# Phase 1 — The Semantic Space Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 39,100 scrobbles and their Last.fm tags into a dense tag-vector space — normalized vocabulary, PPMI-weighted co-occurrence, SVD — and prove it ranks a hand-built gold set of tag pairs correctly.

**Architecture:** Pure Python offline. Tag data is pulled once into a gitignored cache, the vocabulary is normalized, a tags × items co-occurrence matrix is PPMI-weighted and reduced by truncated SVD, and the result exports as a versioned `space.json`. No Spotify API, no Premium, no `cd-player`, nothing at listen time.

**Tech Stack:** Python ≥3.12, `numpy` and `scipy` (they arrive in this phase, per CLAUDE.md), pytest, ruff. Phase 0's `mldj.lastfm`, `mldj.match`, and `mldj.scrobbles` are reused as-is.

## Global Constraints

Everything in Phase 0's plan still applies. Repeated here because this plan may be executed by someone who has not read it:

- **THIS REPO IS PUBLIC.** Never commit `data/`, `.env.local`, credentials, or the scrobble corpus. `space.json` is gitignored and is committed **only if it provably contains no raw history** — see Task 9, which is what makes that provable.
- **Dependencies:** `numpy` and `scipy` are justified here and nowhere earlier. Justify anything beyond them.
- **Tests:** pytest, TDD. Network boundaries take an injected transport; the clock is injected; no test sleeps and no test touches the wire.
- **Fixtures:** anonymized, committed, under `fixtures/`.
- **Commits:** conventional, small, frequent. **Line width 100.** Ruff selects `E`, `F`, `I`, `UP`, `B`.
- **Determinism:** SVD sign and rotation are not unique. Every random or arbitrary choice takes a fixed seed, and the space export is byte-stable for the same inputs, or the evaluation is not reproducible.

---

## Measured inputs — do not re-measure these

Established 2026-09-29 before this plan was written:

| Fact | Value |
|---|---|
| Scrobbles | 39,100 |
| Distinct tracks | 5,831 |
| Distinct artists | 1,741 |
| **Track-level tag coverage** | **24.5%** of distinct tracks (random sample, n=200) |
| Track-level coverage, play-weighted | **60.1%** |
| **Artist-level tag coverage** | **95.0%** (random sample, n=120) |
| Scrobble history gap | 67 days, ending 2026-07-24 |

The exact corpus-wide figures land in `data/tag-coverage.json` when the tag pull finishes; the sampled values above are what this plan is designed around and the two should agree within sampling error. If they disagree badly, stop and find out why before building on it.

## The decision those numbers force

**Learning what a tag means and representing a track in tag space are two different jobs, and they must not share one rule.**

- **To learn tag meanings** (the tags × items matrix → PPMI → SVD), use **only genuinely annotated items**. If every LCD Soundsystem track inherited the artist's tags, those tags would co-occur across hundreds of columns that are really one annotation, PPMI would read that as overwhelming evidence, and the space would learn an artefact of the backoff rather than a fact about language. Inherited tags are therefore **excluded from the matrix**.
- **To represent a track** (which Phase 3 needs for every candidate, tagged or not), back off: **track tags → tagged album siblings → artist tags**, and **record which tier each vector came from**. A vector is not the same kind of evidence depending on where it came from, so the provenance travels with it.

Marking provenance is not bookkeeping, it is load-bearing:

- **It protects a Phase 0 measurement.** Post-skip persistence's tag half compares the outgoing and incoming track's tags. If both fell back to the same artist, their overlap is 1.0 *by construction*. Phase 0's `tagged_transitions` must count only transitions where both sides are **track-tier**, or the metric measures the backoff instead of the DJ.
- **It protects Phase 3.** A session vector built from artist-tier tags cannot distinguish mellow LCD Soundsystem from dancey LCD Soundsystem, which is exactly the discrimination the redesign claims to make.
- **It is a beat 6 number.** "76% of distinct tracks have no tags of their own, and their vectors are inherited" is an honesty-check fact, and it is only sayable if the tiers are counted.

**A second, cheaper win:** artist tag sets are real human annotations too, so tagged **artists** can serve as additional columns in the learning matrix alongside tagged tracks — roughly 1,650 more columns against about 1,430 tagged tracks, more than doubling the evidence for tag co-occurrence. They are coarser and may blur fine distinctions, so Task 5 builds the matrix both ways and Task 8 decides on evidence rather than taste.

---

## File Structure

```
src/mldj/
  lastfm.py            MODIFY — add tested artist_top_tags / artist_top_tags_cached
  tags.py              NEW — `mldj tags` subcommand: populate both caches, report coverage
  space/
    __init__.py
    vocab.py           tag-string normalization and variant grouping (the folksonomy problem)
    assign.py          per-track tag assignment with backoff and provenance
    matrix.py          tags x items sparse count matrix, built from track-tier data only
    ppmi.py            PPMI weighting
    reduce.py          truncated SVD -> dense tag vectors
    space.py           TagSpace: similarity, neighbours, load/save versioned space.json
    evaluate.py        level-1 gold-set evaluation

tests/
  test_lastfm.py       MODIFY — artist tag tests
  test_tags.py
  space/test_vocab.py  space/test_assign.py  space/test_matrix.py
  space/test_ppmi.py   space/test_reduce.py  space/test_space.py
  space/test_evaluate.py

fixtures/
  lastfm-artisttags.json      tag-vocab-gold.json      tag-pairs-gold.json
  tiny-corpus.jsonl           a hand-built corpus with a known-correct space
```

`tests/space/` needs no `__init__.py`; `tests/conftest.py` already puts `tests/` on `sys.path`.

---

## Task 1: Productionize the tag pull

The scratchpad script that populated the caches becomes a tested subcommand, so the pull is repeatable and the coverage numbers are a command rather than a memory.

**Files:** modify `src/mldj/lastfm.py`, `src/mldj/cli.py`; create `src/mldj/tags.py`, `fixtures/lastfm-artisttags.json`; test `tests/test_lastfm.py`, `tests/test_tags.py`

**Produces:**
- `mldj.lastfm.ARTIST_TAGS_DIR: Path = Path("data/artist-tags")`
- `mldj.lastfm.artist_top_tags(client, artist) -> list[tuple[str, int]]`
- `mldj.lastfm.artist_top_tags_cached(client, artist, cache_dir=ARTIST_TAGS_DIR) -> list[tuple[str, int]]`
- `mldj.tags.CoverageSummary` — frozen dataclass: `distinct_tracks`, `distinct_artists`, `track_tagged`, `track_untagged`, `track_coverage`, `play_weighted_coverage`, `album_rescued`, `coverage_after_album`, `artist_tagged`, `artist_coverage`, `distinct_tags`, `failures: int`
- `mldj.tags.pull_all(client, scrobbles, tags_dir, artist_tags_dir, on_progress=None) -> CoverageSummary`
- `mldj.tags.register(subparsers)` — `mldj tags [--coverage-only]`

**Notes:** `_cache_path` is already shared; artist entries cache under a separate directory so a track and an artist of the same name cannot collide. A per-item failure increments a counter and is stepped over — one bad track must never end a 7,500-call run. `--coverage-only` recomputes the summary from the cache with no requests.

**Tests:** `test_artist_top_tags_parses_and_orders_by_count`, `test_artist_top_tags_handles_an_untagged_artist`, `test_artist_top_tags_cached_hits_the_network_once`, `test_artist_and_track_caches_do_not_collide`, `test_pull_all_reports_track_and_artist_coverage`, `test_pull_all_counts_a_failure_and_continues`, `test_pull_all_is_resumable_from_cache_with_no_requests`, `test_coverage_only_makes_no_requests`

---

## Task 2: Tag vocabulary normalization — the folksonomy problem

`chill`, `chillout`, `chill-out`, `mellow`, `laid back`, `lo-fi`, `lofi` are seven strings covering maybe three meanings. A bag-of-tags model treats them as seven orthogonal dimensions, which is a semantic failure, not a modelling one. This task collapses only what is **provably** the same string written differently, and deliberately leaves genuine synonymy to the space to discover.

**Files:** create `src/mldj/space/__init__.py`, `src/mldj/space/vocab.py`, `fixtures/tag-vocab-gold.json`; test `tests/space/test_vocab.py`

**Produces:**
- `normalize_tag(tag: str) -> str` — casefold, strip diacritics, collapse `-`/`_`/whitespace, drop punctuation
- `canonical_tag(tag: str) -> str` — `normalize_tag` plus a curated variant map
- `VARIANTS: Mapping[str, str]` — explicit variant → canonical, extended only from gold-set failures
- `build_vocabulary(tag_counts: Mapping[str, int], min_count: int = 5) -> Vocabulary`
- `Vocabulary` — frozen dataclass: `terms: tuple[str, ...]`, `index: Mapping[str, int]`, `dropped: int`; method `id(tag) -> int | None`

**Decisions, stated so they are arguable:**
- **Morphological collapsing only.** `hip hop`/`hip-hop`/`hiphop` → one term; `lo-fi`/`lofi` → one term. `chill` and `mellow` stay **separate**, because deciding they mean the same thing is the space's job and hard-coding it would pre-empt the very result the project is testing.
- **No stemming.** `remaster`/`remastered` is fine to conflate; `dance`/`dancing` is not obviously so, and a stemmer would also fuse `mellow`/`mellowed`. A curated map is auditable; a stemmer is not.
- **`min_count` drops hapax tags.** A tag on one track carries no co-occurrence information but adds a row of noise to PPMI. 5 is a starting value; Task 8 checks sensitivity.
- The gold set is **variant groups** (strings that must collapse) plus **near-miss pairs** (strings that must NOT collapse: `chill`/`chillwave`, `dream pop`/`dreamcore`, `post rock`/`post punk`).

**Tests:** `test_case_and_whitespace_are_normalized`, `test_hyphen_and_space_and_run_together_forms_collapse`, `test_diacritics_are_stripped`, `test_curated_variants_map_to_one_canonical_form`, `test_chill_and_mellow_are_not_collapsed`, `test_near_miss_pairs_stay_distinct`, `test_every_gold_variant_group_collapses_to_one_term`, `test_vocabulary_drops_tags_below_min_count`, `test_vocabulary_ids_are_stable_for_the_same_input`

---

## Task 3: Track tag assignment with backoff and provenance

The user's context-clues idea, made explicit. An untagged track inherits from its album siblings, then its artist, and **always records which**.

**Files:** create `src/mldj/space/assign.py`; test `tests/space/test_assign.py`

**Produces:**
- `Tier` — `"track"` | `"album"` | `"artist"` | `"none"`
- `TrackTags` — frozen dataclass: `key: tuple[str, str]`, `tags: tuple[str, ...]`, `tier: Tier`, `source: str` (what it inherited from, for auditing)
- `assign_tags(scrobbles, track_tags, artist_tags, vocab, top_n=10) -> dict[tuple[str, str], TrackTags]`
- `tier_counts(assignments) -> dict[Tier, int]`

**Rules:**
- **track tier:** the track has ≥1 tag of its own. Use them.
- **album tier:** it does not, but ≥1 track sharing `(normalized artist, album)` does. Pool those siblings' tags, keep the `top_n` by how many siblings carry them. An empty album string is **not** an album — never pool across every album-less track by an artist.
- **artist tier:** no tagged sibling, but the artist has tags. Use the artist's `top_n`.
- **none:** nothing anywhere. It gets an empty vector and must be excluded from anything that divides.
- Tags pass through `canonical_tag` and must be in `vocab`; unknown tags are dropped, not invented.

**Tests:** `test_a_tagged_track_uses_its_own_tags_at_track_tier`, `test_an_untagged_track_pools_its_tagged_album_siblings`, `test_album_pooling_ranks_by_sibling_count`, `test_an_empty_album_string_never_pools`, `test_artist_tier_is_used_only_when_no_album_sibling_is_tagged`, `test_a_track_with_nothing_anywhere_is_tier_none`, `test_tags_outside_the_vocabulary_are_dropped`, `test_tier_counts_sum_to_the_number_of_tracks`, `test_provenance_records_what_was_inherited_from`

---

## Task 4: The tags × items count matrix

**Built from track-tier assignments only.** Inherited tags are excluded, for the reason in *The decision those numbers force* — including them would teach the space the shape of the backoff rather than the shape of the language.

**Files:** create `src/mldj/space/matrix.py`, `fixtures/tiny-corpus.jsonl`; test `tests/space/test_matrix.py`

**Produces:**
- `CountMatrix` — frozen dataclass: `counts: scipy.sparse.csr_matrix` (tags × items), `vocab: Vocabulary`, `item_ids: tuple[str, ...]`, `item_kinds: tuple[str, ...]` (`"track"` / `"artist"`)
- `build_matrix(assignments, artist_tags, vocab, include_artists: bool = True) -> CountMatrix`
- `cooccurrence(matrix) -> scipy.sparse.csr_matrix` — the tags × tags same-item co-occurrence counts, which **Phase 2's antonym discriminator consumes directly**

**Notes:** `include_artists` is the knob Task 8 evaluates — tagged artists roughly double the column count but are coarser. `fixtures/tiny-corpus.jsonl` is a hand-built corpus small enough that the correct co-occurrence matrix can be written out by hand in the test, which is the only way to be sure the counting is right.

**Tests:** `test_only_track_tier_assignments_become_columns`, `test_artist_columns_are_included_when_asked_and_excluded_when_not`, `test_counts_match_a_hand_computed_tiny_corpus`, `test_item_kinds_line_up_with_item_ids`, `test_cooccurrence_is_symmetric_with_tag_totals_on_the_diagonal`, `test_a_tag_absent_from_the_vocabulary_never_appears`, `test_matrix_shape_is_vocab_by_items`

---

## Task 5: PPMI weighting

**Files:** create `src/mldj/space/ppmi.py`; test `tests/space/test_ppmi.py`

**Produces:**
- `ppmi(counts, shift: float = 0.0, context_smoothing: float = 0.75) -> scipy.sparse.csr_matrix`

**Notes:** PPMI is `max(0, log(p(t,i) / (p(t) · p(i))))`. Two options with reasons rather than defaults-by-habit: `context_smoothing` raises context probabilities to α (0.75 is the standard correction for PMI's bias toward rare contexts — set 1.0 to disable), and `shift` subtracts log k before clamping (shifted PPMI, equivalent to SGNS with k negative samples). Both default to a documented choice and Task 8 checks sensitivity. Must stay sparse: a dense 2,000 × 3,000 float matrix is fine, but the implementation should not densify by accident on a larger vocabulary.

**Tests:** `test_ppmi_of_a_hand_computed_two_by_two_is_exact`, `test_independent_tag_and_item_scores_zero`, `test_negative_pmi_is_clamped_to_zero`, `test_context_smoothing_changes_rare_context_scores`, `test_shift_subtracts_log_k_before_clamping`, `test_result_stays_sparse`, `test_an_all_zero_row_does_not_divide_by_zero`

---

## Task 6: Truncated SVD → dense tag vectors

**Files:** create `src/mldj/space/reduce.py`; test `tests/space/test_reduce.py`; modify `pyproject.toml` to add `numpy` and `scipy`

**Produces:**
- `reduce_dimensions(weighted, rank: int = 150, eigenvalue_weighting: float = 0.5, seed: int = 0) -> numpy.ndarray` — shape `(len(vocab), rank)`
- `explained_variance(weighted, rank) -> float`

**Notes:** `scipy.sparse.linalg.svds` with a fixed `v0` derived from `seed`, because Lanczos is not deterministic without one and an irreproducible space cannot be evaluated. `eigenvalue_weighting` is the exponent p in `U · Σ^p`: p=0 discards magnitudes entirely, p=1 keeps them, and p=0.5 is the usual compromise — chosen on Task 8's evidence, not by default. **Sign is not unique**: fix it deterministically (e.g. force each component's largest-magnitude entry positive) or the same inputs produce different exports. `rank=150` is a starting value against roughly 1,430 tagged tracks plus 1,650 artists; Task 8 sweeps it.

**Tests:** `test_output_shape_is_vocab_by_rank`, `test_the_same_input_and_seed_give_byte_identical_output`, `test_component_signs_are_deterministic`, `test_rank_larger_than_the_matrix_is_rejected_clearly`, `test_eigenvalue_weighting_changes_vector_magnitudes`, `test_explained_variance_rises_with_rank`

---

## Task 7: The TagSpace, and the versioned export

**Files:** create `src/mldj/space/space.py`; test `tests/space/test_space.py`

**Produces:**
- `TagSpace` — frozen dataclass: `terms`, `vectors`, `meta: dict`; methods `similarity(a, b) -> float`, `neighbours(tag, k=10) -> list[tuple[str, float]]`, `vector(tag) -> ndarray | None`, `compose(tags, weights=None) -> ndarray`
- `save_space(space, path) -> None` / `load_space(path) -> TagSpace`
- `SPACE_FORMAT_VERSION: int`

**Notes:** `compose` is the session vector's primitive — a weighted sum of tag vectors, which is where compositional distributional semantics enters — so it belongs here rather than being reinvented in Phase 3. `meta` carries the format version, build timestamp, rank, PPMI options, `include_artists`, vocabulary size, item counts, and the tier counts from Task 3.

**The privacy gate, which is what makes `space.json` committable:** the export contains **tag strings and float vectors only**. No track titles, no artist names, no timestamps, no counts that could identify a single item. A test asserts this positively — that no string in the export appears in the corpus as an artist or title — because CLAUDE.md permits committing `space.json` only if it *provably* contains no raw history, and "provably" means a test, not a glance.

**Tests:** `test_similarity_is_cosine_and_symmetric`, `test_a_tag_is_maximally_similar_to_itself`, `test_neighbours_are_sorted_descending_and_exclude_the_query`, `test_an_unknown_tag_returns_none_rather_than_raising`, `test_compose_is_a_weighted_sum_and_handles_unknown_tags`, `test_save_then_load_round_trips_exactly`, `test_meta_records_rank_ppmi_options_and_tier_counts`, `test_export_contains_no_artist_or_track_strings`, `test_loading_an_unknown_format_version_fails_loudly`

---

## Task 8: The gold set and level-1 evaluation

The spec's evaluation level 1, and the task that turns every "starting value" above into a justified one.

**Files:** create `src/mldj/space/evaluate.py`, `fixtures/tag-pairs-gold.json`; modify `src/mldj/cli.py`; test `tests/space/test_evaluate.py`

**Produces:**
- `GoldPair` — `a`, `b`, `label`, `why`
- `load_gold(path) -> list[GoldPair]`
- `EvaluationResult` — per-label mean similarity, the separation between label groups, Spearman correlation against an expected ordering, and a `ranking_correct: bool`
- `evaluate_space(space, gold) -> EvaluationResult`
- `sweep(builder, grid) -> list[tuple[dict, EvaluationResult]]` — rank, `min_count`, `include_artists`, PPMI options
- `register(subparsers)` — `mldj space [--rank N] [--no-artists] [--sweep]`

**The gold set** has five labels, per the spec: `synonym`, `related`, `antonym`, `complementary`, `unrelated`. Target ≥60 pairs, ≥8 per label. **`complementary` is mandatory, not optional** — the spec names it as a known risk, because pairs like `male vocalist`/`female vocalist` and `verse`/`chorus` show high distributional similarity with low co-tagging exactly like antonyms do, and a discriminator that has never seen them will silently misfile them in Phase 2. Building those pairs now is what makes Phase 2 honest.

**What level 1 must show:** `synonym` similarity > `related` > `unrelated`. Antonyms are *expected* to score high — that is the whole problem Phase 2 exists to solve — so this task must **not** penalise them, only record their similarity so Phase 2 has a baseline to beat. The plan's success criterion is the synonym/related/unrelated ordering plus a documented antonym and complementary baseline.

**Tests:** `test_gold_set_has_every_label_and_the_minimum_counts`, `test_synonyms_outscore_related_pairs`, `test_related_pairs_outscore_unrelated_pairs`, `test_antonym_similarity_is_recorded_not_penalised`, `test_complementary_pairs_are_a_separate_class_in_the_result`, `test_a_gold_tag_missing_from_the_vocabulary_is_reported_not_skipped_silently`, `test_sweep_returns_one_result_per_grid_point`, `test_evaluation_is_reproducible_for_a_fixed_seed`

---

## Task 9: Build the real space, and feed Phase 0 what it needs

**Files:** modify `src/mldj/measure/persistence.py`; test `tests/measure/test_persistence.py`

**Produces:** `build_tag_index` gains a `tier_filter` so Phase 0's persistence metric counts a transition as tagged **only when both sides are track-tier**.

**Why this is in Phase 1:** Phase 0 shipped with `TagIndex` fed straight from `track.getTopTags`, so 76% of tracks contribute nothing and `tagged_transitions` is small. It is tempting to fill those in by backoff — and that would be wrong. Two same-artist tracks that both inherited artist tags have an overlap of 1.0 by construction, so the metric would report the backoff as evidence of the DJ's behaviour. The fix is the opposite of filling in: make the exclusion **explicit and counted**, so the report says "N of M transitions had track-level tags on both sides" and means it.

Then run the real thing and record the outcome:

- [ ] `mldj tags` — confirm corpus-wide coverage against the sampled 24.5% / 95.0%
- [ ] `mldj space --sweep` — pick rank, `min_count`, `include_artists` and the PPMI options on evidence; **write the chosen values and their evaluation numbers into this file**
- [ ] `mldj space` — build and save `space.json`; confirm `test_export_contains_no_artist_or_track_strings` passes against the real export before considering committing it
- [ ] Record final tier counts (track / album / artist / none) — these are beat 6 numbers
- [ ] `git status --porcelain` shows nothing under `data/`

---

## Definition of done

- [ ] `pytest` passes with no network access, no test over a second, no test sleeping
- [ ] `ruff check src tests` clean
- [ ] Corpus-wide tag coverage measured and recorded, at all three tiers
- [ ] Every variant group in `fixtures/tag-vocab-gold.json` collapses; every near-miss pair stays distinct
- [ ] `fixtures/tag-pairs-gold.json` has ≥60 pairs across all five labels, including ≥8 `complementary`
- [ ] Level 1 passes: synonym > related > unrelated, with antonym and complementary baselines recorded for Phase 2
- [ ] `space.json` builds reproducibly — the same inputs and seed give a byte-identical file
- [ ] The privacy test passes against the **real** export, not just a fixture
- [ ] Hyperparameters chosen by sweep, with the numbers written into this plan
- [ ] Phase 0's persistence metric counts only track-tier transitions, and the report says so

Phase 2 starts from the co-occurrence matrix of Task 4 and the antonym and complementary baselines of Task 8.

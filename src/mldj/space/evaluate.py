"""Level-1 evaluation: does the space rank a hand-built gold set correctly?

**The graded claim is narrow on purpose: synonym > related > unrelated.** Those three are
an ordering any usable distributional space must reproduce, and failing it means the
pipeline is broken rather than merely imperfect.

**Antonyms and complementary pairs are recorded, never penalised.** An unaided distributional
space scores `loud`/`quiet` as *similar*, because opposites share contexts - that is the
central problem of the project, not a bug in the measurement, and Phase 2 exists to fix it.
Scoring antonyms as failures here would make the number go up when the space got worse at
the thing the project cares about. What this task produces instead is the **baseline Phase 2
has to beat**, which is why the antonym and complementary means are first-class fields.

Complementary pairs - `male vocalists`/`female vocalists`, adjacent decades, alternative
instruments - are a separate class because the spec names them as the trap: they look exactly
like antonyms to the discriminator (high similarity, near-zero co-tagging) while being
neither opposed nor synonymous. A detector never shown them will misfile them silently.

A gold term the space does not hold is **reported, not skipped**. Silently dropping pairs
would let a shrinking vocabulary look like an improving score.
"""

import argparse
import itertools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scipy import stats

from mldj.space.space import TagSpace

GOLD_PATH = Path("fixtures/tag-pairs-gold.json")
LABELS = ("synonym", "related", "antonym", "complementary", "unrelated")
# Only these are graded, and this is the order they must come out in, worst to best.
GRADED = ("unrelated", "related", "synonym")
MIN_PAIRS_PER_LABEL = 8


@dataclass(frozen=True)
class GoldPair:
    a: str
    b: str
    label: str
    why: str


def load_gold(path: Path = GOLD_PATH) -> list[GoldPair]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        GoldPair(a=p["a"], b=p["b"], label=p["label"], why=p.get("why", ""))
        for p in raw["pairs"]
    ]


@dataclass(frozen=True)
class LabelStats:
    label: str
    pairs: int
    scored: int
    mean: float
    lowest: float
    highest: float


@dataclass(frozen=True)
class EvaluationResult:
    by_label: Mapping[str, LabelStats]
    ranking_correct: bool
    spearman: float
    synonym_minus_unrelated: float
    related_minus_unrelated: float
    # Recorded, not graded. These are the numbers Phase 2 has to improve on.
    antonym_mean: float
    complementary_mean: float
    missing_terms: tuple[str, ...] = field(default_factory=tuple)

    def mean(self, label: str) -> float:
        stats_for = self.by_label.get(label)
        return stats_for.mean if stats_for else 0.0


def _stats(label: str, scores: list[float], total: int) -> LabelStats:
    return LabelStats(
        label=label,
        pairs=total,
        scored=len(scores),
        mean=sum(scores) / len(scores) if scores else 0.0,
        lowest=min(scores) if scores else 0.0,
        highest=max(scores) if scores else 0.0,
    )


def evaluate_space(space: TagSpace, gold: Sequence[GoldPair]) -> EvaluationResult:
    scores: dict[str, list[float]] = {label: [] for label in LABELS}
    totals: dict[str, int] = dict.fromkeys(LABELS, 0)
    missing: set[str] = set()
    graded_expected: list[int] = []
    graded_observed: list[float] = []

    for pair in gold:
        totals[pair.label] = totals.get(pair.label, 0) + 1
        # Asked through the space rather than against its term tuple, so this does not
        # assume the terms are already in canonical form.
        absent = [side for side in (pair.a, pair.b) if space.vector(side) is None]
        if absent:
            missing.update(absent)
            continue
        similarity = space.similarity(pair.a, pair.b)
        scores.setdefault(pair.label, []).append(similarity)
        if pair.label in GRADED:
            graded_expected.append(GRADED.index(pair.label))
            graded_observed.append(similarity)

    by_label = {
        label: _stats(label, scores.get(label, []), totals.get(label, 0)) for label in LABELS
    }
    synonym, related, unrelated = (
        by_label["synonym"].mean,
        by_label["related"].mean,
        by_label["unrelated"].mean,
    )

    spearman = 0.0
    if len(set(graded_expected)) > 1 and len(graded_observed) > 2:
        computed = stats.spearmanr(graded_expected, graded_observed).statistic
        spearman = 0.0 if computed != computed else float(computed)  # nan guard

    return EvaluationResult(
        by_label=by_label,
        ranking_correct=synonym > related > unrelated,
        spearman=spearman,
        synonym_minus_unrelated=synonym - unrelated,
        related_minus_unrelated=related - unrelated,
        antonym_mean=by_label["antonym"].mean,
        complementary_mean=by_label["complementary"].mean,
        missing_terms=tuple(sorted(missing)),
    )


def expand_grid(grid: Mapping[str, Sequence]) -> list[dict]:
    """Cartesian product of the grid, in a deterministic order."""
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]


def sweep(
    builder: Callable[..., TagSpace],
    grid: Mapping[str, Sequence],
    gold: Sequence[GoldPair],
) -> list[tuple[dict, EvaluationResult]]:
    """Evaluate every point in the grid. The seed must be held fixed across a sweep.

    The real matrix's spectrum is near-degenerate, so varying the seed varies the basis; a
    sweep that let it move would be comparing bases rather than hyperparameters.
    """
    return [(point, evaluate_space(builder(**point), gold)) for point in expand_grid(grid)]


def render_evaluation(result: EvaluationResult) -> str:
    lines = [
        f"{'label':<15} {'pairs':>6} {'scored':>7} {'mean':>8} {'min':>8} {'max':>8}",
    ]
    for label in LABELS:
        s = result.by_label[label]
        graded = "" if label in GRADED else "   (recorded, not graded)"
        lines.append(
            f"{label:<15} {s.pairs:>6} {s.scored:>7} {s.mean:>8.3f} "
            f"{s.lowest:>8.3f} {s.highest:>8.3f}{graded}"
        )
    lines += [
        "",
        f"ranking synonym > related > unrelated : {'PASS' if result.ranking_correct else 'FAIL'}",
        f"spearman over graded labels           : {result.spearman:.3f}",
        f"synonym - unrelated                   : {result.synonym_minus_unrelated:+.3f}",
        f"related - unrelated                   : {result.related_minus_unrelated:+.3f}",
        "",
        "Phase 2 baseline (an unaided space is expected to score these high):",
        f"  antonym mean       : {result.antonym_mean:.3f}",
        f"  complementary mean : {result.complementary_mean:.3f}",
    ]
    if result.missing_terms:
        lines += [
            "",
            f"{len(result.missing_terms)} gold terms absent from the vocabulary "
            "(pairs skipped, reported so a shrinking vocabulary cannot look like a better "
            "score):",
            "  " + ", ".join(result.missing_terms),
        ]
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    from mldj.scrobbles import SCROBBLES_PATH, read_scrobbles
    from mldj.space.build import build_space, load_corpus_tags
    from mldj.space.space import DEFAULT_SPACE_PATH, save_space

    scrobbles = read_scrobbles(SCROBBLES_PATH)
    if not scrobbles:
        raise SystemExit("no history in data/scrobbles.jsonl - run `mldj ingest` first")
    corpus = load_corpus_tags(scrobbles)
    gold = load_gold()

    if args.sweep:
        grid = {
            "min_count": [2, 3, 5],
            "min_artists": [2, 3],
            "min_reach": [0, 200],
            "include_artists": [True, False],
            "rank": [50, 100, 150],
        }
        results = sweep(lambda **p: build_space(corpus, **p), grid, gold)
        results.sort(key=lambda pair: -pair[1].synonym_minus_unrelated)
        print(
            f"{'min_count':>9} {'min_art':>8} {'min_reach':>10} {'artists':>8} {'rank':>5} "
            f"{'vocab':>6} {'syn-unrel':>10} {'rank_ok':>8} {'anton':>7}"
        )
        for point, result in results:
            vocab = result.by_label["synonym"].scored
            print(
                f"{point['min_count']:>9} {point['min_artists']:>8} {point['min_reach']:>10} "
                f"{str(point['include_artists']):>8} {point['rank']:>5} {vocab:>6} "
                f"{result.synonym_minus_unrelated:>10.3f} "
                f"{'PASS' if result.ranking_correct else 'FAIL':>8} "
                f"{result.antonym_mean:>7.3f}"
            )
        return 0

    space = build_space(
        corpus,
        min_count=args.min_count,
        min_artists=args.min_artists,
        min_reach=args.min_reach,
        rank=args.rank,
        include_artists=not args.no_artists,
        seed=args.seed,
    )
    print(render_evaluation(evaluate_space(space, gold)))
    if args.save:
        save_space(space, DEFAULT_SPACE_PATH)
        print(f"\nwrote {DEFAULT_SPACE_PATH}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("space", help="build the tag space and evaluate it")
    parser.add_argument("--rank", type=int, default=150)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--min-artists", type=int, default=3)
    parser.add_argument("--min-reach", type=int, default=0)
    parser.add_argument("--no-artists", action="store_true", help="exclude artist columns")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sweep", action="store_true", help="grid search over the knobs")
    parser.add_argument("--save", action="store_true", help="write space.json")
    parser.set_defaults(handler=_run)

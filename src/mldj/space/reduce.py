"""Truncated SVD: PPMI rows become dense tag vectors.

A PPMI row is a few thousand mostly-empty cells saying which items a tag appeared on. Two
synonyms that happen never to share an item score zero similarity there, however alike their
contexts are. The reduction is what fixes that: projecting onto the leading components makes
tags similar when their *contexts* are similar, not only when they literally co-occurred.
That is the whole reason the space exists.

**Determinism is a requirement, not a nicety.** Two things make a naive SVD irreproducible,
and an irreproducible space cannot be evaluated - Task 8's numbers would drift between runs
for no reason connected to the data:

1. `svds` uses Lanczos iteration from a random start, so the starting vector is derived from
   an explicit seed.
2. Singular vector signs are not unique: (-u, -v) decomposes a matrix exactly as well as
   (u, v). Each component's sign is therefore pinned by forcing its largest-magnitude entry
   positive. Negating a whole component is a reflection of the row space, so every inner
   product between tag vectors is unchanged - this fixes the export without touching the
   geometry.

`svds` also makes no promise about the order of the values it returns, so they are sorted
descending here. Every downstream assumption that component 0 is the strongest rests on it.

**eigenvalue_weighting** is the exponent p in `U · Σ^p`. p=1 keeps the singular magnitudes,
so strong components dominate similarity; p=0 discards them, treating every retained
direction as equally important; p=0.5 is the usual compromise and the default. It is a real
choice about whether a tag's position should be dominated by the largest axes of variation -
which here are broad genre axes like rock/electronic - or spread across the finer ones that
distinguish moods. Task 8 settles it on evidence.
"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import svds

DEFAULT_RANK = 150
DEFAULT_EIGENVALUE_WEIGHTING = 0.5


def _validate(weighted: sparse.spmatrix, rank: int) -> int:
    rows, cols = weighted.shape
    limit = min(rows, cols)
    if rank < 1:
        raise ValueError(f"rank must be at least 1, got {rank}")
    if rank >= limit:
        raise ValueError(
            f"rank must be below min(shape)={limit} for a truncated SVD, got {rank}; "
            "lower the rank, lower min_count to widen the vocabulary, or add items"
        )
    return limit


def _decompose(
    weighted: sparse.spmatrix, rank: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Left singular vectors and values, ordered descending, with signs pinned."""
    matrix = sparse.csr_matrix(weighted, dtype=np.float64)
    limit = _validate(matrix, rank)

    if matrix.nnz == 0:
        return np.zeros((matrix.shape[0], rank)), np.zeros(rank)

    # Lanczos from a seeded start, so the same inputs always give the same output.
    v0 = np.random.default_rng(seed).standard_normal(limit)
    left, values, _ = svds(matrix, k=rank, v0=v0)

    order = np.argsort(values)[::-1]
    left, values = left[:, order], values[order]

    # Pin each component's sign by its largest-magnitude entry. argmax breaks ties by taking
    # the first index, which keeps this deterministic too.
    for component in range(left.shape[1]):
        column = left[:, component]
        if column[int(np.argmax(np.abs(column)))] < 0:
            left[:, component] = -column

    return left, values


def reduce_dimensions(
    weighted: sparse.spmatrix,
    rank: int = DEFAULT_RANK,
    eigenvalue_weighting: float = DEFAULT_EIGENVALUE_WEIGHTING,
    seed: int = 0,
) -> np.ndarray:
    """Dense tag vectors of shape (tags, rank), reproducible for a given input and seed."""
    left, values = _decompose(weighted, rank, seed)
    return np.ascontiguousarray(left * np.power(values, eigenvalue_weighting))


def singular_values(
    weighted: sparse.spmatrix, rank: int = DEFAULT_RANK, seed: int = 0
) -> np.ndarray:
    """The retained singular values, descending. Useful for choosing a rank by eye."""
    return _decompose(weighted, rank, seed)[1]


def explained_variance(
    weighted: sparse.spmatrix, rank: int = DEFAULT_RANK, seed: int = 0
) -> float:
    """Share of the matrix's squared Frobenius norm the retained components carry.

    A blunt instrument - it says how much of the matrix survives, not whether what survived
    is the semantically useful part - so it informs the rank sweep rather than deciding it.
    Task 8's gold set is what actually decides.
    """
    matrix = sparse.csr_matrix(weighted, dtype=np.float64)
    total = float(np.square(matrix.data).sum())
    if total == 0:
        return 0.0
    values = _decompose(matrix, rank, seed)[1]
    return float(np.square(values).sum() / total)

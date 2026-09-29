"""Positive pointwise mutual information over the tags x items matrix.

Raw counts say that `rock` and `alternative` co-occur a lot, but so does every popular tag
with every other popular tag. PMI asks the useful question instead: do these two co-occur
more than their individual frequencies would predict? That is what turns a popularity table
into evidence about meaning.

    PMI(t, i) = log( p(t, i) / (p(t) * p(i)) )
    PPMI      = max(0, PMI - shift)

Two options, each with a reason rather than a habit:

**context_smoothing** raises the item (context) probabilities to a power below 1 before
normalizing. Exponentiating a small number by 0.75 inflates it relative to a large one, so
rare contexts get more probability mass and co-occurring with them becomes less surprising.
Without it, PMI is famously biased toward rare contexts - a tag sharing its only item with
another tag scores enormously, on one observation. 0.75 is the standard correction; 1.0 is
the textbook unsmoothed definition.

**shift** is subtracted from PMI before clamping, which makes this shifted PPMI - equivalent
to what skip-gram with negative sampling implicitly factorizes when the shift is log k for k
negative samples. It raises the bar for a cell to survive at all, trading coverage for
confidence. Default 0.0 leaves the ordinary definition.

Negative PMI is clamped rather than kept. A negative value claims two tags co-occur *less*
than chance, and with a matrix this sparse that claim rests on almost no evidence - most
pairs simply never meet. Clamping is also what keeps the result sparse, and the clamped
cells are dropped rather than stored as explicit zeros: at a few thousand terms, keeping them
would make the "sparse" matrix dense in all but name.
"""

import numpy as np
from scipy import sparse

DEFAULT_CONTEXT_SMOOTHING = 0.75


def ppmi(
    counts: sparse.spmatrix,
    shift: float = 0.0,
    context_smoothing: float = DEFAULT_CONTEXT_SMOOTHING,
) -> sparse.csr_matrix:
    """PPMI-weight a tags x items count matrix, keeping it sparse throughout.

    Rows are targets (tags) and columns are contexts (items), so `context_smoothing`
    applies to the columns.
    """
    counts = sparse.csr_matrix(counts, dtype=np.float64)
    total = float(counts.sum())
    if total == 0:
        return sparse.csr_matrix(counts.shape, dtype=np.float64)

    target_totals = np.asarray(counts.sum(axis=1)).ravel()
    context_totals = np.asarray(counts.sum(axis=0)).ravel()

    p_target = target_totals / total
    smoothed = np.power(context_totals, context_smoothing)
    smoothed_total = smoothed.sum()
    p_context = (
        smoothed / smoothed_total if smoothed_total else np.zeros_like(smoothed, dtype=float)
    )

    # Work on the stored entries only: a zero cell has PMI of -inf, which clamps to zero
    # anyway, so materializing it would cost the whole point of a sparse matrix.
    entries = counts.tocoo()
    joint = entries.data / total
    expected = p_target[entries.row] * p_context[entries.col]

    with np.errstate(divide="ignore", invalid="ignore"):
        values = np.log(joint / expected) - shift
    # An empty row or column makes `expected` zero; the ratio is then inf or nan and carries
    # no information, so it is zeroed rather than allowed to propagate.
    values[~np.isfinite(values)] = 0.0
    values[values < 0.0] = 0.0

    weighted = sparse.csr_matrix(
        (values, (entries.row, entries.col)), shape=counts.shape, dtype=np.float64
    )
    weighted.eliminate_zeros()
    return weighted

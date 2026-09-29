"""Truncated SVD over a weighted matrix with deliberate block structure.

W has two blocks that share nothing: rows 0-2 live on columns 0-2, rows 3-5 on columns 3-5.
A reduction worth anything must keep rows inside a block similar and rows across blocks
apart, so that is asserted directly rather than inferred from singular values.
"""

import numpy as np
import pytest
from scipy import sparse

from mldj.space.reduce import explained_variance, reduce_dimensions

# Symmetric blocks, so the spectrum is exactly {8, 8, 1, 1, 1, 1} - deliberately
# degenerate, which is what makes the seed-dependence test below meaningful.
W = sparse.csr_matrix(
    np.array(
        [
            [3.0, 3.0, 2.0, 0.0, 0.0, 0.0],
            [3.0, 2.0, 3.0, 0.0, 0.0, 0.0],
            [2.0, 3.0, 3.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 3.0, 3.0, 2.0],
            [0.0, 0.0, 0.0, 3.0, 2.0, 3.0],
            [0.0, 0.0, 0.0, 2.0, 3.0, 3.0],
        ]
    )
)

# Same block structure, asymmetric entries, so the spectrum is distinct:
# 7.15, 3.57, 2.75, 1.57, 1.00, 0.22 with a smallest gap of 0.57.
DISTINCT = sparse.csr_matrix(
    np.array(
        [
            [4.0, 3.0, 1.0, 0.0, 0.0, 0.0],
            [3.5, 2.0, 0.5, 0.0, 0.0, 0.0],
            [1.0, 2.5, 3.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 2.0, 1.0, 0.5],
            [0.0, 0.0, 0.0, 0.5, 1.5, 1.0],
            [0.0, 0.0, 0.0, 1.0, 0.5, 2.5],
        ]
    )
)


def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def test_output_shape_is_vocab_by_rank():
    assert reduce_dimensions(W, rank=3).shape == (6, 3)


def test_the_same_input_and_seed_give_byte_identical_output():
    # An irreproducible space cannot be evaluated, and Lanczos is not deterministic without
    # a fixed starting vector.
    first = reduce_dimensions(W, rank=3, seed=7)
    second = reduce_dimensions(W, rank=3, seed=7)
    assert first.tobytes() == second.tobytes()


def test_different_seeds_agree_when_the_spectrum_is_distinct():
    # With distinct singular values the subspace is unique, so the only remaining freedom is
    # sign - and that is pinned, so two seeds must land on the same vectors.
    a = reduce_dimensions(DISTINCT, rank=3, seed=0)
    b = reduce_dimensions(DISTINCT, rank=3, seed=1234)
    np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-8)


def test_a_degenerate_spectrum_leaves_the_basis_seed_dependent():
    """Mathematics, not a defect - and the reason `seed` must be recorded in the export.

    W's spectrum is {8, 8, 1, 1, 1, 1}. When singular values repeat, the singular subspace
    is not unique: any orthogonal rotation inside it decomposes the matrix exactly as well,
    so no sign convention can make two starting vectors agree. Reproducibility is therefore
    per-seed, and a sweep must hold the seed fixed or it will compare bases rather than
    hyperparameters.
    """
    a = reduce_dimensions(W, rank=3, seed=0)
    b = reduce_dimensions(W, rank=3, seed=1234)
    assert not np.allclose(a, b, rtol=1e-6, atol=1e-8)
    # Per-seed determinism still holds, which is what the export actually relies on.
    assert reduce_dimensions(W, rank=3, seed=1234).tobytes() == b.tobytes()


def test_component_signs_are_deterministic():
    vectors = reduce_dimensions(W, rank=3)
    for k in range(vectors.shape[1]):
        column = vectors[:, k]
        assert column[int(np.argmax(np.abs(column)))] >= 0


def test_the_reduction_keeps_block_structure():
    vectors = reduce_dimensions(W, rank=2)
    within = cosine(vectors[0], vectors[1])
    across = cosine(vectors[0], vectors[3])
    assert within > 0.9
    assert across < 0.1


def test_rank_larger_than_the_matrix_is_rejected_clearly():
    with pytest.raises(ValueError, match="rank"):
        reduce_dimensions(W, rank=6)


def test_rank_below_one_is_rejected_clearly():
    with pytest.raises(ValueError, match="rank"):
        reduce_dimensions(W, rank=0)


def test_eigenvalue_weighting_of_zero_gives_unit_length_components():
    # p=0 discards singular magnitudes entirely, leaving the orthonormal basis.
    vectors = reduce_dimensions(W, rank=3, eigenvalue_weighting=0.0)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=0), 1.0, rtol=1e-10)


def test_eigenvalue_weighting_changes_vector_magnitudes():
    plain = reduce_dimensions(W, rank=3, eigenvalue_weighting=0.0)
    half = reduce_dimensions(W, rank=3, eigenvalue_weighting=0.5)
    full = reduce_dimensions(W, rank=3, eigenvalue_weighting=1.0)
    norms = [np.linalg.norm(v) for v in (plain, half, full)]
    assert norms[0] < norms[1] < norms[2]


def test_eigenvalue_weighting_does_not_change_the_leading_component_direction():
    # Scaling columns cannot rotate the basis, so the sign invariant still holds.
    for p in (0.0, 0.5, 1.0):
        column = reduce_dimensions(W, rank=2, eigenvalue_weighting=p)[:, 0]
        assert column[int(np.argmax(np.abs(column)))] >= 0


def test_explained_variance_rises_with_rank():
    assert explained_variance(W, 1) < explained_variance(W, 3) <= 1.0 + 1e-9


def test_explained_variance_of_the_block_matrix_is_high_at_rank_two():
    # Two blocks, so two components should already carry most of the matrix.
    assert explained_variance(W, 2) > 0.9


def test_explained_variance_of_an_empty_matrix_is_zero():
    assert explained_variance(sparse.csr_matrix((4, 5)), 2) == 0.0


def test_an_empty_matrix_reduces_to_zeros_rather_than_raising():
    vectors = reduce_dimensions(sparse.csr_matrix((4, 5)), rank=2)
    assert vectors.shape == (4, 2)
    assert not vectors.any()


def test_singular_values_are_ordered_descending():
    # scipy's svds does not guarantee an order, and every downstream assumption that
    # component 0 is the strongest depends on this.
    from mldj.space.reduce import singular_values

    values = singular_values(W, rank=4)
    assert list(values) == sorted(values, reverse=True)

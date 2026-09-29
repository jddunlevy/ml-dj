"""PPMI, checked against arithmetic done by hand.

The worked example throughout is

    M = [[1, 1],
         [1, 3]]          N = 6, row sums [2, 4], col sums [2, 4]

With no context smoothing and no shift, PMI(t, i) = log(M[t,i] * N / (row(t) * col(i))):

    PMI[0,0] = log(1*6 / (2*2)) = log(1.50)  =  0.4055
    PMI[0,1] = log(1*6 / (2*4)) = log(0.75)  = -0.2877  -> clamped to 0
    PMI[1,0] = log(1*6 / (4*2)) = log(0.75)  = -0.2877  -> clamped to 0
    PMI[1,1] = log(3*6 / (4*4)) = log(1.125) =  0.1178
"""

import math

import numpy as np
from scipy import sparse

from mldj.space.ppmi import ppmi

M = sparse.csr_matrix(np.array([[1, 1], [1, 3]], dtype=np.int32))

EXPECTED = np.array(
    [
        [math.log(1.5), 0.0],
        [0.0, math.log(1.125)],
    ]
)


def test_ppmi_of_a_hand_computed_two_by_two_is_exact():
    got = ppmi(M, context_smoothing=1.0).toarray()
    np.testing.assert_allclose(got, EXPECTED, rtol=1e-12, atol=1e-12)


def test_negative_pmi_is_clamped_to_zero():
    got = ppmi(M, context_smoothing=1.0).toarray()
    assert got[0, 1] == 0.0
    assert got[1, 0] == 0.0
    assert (got >= 0).all()


def test_independent_tag_and_item_scores_zero():
    # p(t,i) == p(t)p(i) everywhere, so every PMI is log(1) = 0.
    independent = sparse.csr_matrix(np.ones((2, 2), dtype=np.int32))
    assert ppmi(independent, context_smoothing=1.0).nnz == 0


def test_context_smoothing_lowers_the_score_of_a_rare_context():
    # Raising a small column sum to a power below 1 inflates its probability, which shrinks
    # the surprise of co-occurring with it - the standard correction for PMI's bias toward
    # rare contexts.
    rare = sparse.csr_matrix(np.array([[3, 1], [0, 8]], dtype=np.int32))
    unsmoothed = ppmi(rare, context_smoothing=1.0).toarray()[0, 0]
    smoothed = ppmi(rare, context_smoothing=0.75).toarray()[0, 0]
    assert unsmoothed > smoothed > 0


def test_context_smoothing_of_one_is_the_unsmoothed_definition():
    exact = ppmi(M, context_smoothing=1.0).toarray()
    np.testing.assert_allclose(exact, EXPECTED, rtol=1e-12, atol=1e-12)


def test_shift_subtracts_before_clamping():
    # shift is the amount taken off PMI, i.e. log k for k negative samples. Removing exactly
    # PMI[0,0] must take that cell to zero rather than to a small positive number.
    got = ppmi(M, shift=math.log(1.5), context_smoothing=1.0).toarray()
    assert got[0, 0] == 0.0


def test_a_larger_shift_removes_more_cells():
    few = ppmi(M, shift=0.0, context_smoothing=1.0).nnz
    fewer = ppmi(M, shift=1.0, context_smoothing=1.0).nnz
    assert fewer < few


def test_result_stays_sparse_and_drops_the_clamped_cells():
    result = ppmi(M, context_smoothing=1.0)
    assert sparse.issparse(result)
    # Two of four cells clamp to zero and must not stay stored, or the "sparse" matrix is
    # dense in all but name once the vocabulary is thousands of terms wide.
    assert result.nnz == 2


def test_an_all_zero_row_does_not_divide_by_zero():
    # A vocabulary term that survived min_count but appears on no item in this matrix.
    with_empty_row = sparse.csr_matrix(np.array([[1, 1], [0, 0], [1, 3]], dtype=np.int32))
    result = ppmi(with_empty_row, context_smoothing=1.0).toarray()
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(result[1], [0.0, 0.0])


def test_an_all_zero_column_does_not_divide_by_zero():
    with_empty_col = sparse.csr_matrix(np.array([[1, 0, 1], [1, 0, 3]], dtype=np.int32))
    result = ppmi(with_empty_col, context_smoothing=1.0).toarray()
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(result[:, 1], [0.0, 0.0])


def test_an_all_zero_matrix_returns_all_zeros():
    result = ppmi(sparse.csr_matrix((3, 4), dtype=np.int32))
    assert result.shape == (3, 4)
    assert result.nnz == 0


def test_shape_is_preserved():
    assert ppmi(sparse.csr_matrix(np.ones((5, 7), dtype=np.int32))).shape == (5, 7)


def test_accepts_a_binary_presence_matrix_like_the_real_one():
    counts = sparse.csr_matrix(
        np.array([[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1]], dtype=np.int32)
    )
    result = ppmi(counts)
    assert sparse.issparse(result)
    assert (result.toarray() >= 0).all()
    assert result.nnz > 0

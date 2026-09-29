"""The semantic space: vocabulary, assignment, matrix, PPMI, SVD, evaluation.

Pure offline Python. Nothing here runs at listen time; the boundary to the live client is
a versioned space.json.
"""

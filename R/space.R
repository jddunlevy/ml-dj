#' The tag space: terms, their dense vectors, and the operations over them.
#'
#' space.json is gitignored because four of its terms are artist names carried over from the
#' corpus. They are dropped here, at load, rather than at each display site - one exclusion
#' cannot be forgotten, six can.

#' Normalized term keys, not display names. See the Phase 1 plan's privacy review.
EXCLUDED_TERMS <- c("radiohead", "kanyewest", "kendricklamar", "timbaland")

load_space <- function(path = "space.json", exclude = EXCLUDED_TERMS) {
  if (!file.exists(path)) {
    stop("no space.json at '", path, "' - build it with `mldj space`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path)

  keep <- !(raw$terms %in% exclude)
  terms <- raw$terms[keep]
  vectors <- raw$vectors[keep, , drop = FALSE]

  display <- vapply(terms, function(t) raw$display[[t]] %||% t, character(1))
  names(display) <- terms

  norms <- sqrt(rowSums(vectors^2))
  norms[norms == 0] <- 1
  unit <- vectors / norms

  rownames(vectors) <- terms
  rownames(unit) <- terms

  list(terms = terms, display = display, vectors = vectors, unit = unit, meta = raw$meta)
}

#' Sum of the unit vectors of the recognised tags. Unit-normalized before summing so a
#' six-tag track does not outweigh a two-tag one by sheer count. Unknown tags are dropped
#' rather than raised: Last.fm returns tags the vocabulary filtered out, routinely.
tag_vector <- function(space, tags) {
  known <- intersect(tags, space$terms)
  if (length(known) == 0) return(rep(0, ncol(space$vectors)))
  colSums(space$unit[known, , drop = FALSE])
}

#' Cosine of v against every term, named by term. A zero vector scores zero everywhere
#' rather than producing NaN.
cosine_all <- function(space, v) {
  n <- sqrt(sum(v^2))
  if (n == 0) return(stats::setNames(rep(0, length(space$terms)), space$terms))
  stats::setNames(as.vector(space$unit %*% (v / n)), space$terms)
}

`%||%` <- function(a, b) if (is.null(a)) b else a

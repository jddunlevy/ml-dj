#' Ranking the prefetched pool against the session vector.
#'
#' The ranking returns every candidate, not a top-N. The pitch's claim is "the DJ played
#' something this engine ranked 47th", and a truncated ranking cannot make that claim - the UI
#' truncates for display, the ranking does not.

read_candidates <- function(path) {
  if (!file.exists(path)) {
    stop("no candidate pool at '", path, "' - run `mldj candidates`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  lapply(raw$candidates, function(c) {
    c$tags <- as.character(unlist(c$tags) %||% character(0))
    c$novel <- isTRUE(c$novel)
    c
  })
}

#' epsilon is the exploration knob the parent spec makes user-visible: the amount a
#' never-before-heard candidate is lifted. Novelty is an upper bound (the scrobble hole), so a
#' large epsilon amplifies a number that is already generous. Default it low.
rank_candidates <- function(space, v, candidates, actual = NULL, epsilon = 0) {
  if (length(candidates) == 0) {
    return(data.frame(rank = integer(0), artist = character(0), title = character(0),
                      score = numeric(0), novel = logical(0), is_actual = logical(0),
                      stringsAsFactors = FALSE))
  }

  nv <- sqrt(sum(v^2))
  score <- vapply(candidates, function(c) {
    cv <- tag_vector(space, c$tags)
    ncv <- sqrt(sum(cv^2))
    if (nv == 0 || ncv == 0) 0 else sum(cv * v) / (ncv * nv)
  }, numeric(1))

  novel <- vapply(candidates, function(c) isTRUE(c$novel), logical(1))

  d <- data.frame(
    artist = vapply(candidates, function(c) c$artist, character(1)),
    title  = vapply(candidates, function(c) c$title, character(1)),
    novel  = novel,
    score  = score + epsilon * novel, stringsAsFactors = FALSE
  )
  d <- d[order(-d$score), ]
  d$rank <- seq_len(nrow(d))
  d$is_actual <- if (is.null(actual)) {
    rep(FALSE, nrow(d))
  } else {
    d$artist == actual$artist & d$title == actual$title
  }
  rownames(d) <- NULL
  d[, c("rank", "artist", "title", "score", "novel", "is_actual")]
}

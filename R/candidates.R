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
    c$key <- as.character(unlist(c$key) %||% character(0))
    c$novel <- isTRUE(c$novel)
    c
  })
}

#' The pool's strings come from Last.fm and the DJ's pick comes from Spotify capture, so the
#' two name one track two ways - "Blue Monday - 2016 Remaster" against "Blue Monday". Both
#' `mldj candidates` and `mldj export-session` emit `key` from match.track_key precisely so R
#' never has to know that; R compares keys and owns no matcher of its own. A second
#' implementation of match.py in a second language is free to drift from the first, and the
#' failure is silent: a missed join reads as "the DJ's pick was not in the pool", which is the
#' pitch's headline claim quietly vanishing.
#'
#' Raw strings remain the fallback for hand-written fixtures and for any pool predating the
#' key. Falling back per row rather than wholesale means a keyed pool still joins correctly
#' when a single row lacks one.
matches_actual <- function(candidates, actual) {
  vapply(candidates, function(c) {
    ck <- as.character(c$key %||% character(0))
    ak <- as.character(actual$key %||% character(0))
    if (length(ck) == 2 && length(ak) == 2) {
      return(identical(ck, ak))
    }
    identical(c$artist, actual$artist) && identical(c$title, actual$title)
  }, logical(1))
}

#' epsilon is the exploration knob the parent spec makes user-visible: the amount a
#' never-before-heard candidate is lifted. Novelty is an upper bound (the scrobble hole), so a
#' large epsilon amplifies a number that is already generous. Default it low.
rank_candidates <- function(space, v, candidates, actual = NULL, epsilon = 0) {
  # candidate_pool drops every track played in the session, and the DJ's next pick is one of
  # them - so the pick is absent from the pool by construction, in production as much as in
  # the fixtures. Excluding played tracks is right for recommending and wrong for evaluating,
  # and the pitch needs both: "what I'd play next" from the pool, "where the DJ's choice
  # landed" from the pool PLUS that choice. So it is scored against the same session vector
  # and spliced in. The rank it gets is its rank among everything considered, which is the
  # only reading of "ranked 47th" that means anything.
  #
  # It needs tags to be scoreable. An untaggable pick is left out rather than entered at a
  # score of zero, which would invent a rank for a track nothing is known about.
  if (!is.null(actual) && length(as.character(unlist(actual$tags) %||% character(0))) > 0) {
    if (!any(matches_actual(candidates, actual))) {
      spliced <- list(artist = actual$artist, title = actual$title,
                      key = as.character(unlist(actual$key) %||% character(0)),
                      tags = as.character(unlist(actual$tags)),
                      novel = isTRUE(actual$novel))
      candidates <- c(candidates, list(spliced))
    }
  }

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
  # Computed before the sort, against the candidate list, so the flag follows its own row
  # rather than a position that reordering would invalidate.
  d$is_actual <- if (is.null(actual)) rep(FALSE, nrow(d)) else matches_actual(candidates, actual)

  d <- d[order(-d$score), ]
  d$rank <- seq_len(nrow(d))
  rownames(d) <- NULL
  d[, c("rank", "artist", "title", "score", "novel", "is_actual")]
}

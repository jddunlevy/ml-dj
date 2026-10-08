#' The replay source: a session derived by `mldj export-session`.
#'
#' This file deliberately does no skip detection. `mldj.skips.derive_plays` already does it,
#' tested, and two implementations of one rule is one implementation too many.
#'
#' simplifyVector = FALSE keeps the events as a list of lists. With simplification on,
#' jsonlite turns a one-tag event's `tags` into a bare string and a multi-tag event's into a
#' character vector, so the same field has two shapes depending on the data - which is exactly
#' the bug that shows up only on the one track with a single tag.
#'
#' earliness is deliberately not defaulted here. `engine.R` treats a skipped event with no
#' earliness as malformed source data and stops loudly on it; supplying a default in this
#' module would mean that guard never sees a NULL and can never fire.

read_session <- function(path) {
  if (!file.exists(path)) {
    stop("no session at '", path, "' - run `mldj export-session`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  raw$events <- lapply(raw$events, function(e) {
    e$tags <- as.character(unlist(e$tags) %||% character(0))
    e$earliness <- if (is.null(e$earliness)) NULL else as.numeric(e$earliness)
    e$ts <- as.numeric(e$ts %||% 0)
    e
  })
  raw
}

#' The track `mldj next` actually queued on Spotify, or NULL if nothing has been.
#'
#' Deliberately NULL rather than an error on a missing file: until the first queue write of a
#' session there is legitimately nothing to show, which is a state the app renders rather than
#' a fault. A truncated read is also NULL - `mldj next` rewrites the file in place and the
#' app's file reader polls on a timer, so landing mid-write is expected, not exceptional.
#'
#' The app shows THIS rather than re-ranking on its own, so that what is on screen is the
#' track that reached the wire. The queue is written from the library pool - the only pool
#' whose rows carry a Spotify URI - while "what i'd play next" ranks the Last.fm candidate
#' pool, so the two can legitimately disagree. Reporting the write is what keeps the screen
#' from contradicting the queue in front of a room.

read_queued <- function(path) {
  if (!file.exists(path)) {
    return(NULL)
  }
  q <- tryCatch(jsonlite::fromJSON(path, simplifyVector = TRUE), error = function(e) NULL)
  if (!is.list(q) || is.null(q$uri) || !nzchar(as.character(q$uri))) {
    return(NULL)
  }
  q
}

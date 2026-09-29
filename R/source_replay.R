#' The replay source: a session derived by `mldj export-session`.
#'
#' This file deliberately does no skip detection. `mldj.skips.derive_plays` already does it,
#' tested, and two implementations of one rule is one implementation too many.
#'
#' simplifyVector = FALSE keeps the events as a list of lists. With simplification on,
#' jsonlite turns a one-tag event's `tags` into a bare string and a multi-tag event's into a
#' character vector, so the same field has two shapes depending on the data - which is exactly
#' the bug that shows up only on the one track with a single tag.

read_session <- function(path) {
  if (!file.exists(path)) {
    stop("no session at '", path, "' - run `mldj export-session`", call. = FALSE)
  }
  raw <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  raw$events <- lapply(raw$events, function(e) {
    e$tags <- as.character(unlist(e$tags) %||% character(0))
    e$earliness <- as.numeric(e$earliness %||% 0)
    e$ts <- as.numeric(e$ts %||% 0)
    e
  })
  raw
}

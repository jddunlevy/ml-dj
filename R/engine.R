#' The session vector.
#'
#'   completed  v <- v*decay + w * sum(tags)
#'   skipped    v <- v*decay - w * sum(tags) * earliness
#'   unknown    v <- v*decay
#'
#' An unknown outcome decays without updating: an ambiguous record may not have been a skip,
#' so it cannot found a negative claim. Phase 0 applies the same rule to persistence and
#' repetition, and the prototype must not be more confident than the measurement was. A skipped
#' event missing earliness is the same kind of ambiguity, not a license to assume full-strength
#' penalty, so it raises instead of defaulting to 1.
#'
#' Negative updates subtract the skipped track's own tag vector. The parent spec calls for
#' projecting along antonym-derived axes instead; that is Phase 2 work and it replaces exactly
#' the one line marked below. State this in beat 6 rather than hiding it.

session_new <- function(space, decay = 0.85, w = 1.0) {
  list(space = space, decay = decay, w = w,
       v = rep(0, ncol(space$vectors)), history = list())
}

session_step <- function(state, event) {
  v <- state$v * state$decay
  outcome <- event$outcome

  if (outcome == "completed") {
    v <- v + state$w * tag_vector(state$space, unlist(event$tags))
  } else if (outcome == "skipped") {
    if (is.null(event$earliness)) {
      stop("skipped event has no earliness - malformed source data", call. = FALSE)
    }
    earliness <- max(0, min(1, event$earliness))
    # <- Phase 2 replaces this line with a projection along antonym axes
    v <- v - state$w * tag_vector(state$space, unlist(event$tags)) * earliness
  } else if (outcome != "unknown") {
    stop("unknown outcome '", outcome, "' - expected completed, skipped or unknown",
         call. = FALSE)
  }

  state$v <- v
  state$history <- c(state$history, list(event))
  state
}

session_run <- function(state, events) {
  for (e in events) state <- session_step(state, e)
  state
}

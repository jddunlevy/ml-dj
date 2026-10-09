#' Fire `mldj next` from the app, without R ever reaching the wire.
#'
#' The button is a convenience for presenting: stepping out to a terminal mid-pitch breaks the
#' demo. It is NOT a second implementation. Python still owns the token, the engine, the
#' ranking and the single queue write; R only starts the process and reports what it said.
#' That keeps the rule the whole project is built on - one implementation of one rule - and it
#' is why this file contains no scoring, no auth and no HTTP.
#'
#' `runner` is injected so the command can be tested without launching anything. Same reason
#' every network boundary in the Python side takes a transport.

MLDJ_PYTHON <- Sys.getenv("MLDJ_PYTHON", ".venv/Scripts/python.exe")

#' The argv for one queue write. Split out from the call so a test can assert on it: getting
#' `-m mldj next` wrong fails at demo time and nowhere earlier.
queue_args <- function(dry_run = FALSE, force = FALSE) {
  args <- c("-m", "mldj", "next")
  if (dry_run) args <- c(args, "--dry-run")
  if (force) args <- c(args, "--force")
  args
}

#' Run it and hand back what it printed, whether or not it succeeded.
#'
#' Never throws. A demo that dies because a subprocess exited non-zero is worse than one that
#' prints the reason on screen, and the reasons are all things worth seeing out loud: no active
#' device, a dead token, or the engine declining because the vector is too weak.
trigger_queue <- function(python = MLDJ_PYTHON, dry_run = FALSE, force = FALSE,
                          runner = NULL) {
  runner <- runner %||% function(cmd, args) {
    suppressWarnings(system2(cmd, args, stdout = TRUE, stderr = TRUE))
  }
  out <- tryCatch(runner(python, queue_args(dry_run, force)),
                  error = function(e) paste("could not run", python, "-", conditionMessage(e)))
  if (is.null(out) || length(out) == 0) out <- "(no output)"
  paste(as.character(out), collapse = "\n")
}

#' The one line worth putting on screen. `mldj next` prints the session, the pick and the
#' outcome; the outcome is the last thing it says and is what the room needs to see.
queue_summary <- function(output) {
  lines <- trimws(strsplit(output, "\n", fixed = TRUE)[[1]])
  lines <- lines[nzchar(lines)]
  if (length(lines) == 0) return("(no output)")
  lines[length(lines)]
}

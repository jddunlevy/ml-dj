SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")
TRACE_PATH <- file.path(PROJECT_ROOT, "fixtures", "engine-trace.json")

test_that("the engine still reproduces the golden trace", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  expect_true(file.exists(TRACE_PATH))

  golden <- jsonlite::fromJSON(TRACE_PATH, simplifyVector = FALSE)
  sp <- load_space(SPACE_PATH)

  # The trace records cosines, so it pins the algorithm AND the space it was taken against.
  # A rebuilt vocabulary shifts every number while the engine is untouched, and without this
  # check the failure reads as "the engine changed" and sends you hunting in the wrong file.
  if (!is.null(golden$space_terms)) {
    expect_equal(
      length(sp$terms), golden$space_terms,
      info = paste0("space.json has ", length(sp$terms), " terms, the trace was taken ",
                    "against ", golden$space_terms, " - rebuild the trace with ",
                    "tools/build-engine-trace.R, the engine is not at fault")
    )
  }
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events

  state <- session_new(sp, decay = golden$decay, w = golden$w)
  for (i in seq_along(events)) {
    state <- session_step(state, events[[i]])
    top <- head(sort(cosine_all(sp, state$v), decreasing = TRUE), 5)
    expected <- golden$steps[[i]]
    expect_equal(names(top), unlist(expected$terms),
                 info = paste("step", i, "term order changed"))
    expect_equal(unname(round(top, 6)), unlist(expected$cos),
                 tolerance = 1e-6, info = paste("step", i, "cosines changed"))
  }
})

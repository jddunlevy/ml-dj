test_that("the synthetic session has the shape the prototype expects", {
  s <- jsonlite::fromJSON(
    file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"), simplifyVector = FALSE
  )
  expect_true(all(c("session", "label", "events") %in% names(s)))
  expect_gte(length(s$events), 8)

  outcomes <- vapply(s$events, function(e) e$outcome, character(1))
  expect_true(all(outcomes %in% c("completed", "skipped", "unknown")))
  expect_true(any(outcomes == "skipped"))
  expect_true(any(outcomes == "unknown"))

  for (e in s$events) {
    expect_true(is.numeric(e$earliness) && e$earliness >= 0 && e$earliness <= 1)
    expect_true(length(e$tags) > 0 || e$outcome == "unknown")
  }
})

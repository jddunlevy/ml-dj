FIXTURE <- file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json")

test_that("a derived session reads back with its events in order", {
  s <- read_session(FIXTURE)
  expect_equal(s$label, "dj")
  expect_gte(length(s$events), 8)
  ts <- vapply(s$events, function(e) e$ts, numeric(1))
  expect_false(is.unsorted(ts))
})

test_that("tags come back as a character vector, not a nested list", {
  s <- read_session(FIXTURE)
  expect_type(s$events[[1]]$tags, "character")
})

test_that("a single-tag event does not collapse to a scalar of the wrong shape", {
  s <- read_session(FIXTURE)
  for (e in s$events) expect_true(is.character(e$tags))
})

test_that("a missing file fails loudly rather than returning empty", {
  expect_error(read_session(file.path(PROJECT_ROOT, "fixtures", "nope.json")), "no session")
})

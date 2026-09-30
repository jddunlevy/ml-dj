SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

test_that("reading_data returns the strongest toward and away terms", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  v <- tag_vector(sp, c("dreampop", "shoegaze")) - tag_vector(sp, "dance")
  d <- reading_data(sp, v, n_toward = 4, n_away = 2)

  expect_equal(nrow(d), 6)
  expect_equal(sum(d$sign == "toward"), 4)
  expect_equal(sum(d$sign == "away"), 2)
  expect_false(is.unsorted(rev(d$cos[d$sign == "toward"])))
  expect_true(all(d$cos[d$sign == "toward"] >= d$cos[d$sign == "away"]))
})

test_that("reading_data labels with display names, never raw term keys", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, tag_vector(sp, "dreampop"), n_toward = 3, n_away = 1)
  expect_true("dream pop" %in% d$tag)
  expect_false("dreampop" %in% d$tag)
})

test_that("no excluded artist term can appear in a reading", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, tag_vector(sp, "hiphop"), n_toward = 20, n_away = 20)
  expect_false(any(tolower(gsub(" ", "", d$tag)) %in% EXCLUDED_TERMS))
})

test_that("reading_data keeps toward and away disjoint even when windows would overlap", {
  # A deliberately tiny candidate set: with n_toward = 3 and n_away = 3 against only 4 terms,
  # the naive head()/tail() split would have put "b" and "c" in both groups.
  terms <- c("a", "b", "c", "d")
  vectors <- diag(4)
  rownames(vectors) <- terms
  space <- list(terms = terms, display = stats::setNames(terms, terms),
                vectors = vectors, unit = vectors)
  v <- c(1, 0.5, 0, -1)
  d <- reading_data(space, v, n_toward = 3, n_away = 3)
  expect_equal(length(unique(d$tag)), nrow(d))
})

test_that("plot_reading survives duplicate display labels", {
  d <- data.frame(
    tag = c("same label", "same label", "other"),
    cos = c(0.5, -0.3, 0.1),
    sign = c("toward", "away", "toward"),
    stringsAsFactors = FALSE
  )
  p <- plot_reading(d)
  expect_s3_class(p, "ggplot")
})

test_that("plot_reading returns a ggplot without drawing it", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  p <- plot_reading(reading_data(sp, tag_vector(sp, "dreampop")))
  expect_s3_class(p, "ggplot")
})

test_that("a zero vector still produces a plottable frame", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- reading_data(sp, rep(0, ncol(sp$vectors)))
  expect_gt(nrow(d), 0)
  expect_true(all(d$cos == 0))
})

test_that("the layout is stable across calls, even across a forced recompute", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  a <- space_layout(sp)
  # Force the cache to actually recompute the SVD from scratch, so this test can catch a sign
  # flip across fresh processes rather than just hitting the same cache entry twice.
  space_basis_reset()
  b <- space_layout(sp)
  expect_equal(a$x, b$x)
  expect_equal(a$y, b$y)
})

test_that("labelled terms are separated by at least min_sep of the span", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  lay <- space_layout(sp, n_labels = 20, min_sep = 0.1)
  lab <- lay[lay$label, ]
  span <- max(diff(range(lay$x)), diff(range(lay$y)))
  d <- as.matrix(stats::dist(cbind(lab$x, lab$y)))
  diag(d) <- Inf
  expect_gte(min(d), 0.1 * span)
})

test_that("trail_data projects in the same coordinate system as the term backdrop", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  term <- sp$terms[1]
  state <- list(v = sp$vectors[term, ], history = list())
  lay <- space_layout(sp)
  tr <- trail_data(sp, lay, list(state))
  expected <- lay[lay$term == term, c("x", "y")]

  # Before the FIX 1 centring correction, this would be off by exactly mu %*% P - the offset
  # between the backdrop's centred basis and the trail's uncentred projection.
  expect_equal(tr$x[1], expected$x, tolerance = 1e-8)
  expect_equal(tr$y[1], expected$y, tolerance = 1e-8)
})

test_that("the trail has one row per state and marks skips", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events
  states <- Reduce(function(s, e) session_step(s, e), events, session_new(sp), accumulate = TRUE)
  states <- states[-1]
  tr <- trail_data(sp, space_layout(sp), states)
  expect_equal(nrow(tr), length(events))
  expect_true(any(tr$outcome == "skipped"))
})

test_that("plot_constellation returns a ggplot", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events
  states <- Reduce(function(s, e) session_step(s, e), events, session_new(sp), accumulate = TRUE)
  lay <- space_layout(sp)
  expect_s3_class(plot_constellation(lay, trail_data(sp, lay, states[-1])), "ggplot")
})

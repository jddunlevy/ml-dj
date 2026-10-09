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

test_that("the backdrop plots only the labelled terms, not the whole vocabulary", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  events <- read_session(file.path(PROJECT_ROOT, "fixtures", "session-synthetic.json"))$events
  states <- Reduce(function(s, e) session_step(s, e), events, session_new(sp), accumulate = TRUE)
  lay <- space_layout(sp)
  p <- plot_constellation(lay, trail_data(sp, lay, states[-1]))

  # 285 of 367 terms sit within 10% of the span of the median point, so drawing them all
  # produces a grey blob at the origin that no amount of label thinning fixes. A point the
  # audience cannot attach a name to carries no information and costs legibility.
  expect_equal(nrow(ggplot2::layer_data(p, 1)), sum(lay$label))
  expect_lt(nrow(ggplot2::layer_data(p, 1)), nrow(lay))
})

test_that("labelled terms clear an exclusion ellipse, not a circle", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  d <- space_layout(sp)
  lab <- d[d$label, ]
  span <- max(diff(range(d$x)), diff(range(d$y)))

  # Rendered labels are far wider than they are tall, so two points separated well enough
  # vertically can still have their text run together horizontally ("female vocalists" over
  # "beautiful" did exactly this). The keep rule uses an ellipse matching that geometry.
  # Derived from the real defaults, not a copy of them. This hardcoded 0.095 and started
  # failing the moment the default moved - it was asserting against a number the
  # implementation no longer used.
  #
  # The half-width is per label, scaled by its own character count, and a pair is checked
  # against the mean of the two. A single fixed width let "female vocalists" run through
  # "melancholy" while reserving dead space around "90s".
  widths <- nchar(lab$tag)
  ref <- stats::median(nchar(d$tag))
  half_w <- (WIDE / 2) * DEFAULT_MIN_SEP * span * widths / ref
  b <- FLAT * DEFAULT_MIN_SEP * span
  for (i in seq_len(nrow(lab))) {
    for (j in seq_len(nrow(lab))) {
      if (i >= j) next
      dx <- lab$x[i] - lab$x[j]
      dy <- lab$y[i] - lab$y[j]
      a <- half_w[i] + half_w[j]  # each label extends from its own point: sum, not mean
      expect_gte((dx / a)^2 + (dy / b)^2, 1)
    }
  }
})

# The session vector is a decayed SUM of tag vectors, so its magnitude grows without bound
# while term positions stay fixed and small. Projected raw it leaves the term cloud entirely:
# measured on a real 19-event session, 13 of 19 trail points fell outside the extent of the
# whole 319-term vocabulary, in territory where no tag exists at any radius.
#
# The engine ranks by cosine, which is direction only - magnitude changes nothing about which
# track gets picked. The plot was therefore spending most of its canvas on a quantity the
# recommender does not use, and that quantity was what pushed the dot into empty space.

a_state <- function(v, outcome = "completed") {
  list(list(v = v, history = list(list(outcome = outcome))))
}

test_that("direction still moves the point", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  ld <- space_layout(sp)

  a <- trail_data(sp, ld, a_state(tag_vector(sp, "dreampop")))
  b <- trail_data(sp, ld, a_state(tag_vector(sp, "dance")))

  expect_false(isTRUE(all.equal(c(a$x, a$y), c(b$x, b$y))))
})

test_that("a zero vector does not produce NaN", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  tr <- trail_data(sp, space_layout(sp), list(list(v = rep(0, ncol(sp$vectors)),
                                                   history = list())))

  expect_false(any(is.na(tr$x)))
  expect_false(any(is.na(tr$y)))
})

test_that("a vector with real accumulated magnitude still plots among the tags", {
  # The whole point: it must land where the things it is compared against live. Clamped, not
  # normalised - see trail_data. A term's own vector is unaffected, which is asserted above by
  # "trail_data projects in the same coordinate system as the term backdrop".
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  ld <- space_layout(sp)
  big <- tag_vector(sp, c("dreampop", "shoegaze", "indie")) * 25

  tr <- trail_data(sp, ld, a_state(big))

  expect_gte(tr$x, min(ld$x) - 1)
  expect_lte(tr$x, max(ld$x) + 1)
  expect_gte(tr$y, min(ld$y) - 1)
  expect_lte(tr$y, max(ld$y) + 1)
})

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

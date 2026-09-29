SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

test_that("the four artist-name terms never reach the loaded space", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored; build it with `mldj space`")
  sp <- load_space(SPACE_PATH)
  expect_false(any(c("radiohead", "kanyewest", "kendricklamar", "timbaland") %in% sp$terms))
})

test_that("the loaded space is internally consistent", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_equal(nrow(sp$vectors), length(sp$terms))
  expect_equal(nrow(sp$unit), length(sp$terms))
  expect_true(all(sp$terms %in% names(sp$display)))
})

test_that("unit rows are unit length", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  norms <- sqrt(rowSums(sp$unit^2))
  expect_true(all(abs(norms - 1) < 1e-8))
})

test_that("tag_vector sums the unit rows of the tags it recognises", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  one <- tag_vector(sp, "dreampop")
  two <- tag_vector(sp, c("dreampop", "shoegaze"))
  expect_equal(length(one), ncol(sp$vectors))
  expect_false(isTRUE(all.equal(one, two)))
})

test_that("tag_vector ignores unknown tags instead of failing", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_equal(tag_vector(sp, c("dreampop", "nosuchtag")), tag_vector(sp, "dreampop"))
})

test_that("tag_vector returns zeros when nothing is recognised", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  expect_true(all(tag_vector(sp, c("nosuchtag", "alsonone")) == 0))
})

test_that("a tag is its own nearest term by cosine", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cos <- cosine_all(sp, tag_vector(sp, "dreampop"))
  expect_equal(names(which.max(cos)), "dreampop")
})

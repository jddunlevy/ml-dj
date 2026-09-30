SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")
CAND <- file.path(PROJECT_ROOT, "fixtures", "candidates-synthetic.json")

test_that("candidates rank by cosine against the session vector", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  v <- tag_vector(sp, c("dreampop", "shoegaze"))
  r <- rank_candidates(sp, v, read_candidates(CAND))
  expect_equal(r$rank, seq_len(nrow(r)))
  expect_false(is.unsorted(rev(r$score)))
})

test_that("the DJ's actual pick is flagged wherever it lands", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- read_candidates(CAND)
  actual <- list(artist = cands[[length(cands)]]$artist, title = cands[[length(cands)]]$title)
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)
  expect_equal(sum(r$is_actual), 1)
})

test_that("an actual pick absent from the pool flags nothing rather than erroring", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), read_candidates(CAND),
                       actual = list(artist = "Nobody", title = "Nothing"))
  expect_equal(sum(r$is_actual), 0)
})

test_that("a candidate whose tags are all unknown scores zero, not NA", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(list(artist = "X", title = "Y", tags = c("nosuchtag")))
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands)
  expect_equal(r$score[1], 0)
})

test_that("epsilon lifts a novel candidate above an identical familiar one", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "Known", title = "K", tags = "dreampop", novel = FALSE),
    list(artist = "Fresh", title = "F", tags = "dreampop", novel = TRUE)
  )
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, epsilon = 0.2)
  expect_equal(r$artist[1], "Fresh")
})

test_that("epsilon of zero ignores novelty entirely", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "Known", title = "K", tags = "dreampop", novel = FALSE),
    list(artist = "Fresh", title = "F", tags = "dreampop", novel = TRUE)
  )
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, epsilon = 0)
  expect_equal(r$score[1], r$score[2])
})

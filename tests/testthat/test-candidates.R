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

test_that("the actual pick matches on the normalized key, not on raw strings", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  # The pool's title came from Last.fm, the DJ's from Spotify. They name one track two ways.
  # Joining on raw strings flags nothing and reads as "the DJ's pick was not in the pool" -
  # the pitch's whole claim, lost silently. mldj candidates and mldj export-session both
  # emit `key` from match.track_key so this join never depends on the strings agreeing.
  cands <- list(
    list(artist = "New Order", title = "Blue Monday - 2016 Remaster",
         key = c("new order", "blue monday"), tags = "dreampop", novel = TRUE)
  )
  actual <- list(artist = "New Order", title = "Blue Monday",
                 key = c("new order", "blue monday"))
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)
  expect_equal(sum(r$is_actual), 1)
  # Display still shows what Last.fm actually called it.
  expect_equal(r$title[1], "Blue Monday - 2016 Remaster")
})

test_that("a keyed actual pick never matches a different track that shares no key", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "New Order", title = "Blue Monday", key = c("new order", "blue monday"),
         tags = "dreampop", novel = TRUE)
  )
  actual <- list(artist = "New Order", title = "Temptation",
                 key = c("new order", "temptation"))
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)
  expect_equal(sum(r$is_actual), 0)
})

test_that("the actual pick is ranked even though the pool excludes it by construction", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  # candidate_pool drops every track played in the session, and the DJ's next pick is one of
  # those. Without splicing it back in, "the DJ played the one this engine ranked 47th" is
  # unsayable: the pick is never in the ranking to be found.
  cands <- list(
    list(artist = "Pool", title = "P", tags = "dreampop", novel = TRUE),
    list(artist = "Pool2", title = "Q", tags = "shoegaze", novel = TRUE)
  )
  actual <- list(artist = "DJ", title = "Played", tags = c("hiphop", "rap"), novel = FALSE)
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)

  expect_equal(nrow(r), 3)
  expect_equal(sum(r$is_actual), 1)
  # It is scored on its own tags, so a poor match lands low - which is the pitch's point.
  expect_equal(r$artist[r$is_actual], "DJ")
  expect_true(r$rank[r$is_actual] > 1)
})

test_that("an actual pick already in the pool is flagged once, never duplicated", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(
    list(artist = "Pool", title = "P", key = c("pool", "p"), tags = "dreampop", novel = TRUE)
  )
  actual <- list(artist = "Pool", title = "P", key = c("pool", "p"), tags = "dreampop")
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands, actual = actual)
  expect_equal(nrow(r), 1)
  expect_equal(sum(r$is_actual), 1)
})

test_that("an untaggable actual pick flags nothing rather than entering the ranking unscored", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  cands <- list(list(artist = "Pool", title = "P", tags = "dreampop", novel = TRUE))
  r <- rank_candidates(sp, tag_vector(sp, "dreampop"), cands,
                       actual = list(artist = "DJ", title = "Played"))
  expect_equal(nrow(r), 1)
  expect_equal(sum(r$is_actual), 0)
})

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

# Artist-tier tags are identical for every track by that artist, so every such track scores
# identically and the sort keeps the block together. Measured on a real pool: 1144 of 1406
# candidates shared a score with at least one other - exactly the artist-tier count - and the
# top 20 held 6 distinct artists. The novelty term does not help, because five tracks by one
# artist are equally novel and it shifts the whole block by the same amount.
#
# The fix belongs here rather than in rank_candidates. The ranking must stay complete: "the
# DJ played something this engine ranked 349th" is counted over every candidate, and thinning
# the pool would change that number. This only chooses what to show.

.row <- function(rank, artist, title, score) {
  data.frame(rank = rank, artist = artist, title = title, score = score,
             novel = TRUE, is_actual = FALSE, stringsAsFactors = FALSE)
}

.ranked <- function() {
  do.call(rbind, list(
    .row(1, "Sky Ferreira", "You're Not the One", 0.7214),
    .row(2, "Sky Ferreira", "I Blame Myself", 0.7214),
    .row(3, "Sky Ferreira", "Boys", 0.7214),
    .row(4, "Phantogram", "Black Out Days", 0.7195),
    .row(5, "Bebe Rexha", "I Got You", 0.7182),
    .row(6, "Bebe Rexha", "Meant to Be", 0.7182),
    .row(7, "Chairlift", "Bruises", 0.7081),
    .row(8, "Chairlift", "Sidewalk Safari", 0.7081),
    .row(9, "Grimes", "Oblivion", 0.6902)))
}

test_that("the shown rows hold one track per artist", {
  shown <- top_by_artist(.ranked(), n = 5)
  expect_equal(shown$artist,
               c("Sky Ferreira", "Phantogram", "Bebe Rexha", "Chairlift", "Grimes"))
})

test_that("the highest-scoring track is the one kept for each artist", {
  shown <- top_by_artist(.ranked(), n = 5)
  expect_equal(shown$title[1], "You're Not the One")
  expect_equal(shown$title[3], "I Got You")
})

test_that("true ranks survive, so the elision is visible rather than hidden", {
  # Renumbering 1..5 would erase the fact that ranks 2, 3, 6 and 8 were skipped, which is
  # precisely the tie structure worth showing.
  expect_equal(top_by_artist(.ranked(), n = 5)$rank, c(1, 4, 5, 7, 9))
})

test_that("fewer artists than slots returns what exists rather than padding", {
  few <- .ranked()[1:3, ]
  expect_equal(nrow(top_by_artist(few, n = 5)), 1)
})

test_that("an empty ranking yields an empty selection", {
  expect_equal(nrow(top_by_artist(.ranked()[0, ], n = 5)), 0)
})

test_that("per_artist is tunable for a pool that does not need thinning", {
  expect_equal(nrow(top_by_artist(.ranked(), n = 5, per_artist = 2)), 5)
  expect_equal(top_by_artist(.ranked(), n = 5, per_artist = 2)$rank, c(1, 2, 4, 5, 6))
})

test_that("the DJ's actual pick is never dropped by the per-artist cap", {
  # The pitch's moment must survive display thinning: if the pick is a second track by an
  # artist already shown, hiding it would silently delete the claim.
  r <- .ranked()
  r$is_actual[3] <- TRUE
  shown <- top_by_artist(r, n = 5)
  expect_true(any(shown$is_actual))
  expect_true("Boys" %in% shown$title)
})

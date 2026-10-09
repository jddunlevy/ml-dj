# `mldj next` writes data/live/queued.json after a successful queue write. The app reads it so
# that what is on screen is the track that was actually sent to Spotify, rather than a second
# opinion computed from a different pool. Absence is normal - nothing has been queued yet - so
# this reader returns NULL rather than erroring, which is the opposite of read_session.

test_that("a queued pick reads back with its numbers", {
  tmp <- tempfile(fileext = ".json")
  on.exit(unlink(tmp))
  writeLines('{
    "uri": "spotify:track:0000000000fixture01",
    "artist": "Night Cartography",
    "title": "Slow Transit - 2009 Remaster",
    "score": 0.6919,
    "rank": 7,
    "pool_size": 4154,
    "novel": false
  }', tmp)

  q <- read_queued(tmp)
  expect_equal(q$artist, "Night Cartography")
  expect_equal(q$rank, 7)
  expect_equal(q$pool_size, 4154)
  expect_false(q$novel)
})

test_that("no file means nothing has been queued, not an error", {
  expect_null(read_queued(tempfile(fileext = ".json")))
})

test_that("a truncated read returns NULL instead of taking the session down", {
  # `mldj next` rewrites the file in place, so a 1.5s poll can land mid-write.
  tmp <- tempfile(fileext = ".json")
  on.exit(unlink(tmp))
  writeLines('{"uri": "spotify:track:1", "arti', tmp)

  expect_null(read_queued(tmp))
})

test_that("a file with no uri is not a pick", {
  tmp <- tempfile(fileext = ".json")
  on.exit(unlink(tmp))
  writeLines('{"artist": "Nobody"}', tmp)

  expect_null(read_queued(tmp))
})

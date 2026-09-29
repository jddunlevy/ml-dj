SPACE_PATH <- file.path(PROJECT_ROOT, "space.json")

ev <- function(tags, outcome, earliness = 0) {
  list(tags = tags, outcome = outcome, earliness = earliness,
       artist = "A", title = "T", ts = 0)
}

test_that("a completed track moves the vector toward its tags", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_step(session_new(sp), ev("dreampop", "completed"))
  expect_gt(cosine_all(sp, s$v)[["dreampop"]], 0.9)
})

test_that("an early skip drives its tags negative", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_step(session_new(sp), ev("dance", "skipped", earliness = 1))
  expect_lt(cosine_all(sp, s$v)[["dance"]], -0.9)
})

test_that("earliness scales the size of the negative update", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  early <- session_step(session_new(sp), ev("dance", "skipped", earliness = 1.0))
  late  <- session_step(session_new(sp), ev("dance", "skipped", earliness = 0.2))
  expect_gt(sqrt(sum(early$v^2)), sqrt(sum(late$v^2)))
})

test_that("decay is applied once per event", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s1 <- session_step(session_new(sp, decay = 0.5), ev("dreampop", "completed"))
  s2 <- session_step(s1, ev("nosuchtag", "completed"))
  # the second event contributes nothing, so the vector is exactly the first, halved
  expect_equal(s2$v, s1$v * 0.5, tolerance = 1e-9)
})

test_that("an unknown outcome decays the vector but never updates it", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s1 <- session_step(session_new(sp, decay = 0.8), ev("dreampop", "completed"))
  s2 <- session_step(s1, ev("dance", "unknown", earliness = 1))
  expect_equal(s2$v, s1$v * 0.8, tolerance = 1e-9)
})

test_that("history records every event in order", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  s <- session_run(session_new(sp), list(ev("dreampop", "completed"), ev("dance", "skipped", 1)))
  expect_equal(length(s$history), 2)
  expect_equal(s$history[[2]]$outcome, "skipped")
})

test_that("a skipped event with no earliness raises rather than assuming full strength", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  no_earliness <- list(tags = "dance", outcome = "skipped", artist = "A", title = "T", ts = 0)
  expect_error(session_step(session_new(sp), no_earliness), "no earliness")
})

test_that("a skip after a completion pulls the vector back toward neutral", {
  skip_if_not(file.exists(SPACE_PATH), "space.json is gitignored")
  sp <- load_space(SPACE_PATH)
  up   <- session_step(session_new(sp), ev("dreampop", "completed"))
  down <- session_step(up, ev("dreampop", "skipped", earliness = 1))
  expect_lt(cosine_all(sp, down$v)[["dreampop"]], cosine_all(sp, up$v)[["dreampop"]])
})

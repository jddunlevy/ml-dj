test_that("the harness can see functions sourced from R/", {
  expect_true(exists("harness_ok"))
  expect_true(harness_ok())
})

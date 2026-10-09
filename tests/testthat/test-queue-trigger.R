# The button shells out to the Python CLI rather than reimplementing the write in R. These
# tests pin the command and the failure behaviour; nothing here launches a process.

test_that("the default command is the one the CLI actually registers", {
  expect_equal(queue_args(), c("-m", "mldj", "next"))
})

test_that("dry run and force are passed through as flags", {
  expect_equal(queue_args(dry_run = TRUE), c("-m", "mldj", "next", "--dry-run"))
  expect_equal(queue_args(force = TRUE), c("-m", "mldj", "next", "--force"))
  expect_equal(queue_args(dry_run = TRUE, force = TRUE),
               c("-m", "mldj", "next", "--dry-run", "--force"))
})

test_that("trigger_queue hands the python path and argv to the runner", {
  seen <- NULL
  trigger_queue(python = "py.exe", runner = function(cmd, args) {
    seen <<- list(cmd = cmd, args = args)
    "queued spotify:track:x"
  })
  expect_equal(seen$cmd, "py.exe")
  expect_equal(seen$args, c("-m", "mldj", "next"))
})

test_that("output comes back as one string", {
  out <- trigger_queue(runner = function(cmd, args) c("pick: +0.83 A - B", "queued spotify:track:x"))
  expect_equal(out, "pick: +0.83 A - B\nqueued spotify:track:x")
})

test_that("a runner that throws is reported, not raised", {
  # Mid-demo, a stack trace in the console is worse than a line on the screen saying why.
  out <- trigger_queue(python = "nope.exe",
                       runner = function(cmd, args) stop("file not found"))
  expect_match(out, "could not run nope.exe")
  expect_match(out, "file not found")
})

test_that("empty output does not render as nothing at all", {
  expect_equal(trigger_queue(runner = function(cmd, args) character(0)), "(no output)")
})

test_that("the summary is the last meaningful line, which is the outcome", {
  out <- paste("session: 9 events, last unknown X - Y",
               "pick: +0.8327  Del Water Gap - Ode to a Conversation",
               "      rank 1 of 4139 eligible (cooldown 5)",
               "queued spotify:track:abc", sep = "\n")
  expect_equal(queue_summary(out), "queued spotify:track:abc")
})

test_that("a decline is surfaced as the summary", {
  out <- paste("session: 6 events, last unknown X - Y",
               "declined: nothing clears min-score 0.15 on this vector.", sep = "\n")
  expect_match(queue_summary(out), "^declined:")
})

test_that("blank trailing lines do not become the summary", {
  expect_equal(queue_summary("queued spotify:track:abc\n\n   \n"), "queued spotify:track:abc")
})

# Source every module under R/ so tests see them. Shiny auto-loads R/ when the app runs;
# tests are not the app, so they load it themselves. testthat sets the working directory to
# tests/testthat, so the project root is two levels up.
PROJECT_ROOT <- normalizePath(file.path("..", ".."), mustWork = TRUE)

for (f in list.files(file.path(PROJECT_ROOT, "R"), pattern = "[.][Rr]$", full.names = TRUE)) {
  source(f)
}

# Regenerates fixtures/engine-trace.json. Run this ONLY when the engine's behaviour is meant
# to change, and say so in the commit message - a silent regeneration turns the parity test
# into a test that the engine equals itself.
for (f in list.files("R", pattern = "[.][Rr]$", full.names = TRUE)) source(f)

DECAY <- 0.85
W <- 1.0

sp <- load_space("space.json")
events <- read_session("fixtures/session-synthetic.json")$events

state <- session_new(sp, decay = DECAY, w = W)
steps <- lapply(events, function(e) {
  state <<- session_step(state, e)
  top <- head(sort(cosine_all(sp, state$v), decreasing = TRUE), 5)
  list(terms = names(top), cos = round(unname(top), 6))
})

jsonlite::write_json(
  list(source = "fixtures/session-synthetic.json", decay = DECAY, w = W, steps = steps),
  "fixtures/engine-trace.json", auto_unbox = TRUE, digits = 8, pretty = TRUE
)
cat("wrote fixtures/engine-trace.json:", length(steps), "steps\n")

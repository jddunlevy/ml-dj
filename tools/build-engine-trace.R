# Regenerates fixtures/engine-trace.json. Run this ONLY when the engine's behaviour is meant
# to change, or when space.json has been rebuilt, and say which in the commit message - a
# silent regeneration turns the parity test into a test that the engine equals itself.
#
# The trace records cosines, so it depends on the space as much as on the algorithm: a
# rebuilt vocabulary shifts every number slightly and the parity test fails while the engine
# is untouched. The fingerprint below exists so that failure names the right culprit.
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
  list(source = "fixtures/session-synthetic.json", decay = DECAY, w = W,
       space_terms = length(sp$terms),
       steps = steps),
  "fixtures/engine-trace.json", auto_unbox = TRUE, digits = 8, pretty = TRUE
)
cat("wrote fixtures/engine-trace.json:", length(steps), "steps\n")

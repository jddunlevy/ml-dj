# Render the current plots for the synthetic session, so they can be looked at.
for (f in list.files("R", pattern = "[.][Rr]$", full.names = TRUE)) source(f)
sp <- load_space("space.json")
s <- session_run(session_new(sp), read_session("fixtures/session-synthetic.json")$events)
dir.create("preview", showWarnings = FALSE)
ggplot2::ggsave("preview/reading.png", plot_reading(reading_data(sp, s$v)),
                width = 5.4, height = 3.3, dpi = 190)
cat("wrote preview/reading.png\n")

states <- Reduce(function(st, e) session_step(st, e), read_session("fixtures/session-synthetic.json")$events,
                  session_new(sp), accumulate = TRUE)[-1]
lay <- space_layout(sp)
ggplot2::ggsave("preview/constellation.png",
                plot_constellation(lay, trail_data(sp, lay, states)),
                width = 5.4, height = 4.6, dpi = 190)
cat("wrote preview/constellation.png\n")

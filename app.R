# The prototype. Shiny auto-sources R/ for an app in this directory, so the modules are
# already loaded by the time ui and server are evaluated.

SESSION_PATH <- Sys.getenv("MLDJ_SESSION", "fixtures/session-synthetic.json")
CANDS_PATH   <- Sys.getenv("MLDJ_CANDIDATES", "fixtures/candidates-synthetic.json")

# What `mldj next` actually wrote to Spotify's queue. Shown verbatim rather than recomputed:
# the queue is written from the library pool (the only pool carrying Spotify URIs) and
# "what i'd play next" ranks the Last.fm candidate pool, so they can disagree. Displaying the
# write is what stops the screen contradicting the queue.
QUEUED_PATH  <- Sys.getenv("MLDJ_QUEUED", "data/live/queued.json")

# Live mode re-reads the two JSON files as `mldj live` rewrites them. R still never polls
# Spotify and still never decides an outcome - `skips.derive_plays` owns that, and a second
# implementation in another language is a second thing to be wrong. Shiny only notices the
# file changed. Off by default, so the demo path stays a deterministic replay from disk.
LIVE <- nzchar(Sys.getenv("MLDJ_LIVE", ""))

space <- load_space(Sys.getenv("MLDJ_SPACE", "space.json"))
replay <- read_session(SESSION_PATH)
candidates <- read_candidates(CANDS_PATH)
layout_df <- space_layout(space)
N_EVENTS <- length(replay$events)

# Every prefix state, recomputed only when the events, decay or w change. The scrubber is
# then a lookup, not a fold over the whole session on every frame.
all_states <- function(events, decay, w) {
  Reduce(function(s, e) session_step(s, e), events,
         session_new(space, decay = decay, w = w), accumulate = TRUE)[-1]
}

ui <- shiny::fluidPage(
  shiny::tags$head(shiny::tags$link(rel = "stylesheet", href = "theme.css")),
  shiny::tags$script(shiny::HTML(
    "Shiny.addCustomMessageHandler('theme', function(t){
       document.documentElement.setAttribute('data-theme', t); });"
  )),
  shiny::div(
    class = "hd",
    shiny::div(shiny::span(class = "logo", "ml-dj"),
               shiny::span(style = "margin-left:14px;color:var(--muted);font-size:10px",
                           shiny::textOutput("ident", inline = TRUE))),
    shiny::div(
      style = "display:flex;gap:10px;align-items:center",
      shiny::numericInput("decay", "decay", 0.85, min = 0, max = 1, step = .05, width = "90px"),
      shiny::numericInput("w", "w", 1, min = 0, max = 5, step = .25, width = "70px"),
      shiny::numericInput("eps", "ε", 0, min = 0, max = 1, step = .05, width = "70px"),
      if (LIVE) shiny::checkboxInput("follow", "follow", value = TRUE, width = "80px"),
      shiny::selectInput("theme", NULL, choices = names(THEMES), width = "150px")
    )
  ),
  shiny::fluidRow(
    shiny::column(
      2,
      shiny::p(class = "lab", "now playing"),
      shiny::uiOutput("track"),
      shiny::p(class = "lab", style = "margin-top:18px", "session"),
      shiny::uiOutput("stats")
    ),
    shiny::column(6, shiny::p(class = "lab", "session vector"),
                  shiny::plotOutput("constellation", height = "100%")),
    shiny::column(
      4,
      shiny::p(class = "lab", "reading"),
      shiny::plotOutput("reading", height = "100%"),
      shiny::p(class = "lab", style = "margin-top:14px", "what i'd play next"),
      shiny::uiOutput("candidates"),
      shiny::p(class = "lab", style = "margin-top:14px", "queued on spotify"),
      shiny::uiOutput("queued")
    )
  ),
  shiny::div(
    class = "scrub",
    shiny::sliderInput("step", NULL, min = 1, max = N_EVENTS, value = 1, step = 1,
                       width = "100%", animate = shiny::animationOptions(interval = 1400)),
    shiny::div(style = "font-size:9px;color:var(--muted);margin-top:4px",
               "* novelty is an upper bound: the scrobble history has a 64-day hole,",
               "2026-07-24 to 2026-09-26, and a track first heard inside it reads as new.")
  )
)

server <- function(input, output, session) {
  th <- shiny::reactive(THEMES[[input$theme %||% "notebook"]])

  # `mldj live` rewrites these files in place, so a poll can land mid-write and read a
  # truncated document. One bad read must not take down a running session: keep the last
  # good value and try again on the next tick.
  replay_rv <- shiny::reactiveVal(replay)
  cands_rv <- shiny::reactiveVal(candidates)
  queued_rv <- shiny::reactiveVal(read_queued(QUEUED_PATH))

  # Polled outside LIVE too: the queue write is a live act whichever source the session came
  # from, and a demo that replays a session can still queue against the real account.
  queued_raw <- shiny::reactiveFileReader(
    1500, session, QUEUED_PATH,
    function(path) tryCatch(read_queued(path), error = function(e) NULL)
  )
  shiny::observe({
    q <- queued_raw()
    if (!is.null(q)) queued_rv(q)
  })

  if (LIVE) {
    tolerant <- function(reader) function(path) tryCatch(reader(path), error = function(e) NULL)
    raw_session <- shiny::reactiveFileReader(1500, session, SESSION_PATH,
                                             tolerant(read_session))
    raw_cands <- shiny::reactiveFileReader(1500, session, CANDS_PATH,
                                           tolerant(read_candidates))
    shiny::observe({
      v <- raw_session()
      if (!is.null(v) && length(v$events)) replay_rv(v)
    })
    shiny::observe({
      v <- raw_cands()
      if (!is.null(v) && length(v)) cands_rv(v)
    })
  }

  n_events <- shiny::reactive(length(replay_rv()$events))

  # The scrubber's range is data, not a constant, once the session can grow underneath it.
  # `follow` is what makes live mode feel live: it pins the view to the newest event, and
  # unticking it lets you scrub back through the session without the next poll yanking you
  # forward again.
  shiny::observeEvent(n_events(), {
    n <- n_events()
    current <- input$step %||% 1
    shiny::updateSliderInput(
      session, "step", max = max(n, 1),
      value = if (LIVE && isTRUE(input$follow)) n else min(current, max(n, 1))
    )
  })

  # Guards the window between the slider's max growing and the browser echoing the new
  # value back: for one tick input$step can still exceed the event count.
  step <- shiny::reactive(max(1, min(input$step %||% 1, n_events())))
  shiny::observeEvent(input$theme, {
    session$sendCustomMessage("theme", input$theme)
  })

  states <- shiny::reactive(all_states(replay_rv()$events, input$decay %||% 0.85,
                                       input$w %||% 1))
  state <- shiny::reactive(states()[[step()]])
  event <- shiny::reactive(replay_rv()$events[[step()]])
  nxt <- shiny::reactive({
    i <- step() + 1
    if (i > n_events()) NULL else replay_rv()$events[[i]]
  })

  # n_events(), not length(states) - states is a reactive, so length() on it is always 1
  # and the header would read "3 / 1" for the whole demo.
  output$ident <- shiny::renderText(
    paste(replay_rv()$session, "·", replay_rv()$label, "·", step(), "/", n_events(),
          if (LIVE) "· live" else "")
  )

  output$track <- shiny::renderUI({
    e <- event()
    shiny::tagList(
      shiny::p(class = "trk", e$title),
      shiny::p(class = "art", e$artist),
      shiny::div(style = "font-size:10px;color:var(--muted)",
                 paste(e$tags, collapse = " · "))
    )
  })

  output$stats <- shiny::renderUI({
    h <- state()$history
    outcomes <- vapply(h, function(e) e$outcome, character(1))
    row <- function(k, v) shiny::div(class = "kv", shiny::tags$b(k), shiny::span(v))
    shiny::tagList(
      row("tracks", length(h)),
      row("skipped", sum(outcomes == "skipped")),
      row("unknown", sum(outcomes == "unknown")),
      row("novel*", paste0(sum(vapply(h, function(e) isTRUE(e$novel), logical(1))),
                           " / ", length(h)))
    )
  })

  # res, not point sizes: the plot functions size type in points, so a panel that grows
  # with the window leaves the labels the same pixel height and they read as tiny on a
  # large monitor. Raising the device resolution scales every mark together.
  output$constellation <- shiny::renderPlot({
    plot_constellation(layout_df,
                       trail_data(space, layout_df, states()[seq_len(step())]), th())
  }, res = 104)

  output$reading <- shiny::renderPlot(plot_reading(reading_data(space, state()$v), th()),
                                      res = 104)

  output$candidates <- shiny::renderUI({
    r <- rank_candidates(space, state()$v, cands_rv(), actual = nxt(),
                         epsilon = input$eps %||% 0)
    top <- top_by_artist(r, n = 5)
    cand_row <- function(rank, title, artist, score, hit) {
      shiny::div(class = paste("cand-row", if (hit) "hit" else ""),
                 shiny::span(rank),
                 shiny::span(paste(title, "—", artist)),
                 shiny::span(sprintf("%.2f", score)))
    }
    rows <- lapply(seq_len(nrow(top)), function(i) {
      cand_row(top$rank[i], top$title[i], top$artist[i], top$score[i], top$is_actual[i])
    })
    # The pitch's moment: the DJ's pick ranked outside what the engine would have shown.
    # It is always rendered, however deep it sits, with the elision made explicit.
    #
    # "not already shown" rather than "rank > 5": top_by_artist thins same-artist ties out of
    # the display, so a pick can sit at rank 3 and still be absent from the rows above.
    hit <- r[r$is_actual, ]
    if (nrow(hit) == 1 && !(hit$rank %in% top$rank)) {
      rows <- c(rows, list(
        shiny::div(class = "gap", "· · ·"),
        cand_row(hit$rank, hit$title, hit$artist, hit$score, TRUE)))
    }
    shiny::tagList(rows)
  })

  # The write, reported rather than recomputed. Nothing here ranks anything: if this panel
  # disagreed with Spotify's own queue it would be the exact failure this project diagnoses -
  # a display claiming more than the system did.
  output$queued <- shiny::renderUI({
    q <- queued_rv()
    if (is.null(q)) {
      return(shiny::div(class = "cand-row",
                        shiny::span(""),
                        shiny::span(style = "color:var(--muted)", "nothing queued yet"),
                        shiny::span("")))
    }
    shiny::tagList(
      shiny::div(class = "cand-row hit",
                 shiny::span(q$rank),
                 shiny::span(paste(q$title, "—", q$artist)),
                 shiny::span(sprintf("%.2f", q$score))),
      shiny::div(style = "font-size:9px;color:var(--muted);margin-top:3px",
                 sprintf("written to spotify · rank %s of %s eligible%s",
                         q$rank, q$pool_size, if (isTRUE(q$novel)) " · novel" else ""))
    )
  })
}

shiny::shinyApp(ui, server)

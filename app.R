# The prototype. Shiny auto-sources R/ for an app in this directory, so the modules are
# already loaded by the time ui and server are evaluated.

SESSION_PATH <- Sys.getenv("MLDJ_SESSION", "fixtures/session-synthetic.json")
CANDS_PATH   <- Sys.getenv("MLDJ_CANDIDATES", "fixtures/candidates-synthetic.json")

space <- load_space(Sys.getenv("MLDJ_SPACE", "space.json"))
replay <- read_session(SESSION_PATH)
candidates <- read_candidates(CANDS_PATH)
layout_df <- space_layout(space)
N_EVENTS <- length(replay$events)

# Every prefix state, recomputed only when decay or w changes. The scrubber is then a lookup,
# not a fold over the whole session on every frame.
all_states <- function(decay, w) {
  Reduce(function(s, e) session_step(s, e), replay$events,
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
                  shiny::plotOutput("constellation", height = "380px")),
    shiny::column(
      4,
      shiny::p(class = "lab", "reading"),
      shiny::plotOutput("reading", height = "260px"),
      shiny::p(class = "lab", style = "margin-top:14px", "what i'd play next"),
      shiny::uiOutput("candidates")
    )
  ),
  shiny::div(
    style = "padding:10px 14px;border-top:1px solid var(--muted);background:var(--surface)",
    shiny::sliderInput("step", NULL, min = 1, max = N_EVENTS, value = 1, step = 1,
                       width = "100%", animate = shiny::animationOptions(interval = 1400)),
    shiny::div(style = "font-size:9px;color:var(--muted);margin-top:4px",
               "* novelty is an upper bound: the scrobble history has a 64-day hole,",
               "2026-07-24 to 2026-09-26, and a track first heard inside it reads as new.")
  )
)

server <- function(input, output, session) {
  th <- shiny::reactive(THEMES[[input$theme %||% "notebook"]])
  shiny::observeEvent(input$theme, {
    session$sendCustomMessage("theme", input$theme)
  })

  states <- shiny::reactive(all_states(input$decay %||% 0.85, input$w %||% 1))
  state <- shiny::reactive(states()[[input$step]])
  event <- shiny::reactive(replay$events[[input$step]])
  nxt <- shiny::reactive({
    i <- input$step + 1
    if (i > N_EVENTS) NULL else replay$events[[i]]
  })

  # N_EVENTS, not length(states) - states is a reactive, so length() on it is always 1 and
  # the header would read "3 / 1" for the whole demo.
  output$ident <- shiny::renderText(
    paste(replay$session, "·", replay$label, "·", input$step, "/", N_EVENTS)
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

  output$constellation <- shiny::renderPlot({
    plot_constellation(layout_df,
                       trail_data(space, layout_df, states()[seq_len(input$step)]), th())
  })

  output$reading <- shiny::renderPlot(plot_reading(reading_data(space, state()$v), th()))

  output$candidates <- shiny::renderUI({
    r <- rank_candidates(space, state()$v, candidates, actual = nxt(),
                         epsilon = input$eps %||% 0)
    top <- head(r, 5)
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
    hit <- r[r$is_actual, ]
    if (nrow(hit) == 1 && hit$rank > 5) {
      rows <- c(rows, list(
        shiny::div(class = "gap", "· · ·"),
        cand_row(hit$rank, hit$title, hit$artist, hit$score, TRUE)))
    }
    shiny::tagList(rows)
  })
}

shiny::shinyApp(ui, server)

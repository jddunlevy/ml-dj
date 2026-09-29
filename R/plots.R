#' The two plots. Data in, ggplot out - nothing here reads a file or a reactive.

THEMES <- list(
  notebook       = list(bg = "#f5f1e8", surface = "#ffffff", text = "#1a1a1a",
                        muted = "#666666", accent = "#000000"),
  avocado        = list(bg = "#d4e3c0", surface = "#e8efd9", text = "#2d3a1f",
                        muted = "#5a6b46", accent = "#3d5a2a"),
  sakura         = list(bg = "#fce4ec", surface = "#fdeef3", text = "#3a1f2e",
                        muted = "#7a4a60", accent = "#d9869f"),
  `blood-orange` = list(bg = "#ffb380", surface = "#ffd9b3", text = "#2a0f00",
                        muted = "#8a3a1a", accent = "#c91540"),
  `blue-bird`    = list(bg = "#bcd4e6", surface = "#d4e2ee", text = "#3a2820",
                        muted = "#7a5a48", accent = "#6e4030")
)

MONO <- "mono"

base_theme <- function(th) {
  ggplot2::theme_minimal(base_family = MONO, base_size = 11) +
    ggplot2::theme(
      plot.background  = ggplot2::element_rect(fill = th$bg, colour = NA),
      panel.background = ggplot2::element_rect(fill = th$surface, colour = th$muted,
                                               linewidth = .3),
      panel.grid.major = ggplot2::element_line(colour = scales::alpha(th$muted, .13),
                                               linewidth = .25),
      panel.grid.minor = ggplot2::element_blank(),
      plot.title    = ggplot2::element_text(colour = th$text, size = 10.5, face = "bold",
                                            hjust = 0, margin = ggplot2::margin(b = 2)),
      plot.subtitle = ggplot2::element_text(colour = th$muted, size = 8, hjust = 0,
                                            margin = ggplot2::margin(b = 9)),
      axis.text  = ggplot2::element_text(colour = th$muted, size = 7.5),
      axis.title = ggplot2::element_blank(),
      legend.position = "none",
      plot.margin = ggplot2::margin(11, 13, 9, 11)
    )
}

#' The strongest terms toward, and the strongest away. Display names, never term keys.
reading_data <- function(space, v, n_toward = 6, n_away = 3) {
  cos <- cosine_all(space, v)
  ordered <- sort(cos, decreasing = TRUE)
  toward <- head(ordered, n_toward)
  away <- rev(tail(ordered, n_away))

  data.frame(
    tag  = c(unname(space$display[names(toward)]), unname(space$display[names(away)])),
    cos  = c(unname(toward), unname(away)),
    sign = c(rep("toward", length(toward)), rep("away", length(away))),
    stringsAsFactors = FALSE
  )
}

#' Sign is carried by value, not hue: with one accent token there is no diverging scale
#' available, and this survives greyscale, all five themes, and a projector.
plot_reading <- function(reading_df, th = THEMES$notebook) {
  d <- reading_df
  d$tag <- factor(d$tag, levels = d$tag[order(d$cos)])
  d$fill <- ifelse(d$sign == "toward", th$accent, th$muted)
  lim <- max(abs(d$cos), 0.1) * 1.35

  ggplot2::ggplot(d, ggplot2::aes(cos, tag, fill = fill)) +
    ggplot2::geom_col(width = .62) +
    ggplot2::geom_vline(xintercept = 0, colour = th$muted, linewidth = .35) +
    ggplot2::geom_text(
      ggplot2::aes(label = sprintf("%+.2f", cos), hjust = ifelse(cos > 0, -0.22, 1.22)),
      family = MONO, size = 2.6, colour = th$text
    ) +
    ggplot2::scale_fill_identity() +
    ggplot2::scale_x_continuous(limits = c(-lim, lim)) +
    ggplot2::labs(title = "What the vector is pointing at",
                  subtitle = "cosine vs every tag · grey = pushed away by a skip") +
    base_theme(th) +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_blank(),
                   axis.text.y = ggplot2::element_text(colour = th$text, size = 8.5, hjust = 1))
}

#' The two plots. Data in, ggplot out - nothing here reads a file or a reactive.

# One theme, lifted token-for-token from the pitch mockup
# (homework/individual-pitch-prototype.html), so the live app and the submitted deck read as
# one artifact. The five light themes and the selector that chose between them are gone.
#
# That removal is what lets `skip` and `now` be fixed colours. The old note in theme.css was
# right that a hardcoded highlight could not survive both a cream ground and a blood-orange
# one - with a single dark ground that constraint does not exist, and a skip marker that must
# carry across a lit room is worth more than portability to themes nobody is going to use.
#
# `skip` is brighter than the mockup's own --red (#a35c5c), which is desaturated for body
# text on a page rather than for a 3.6pt glyph read from the back of a classroom.
# These must stay in step with :root in www/theme.css, which paints the page chrome.
THEME <- list(
  bg = "#0a0c0b", surface = "#141816", text = "#eef0ec",
  muted = "#949c96", accent = "#1ed760",
  skip = "#ff5c5c",  # the x markers - a skip is the one event the pitch is about
  now = "#22d3ee"    # the live position, cyan so it never reads as another skip or trail dot
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
  # Disjoint by construction: away is drawn from what's left after toward is removed, so a term
  # can never land in both groups even when n_toward + n_away >= length(ordered).
  remainder <- ordered[!(names(ordered) %in% names(toward))]
  away <- rev(tail(remainder, n_away))

  data.frame(
    tag  = c(unname(space$display[names(toward)]), unname(space$display[names(away)])),
    cos  = c(unname(toward), unname(away)),
    sign = c(rep("toward", length(toward)), rep("away", length(away))),
    stringsAsFactors = FALSE
  )
}

#' Sign is carried by value, not hue: with one accent token there is no diverging scale
#' available, and this survives greyscale and a projector. Deliberately NOT recoloured to the
#' new `skip` token - these bars are terms the vector points away from, which is the lasting
#' effect of past skips, not the skip events themselves. The x markers are the skips.
plot_reading <- function(reading_df, th = THEME) {
  d <- reading_df
  # factor() rejects duplicate levels ("duplicated levels are not allowed"), so two term keys
  # that share a display string would crash the plot. Order/position by a de-duplicated key, but
  # keep the original text for display via scale_y_discrete's labels map.
  key <- make.unique(as.character(d$tag))
  y_labels <- stats::setNames(as.character(d$tag), key)
  d$tag <- factor(key, levels = key[order(d$cos)])
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
    ggplot2::scale_y_discrete(labels = y_labels) +
    ggplot2::labs(title = "What the vector is pointing at",
                  subtitle = "cosine vs every tag · grey = pushed away by a skip") +
    base_theme(th) +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_blank(),
                   axis.text.y = ggplot2::element_text(colour = th$text, size = 8.5, hjust = 1))
}

#' A fixed 2-D basis for the term cloud, computed once. Centre, then take the first two
#' principal components. The basis is cached on the space object's meta so repeated calls in a
#' reactive cannot produce a backdrop that drifts between frames.
#'
#' Cache validity is decided by identical() against the exact `terms` and `vectors` that produced
#' the cached basis, not by a summary key. A key like "vocab size - rank" collides for any two
#' spaces of the same shape (Shiny reloads space.json without restarting the process, so a stale
#' basis served under a matching-shape key would be silently wrong). Digest is not installed, and
#' a hand-rolled hash risks the same collision class it's meant to fix; identical() on the actual
#' terms and vectors is slower but cannot be wrong, and this is called once per reactive tick, not
#' per term.
.space_basis_impl <- local({
  cache <- new.env(parent = emptyenv())
  list(
    get = function(space) {
      if (!is.null(cache$basis) &&
          identical(cache$terms, space$terms) &&
          identical(cache$vectors, space$vectors)) {
        return(cache$basis)
      }
      mu <- colMeans(space$vectors)
      centred <- sweep(space$vectors, 2, mu)
      sv <- svd(centred, nu = 0, nv = 2)
      basis <- list(mu = mu, P = sv$v, xy = centred %*% sv$v)
      cache$basis <- basis
      cache$terms <- space$terms
      cache$vectors <- space$vectors
      basis
    },
    #' Test-only: force the next space_basis() call to recompute the SVD from scratch, so a
    #' stability test can genuinely exercise sign-flip risk instead of hitting the cache.
    reset = function() {
      cache$basis <- NULL
      cache$terms <- NULL
      cache$vectors <- NULL
    }
  )
})
space_basis <- .space_basis_impl$get
space_basis_reset <- .space_basis_impl$reset

#' Terms in 2-D, with a greedy de-collision pass choosing which get labels. Character cells and
#' text labels both collide; picking labels by separation is cheaper and more predictable than
#' a repulsion solver, and it degrades gracefully when the space changes.
#'
#' The exclusion zone is an ellipse, not a circle, because what actually collides on screen is
#' rendered text and text is far wider than it is tall. A circle sized to stop vertical overlap
#' leaves "female vocalists" running straight through "beautiful"; sizing it to stop horizontal
#' overlap instead would throw away most of the plot's vertical structure. WIDE and FLAT are the
#' semi-axes as multiples of min_sep, so the rule is stricter across than it is up and down.
WIDE <- 2.4
FLAT <- 1.1

space_layout <- function(space, n_labels = 26, min_sep = 0.095) {
  b <- space_basis(space)
  xy <- b$xy
  span <- max(diff(range(xy[, 1])), diff(range(xy[, 2])))
  a <- WIDE * min_sep * span
  h <- FLAT * min_sep * span

  keep <- integer(0)
  for (i in seq_len(nrow(xy))) {
    if (length(keep) >= n_labels) break
    if (length(keep) > 0) {
      inside <- ((xy[i, 1] - xy[keep, 1]) / a)^2 + ((xy[i, 2] - xy[keep, 2]) / h)^2
      if (min(inside) < 1) next
    }
    keep <- c(keep, i)
  }

  data.frame(
    term = space$terms, tag = unname(space$display[space$terms]),
    x = xy[, 1], y = xy[, 2],
    label = seq_len(nrow(xy)) %in% keep,
    stringsAsFactors = FALSE
  )
}

#' Project each state's vector into the same basis as the terms.
trail_data <- function(space, layout_df, states) {
  b <- space_basis(space)
  pts <- t(vapply(states, function(s) as.vector((s$v - b$mu) %*% b$P), numeric(2)))
  data.frame(
    step = seq_along(states),
    outcome = vapply(states, function(s) {
      h <- s$history
      if (length(h) == 0) "completed" else h[[length(h)]]$outcome
    }, character(1)),
    x = pts[, 1], y = pts[, 2],
    stringsAsFactors = FALSE
  )
}

#' The constellation. Motion lives here; truth lives in the reading. The subtitle says so,
#' because a 150-to-2 projection discards 148 dimensions and the audience cannot see that.
plot_constellation <- function(layout_df, trail_df, th = THEME) {
  lab <- layout_df[layout_df$label, ]
  n <- nrow(trail_df)
  trail_df$alpha <- if (n > 1) seq(.3, 1, length.out = n) else 1
  cur <- trail_df[n, , drop = FALSE]
  skips <- trail_df[trail_df$outcome == "skipped", , drop = FALSE]

  ggplot2::ggplot() +
    # Only the labelled subset is drawn. 285 of the 367 terms fall within 10% of the span of
    # the median point, so plotting the full vocabulary made a grey blob at the origin, and
    # thinning n_labels never touched it - that only removes text from points already drawn.
    # An unlabelled point tells the audience "something is here" and nothing else, which is
    # not worth the legibility it costs. Slightly more solid now that each point has a name.
    ggplot2::geom_point(data = lab, ggplot2::aes(x, y), colour = th$muted,
                        size = 1.5, alpha = .75) +
    ggplot2::geom_text(data = lab, ggplot2::aes(x, y, label = tag), family = MONO,
                       size = 2.4, colour = th$muted, vjust = -1) +
    ggplot2::geom_path(data = trail_df, ggplot2::aes(x, y), colour = th$accent,
                       linewidth = .45, alpha = .4) +
    ggplot2::geom_point(data = trail_df, ggplot2::aes(x, y, alpha = alpha),
                        colour = th$accent, size = 1.9) +
    ggplot2::geom_point(data = skips, ggplot2::aes(x, y), shape = 4, colour = th$skip,
                        size = 3.6, stroke = 1.15) +
    ggplot2::geom_point(data = cur, ggplot2::aes(x, y), colour = th$accent, size = 4.2) +
    ggplot2::geom_point(data = cur, ggplot2::aes(x, y), colour = th$surface, size = 1.5) +
    ggplot2::geom_text(data = cur, ggplot2::aes(x, y, label = "now"), family = MONO,
                       size = 2.8, colour = th$now, hjust = -0.45, fontface = "bold") +
    ggplot2::scale_alpha_identity() +
    # Equal units on both axes, gridded every 2.5. Until now the panel stretched each axis to
    # fill its box independently, so a unit of y was drawn longer than a unit of x and the
    # distance the vector appeared to travel depended on which direction it went. For a plot
    # whose only job is showing how far the session moved, that is a wrong picture rather than
    # an ugly one. coord_fixed costs some empty margin when a session is wider than it is tall;
    # an honest aspect is worth more than a full box.
    #
    # Both axes get the same expansion now, because with equal scales an asymmetric one
    # reintroduces exactly the distortion coord_fixed is here to remove.
    ggplot2::scale_x_continuous(breaks = scales::breaks_width(2.5),
                                expand = ggplot2::expansion(mult = .12)) +
    ggplot2::scale_y_continuous(breaks = scales::breaks_width(2.5),
                                expand = ggplot2::expansion(mult = .12)) +
    ggplot2::coord_fixed(ratio = 1) +
    ggplot2::labs(title = "Session vector in tag space",
                  subtitle = paste("2-D of 150 · read the bars for what it means",
                                   "· × = skip")) +
    base_theme(th)
}

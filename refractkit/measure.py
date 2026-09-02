"""Rough text-height estimation, used to *autosize* overflowing slide content (shrink the
body font just enough that a column of text/bullets fits its available height) and, later,
to decide when a slide needs scroll steps.

The player does the real line-breaking; refract can't call into it, so this module models
it: proportional body text wraps at an average glyph advance of ``CHAR_W`` × font size, and
each visual line occupies ``LINE_H`` × font size. The constants deliberately lean *large*
(slightly over-estimating height) so autosize errs toward shrinking a touch more rather than
leaving content clipped."""

# Average glyph advance as a fraction of the font size, for a proportional body font, and the
# visual line height as a fraction of the font size. Calibrated against the player's actual
# layout (default sans) so ``content_height`` tracks reality — scroll offsets rely on it being
# accurate, not merely an upper bound. Autosize adds its own safety margin on top.
CHAR_W = 0.46
MONO_CHAR_W = 0.6           # monospace (code) glyphs are near-fixed and wider
LINE_H = 1.12               # visual line height as a fraction of the font size
AUTOSIZE_SAFETY = 1.06      # autosize-only headroom, so shrinking errs toward fitting


def _wrap_lines(s: str, font_size: float, width: float, char_w: float = CHAR_W) -> int:
    """Number of visual lines ``s`` wraps into at ``font_size`` within ``width`` (greedy
    word wrap). An empty string still occupies one line (a paragraph break)."""
    s = s.strip()
    if not s:
        return 1
    if width <= 0:
        return 1
    max_chars = max(1, int(width / (font_size * char_w)))
    lines, cur = 1, 0
    for word in s.split():
        wl = len(word)
        if cur == 0:
            cur = wl
        elif cur + 1 + wl <= max_chars:
            cur += 1 + wl
        else:
            lines += 1
            cur = wl
        # A single word longer than the line still spills onto extra lines.
        while cur > max_chars:
            lines += 1
            cur -= max_chars
    return lines


def _text_height(text: str, font_size: float, width: float, char_w: float = CHAR_W) -> float:
    """Estimated height of a multi-line string (each ``\\n`` line wraps independently)."""
    h = 0.0
    for line in text.split("\n"):
        h += _wrap_lines(line, font_size, width, char_w) * font_size * LINE_H
    return h


def block_height(block: dict, body_size: float, theme, width: float) -> float:
    """Estimated rendered height of one content block at ``body_size``. Non-text blocks
    (media, embeds) return 0 — they size themselves to the available area and don't scale
    with the body font, so they don't drive autosize."""
    kind = block.get("kind")
    if kind == "text":
        return _text_height(block.get("text", ""), body_size, width)
    if kind == "subtitle":
        size = theme.fonts.get("subtitle", body_size)
        return _text_height(block.get("text", ""), size, width)
    if kind == "bullets":
        h = 0.0
        for it in block.get("items", []):
            level = it.get("level", 0)
            # The marker column, its gap and the per-level indent all eat into the text width.
            indent = body_size * (0.9 + 0.32 + 1.3 * level)
            h += _wrap_lines(it.get("text", ""), body_size, width - indent) * body_size * LINE_H
        return h
    if kind == "code":
        # Match the code renderer exactly (n source lines at code_font_size * code_line_height,
        # inside a panel padded 24 top+bottom) so scroll offsets line up with the real content
        # height — the canvas renderer never wraps, so line count == source line count.
        size = float(getattr(theme, "code_font_size", body_size))
        lh = float(getattr(theme, "code_line_height", 1.35))
        lines = block.get("lines")
        if lines is None:
            lines = block.get("text", "").split("\n")
        n = max(1, len(lines))
        return n * size * lh + 48.0                  # + panel padding (24 + 24)
    if kind == "table":
        rows = block.get("rows", [])
        return max(1, len(rows)) * body_size * 1.9    # padded table rows
    if kind == "outline":
        n = len(block.get("items", []))
        size = _outline_size(theme, body_size)
        return n * size * 1.3 + max(0, n - 1) * size * 0.55   # rows + inter-item gaps
    return 0.0


def _outline_size(theme, body_size: float) -> float:
    """The outline's heading size scaled by the current autosize factor (``body_size`` vs the
    base content body), so measuring and rendering stay in step."""
    fonts = getattr(theme, "fonts", {}) or {}
    base = fonts.get("content_body", 40.0)
    heading = fonts.get("heading", 44.0)
    return heading * (body_size / base if base else 1.0)


def content_height(blocks: list, body_size: float, theme, width: float) -> float:
    """Estimated total height of a column of content blocks at ``body_size`` (calibrated to
    the player's real layout — no safety margin; autosize adds its own)."""
    return sum(block_height(b, body_size, theme, width) for b in blocks)


def fit_body_size(blocks: list, base_size: float, theme, width: float, avail_h: float,
                  min_scale: float = 0.5) -> float:
    """The largest body size ≤ ``base_size`` at which ``blocks`` fit within ``avail_h``
    (shrink-only autosize). Returns ``base_size`` unchanged when the content already fits or
    when there's nothing measurable; never shrinks past ``base_size × min_scale`` (content
    that overflows even then wants scroll, not a microscopic font)."""
    if avail_h <= 0:
        return base_size
    est = AUTOSIZE_SAFETY * content_height(blocks, base_size, theme, width)
    if est <= avail_h or est <= 0:
        return base_size
    scale = max(min_scale, avail_h / est)
    return round(base_size * scale, 2)

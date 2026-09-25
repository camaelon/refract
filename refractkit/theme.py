"""Theme: all colours and code styling, built from settings.toml with defaults.

Passed explicitly to the renderers (no module globals), so a deck's settings.toml
fully controls the look.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

# Default syntax-highlighting palette (token type -> #AARRGGBB), VS Code "dark"-ish.
DEFAULT_SYNTAX = {
    "keyword":    "#FFC586C0",
    "type":       "#FF4EC9B0",
    "string":     "#FFCE9178",
    "number":     "#FFB5CEA8",
    "comment":    "#FF6A9955",
    "annotation": "#FFDCDCAA",
    "key":        "#FF9CDCFE",   # JSON property name
    "literal":    "#FF569CD6",   # true / false / null
    "punct":      "#FFD4D4D4",
    "default":    "#FFD4D4D4",
}

# Default font sizes (px). Keyed <slide-type>_title / <slide-type>_body plus roles.
# Configurable via settings.toml [font]; the aliases below cover the common cases.
DEFAULT_FONTS = {
    "title_title":   120.0, "title_body":   48.0,
    "section_title":  96.0, "section_body": 40.0,
    "content_title":  72.0, "content_body": 40.0,
    "max_title":      44.0, "max_body":     40.0,   # near-fullscreen: small title
    "subtitle":       46.0,
    "table":          38.0,
}
# Friendly settings names -> internal font keys.
FONT_ALIASES = {
    "title": "title_title", "section": "section_title", "heading": "content_title",
    "body": "content_body", "content": "content_body", "subtitle": "subtitle",
    "table": "table", "code": "code", "max": "max_title",
}


# Built-in theme presets (selected via [theme] preset = "name"). Each is a set of
# Theme field overrides applied before the user's own [theme]/[code]/… settings.
PRESETS = {
    "dark": {},   # the built-in defaults
    "light": {
        "background": "#FFF7F8FA", "title_color": "#FF10141C", "body_color": "#FF2A2F3A",
        "accent": "#FF0B6BCB", "table_bg": "#14000000", "table_header_bg": "#22000000",
        "code_background": "#FFEDEFF2", "code_foreground": "#FF2A2F3A",
    },
    "midnight": {
        "background": "#FF090C18", "title_color": "#FFEAF0FF", "body_color": "#FFB9C4DD",
        "accent": "#FF7C93FF",
    },
    "warm": {
        "background": "#FF1B1410", "title_color": "#FFFDF6EE", "body_color": "#FFE8D9C6",
        "accent": "#FFE8955A", "code_background": "#FF241B14",
    },
    "mono": {
        "background": "#FF121212", "title_color": "#FFFFFFFF", "body_color": "#FFCCCCCC",
        "accent": "#FF9E9E9E", "table_bg": "#14FFFFFF", "table_header_bg": "#22FFFFFF",
    },
}


@dataclass
class Theme:
    background: str = "#FF0D1B2A"
    title_color: str = "#FFFFFFFF"
    title_colors: dict = field(default_factory=dict)
    title_color_override: str | None = None
    slide_types: dict = field(default_factory=dict)
    body_color: str = "#FFE6EEF6"
    accent: str = "#FF4FC3F7"           # subtitles, table headers, emphasis (can be
                                        # overridden per-slide by a speaker/author colour)
    primary: str = ""                   # the deck's brand colour (section numbers, outline);
                                        # stable across slides. Falls back to accent if unset.
    table_bg: str = "#1AFFFFFF"
    table_header_bg: str = "#22FFFFFF"
    table_corner_radius: float = 16.0   # rounded corners on the table panel (0 = square)
    code_background: str = "#FF1E1E1E"
    code_foreground: str = "#FFD4D4D4"
    code_font_size: float = 28.0
    code_corner_radius: float = 0.0
    # Code block renderer: "components" (a Text per token — precise metrics, but one
    # layout component per span) or "canvas" (positioned monospace drawTextRun ops on a
    # single canvas — collapses hundreds of components to ~2, far cheaper to paint for
    # large embedded source files). The canvas path assumes a monospace font and lays
    # tokens on a fixed character grid; the two ratios below tune that grid.
    code_renderer: str = "components"
    code_char_advance: float = 0.6      # glyph advance as a fraction of font size (mono)
    code_line_height: float = 1.35      # line pitch as a fraction of font size
    # Torn "zigzag" edge on a code panel that scrolls across several slides: the cut edge
    # (top when there's content above, bottom when there's more below) is drawn ripped.
    code_jagged_scroll: bool = True
    code_jagged_amp: float = 12.0       # zigzag tooth height (px)
    code_jagged_tooth: float = 32.0     # zigzag tooth width (px)
    # Font families (named system fonts) and weights. Empty family = default sans.
    title_font: str = ""            # headings (title/section/content/max)
    title_weight: float = 400.0
    body_font: str = ""             # body / bullets / subtitle / tables / chrome
    body_weight: float = 400.0
    code_font_family: str = "monospace"   # code blocks & spans
    title_gap: float = 44.0             # vertical gap between the title and content
    # Per-slide alignment overrides (applied via `align=` / `h_align=` / `valign=` / `v_align=`)
    h_align: str | None = None
    v_align: str | None = None
    # Per-slide padding deltas (left, top, right, bottom), added to the slide type's base
    # margin — set via `pad_left=` / `pad=` overrides to nudge one slide's content inward.
    pad_extra: tuple = (0.0, 0.0, 0.0, 0.0)
    # Slide chrome (page number / footer / progress bar). Rendered in the theme's own
    # colours (body / accent) and made translucent via chrome_alpha, so it reads as a
    # soft glassy overlay rather than a flat grey.
    chrome_page: bool = False
    chrome_footer: str = ""
    chrome_progress: bool = False
    chrome_hidden: bool = False          # per-slide `chrome=off`: no bottom chrome, content expands
    chrome_color: str = "#66FFFFFF"     # deprecated (kept for back-compat); use chrome_alpha
    chrome_alpha: float = 0.55          # translucency of the whole chrome overlay
    # Progress bar: mark section starts with a small circle above the bar, and colour the
    # bar/marks either by the current speaker (default) or per-section by that section's
    # expected speaker.
    chrome_progress_marks: bool = False
    chrome_progress_color: str = "current"   # "current" | "section"
    progress_mark_at: str = "speaker"        # "speaker" (at each speaker change) | "section"
    progress_mark_shape: str = "circle"      # circle | square | four | diamond
    progress_mark_filled: bool = True
    # Bullet-point marker shape/fill, plus optional overrides for sub-levels (level >= 1):
    # a different marker, font family, weight and colour. Empty/0 → inherit the top level.
    bullet_shape: str = "circle"             # circle | square | four | diamond | asanoha | quad | hline | vline
    bullet_filled: bool = True
    bullet_color: str = ""                   # the marker's own colour; "" → primary accent
    bullet_sub_shape: str = ""               # "" → same as bullet_shape
    bullet_sub_font: str = ""                # sub-level (>=1) text font; "" → same as body_font
    bullet_sub_weight: float = 0.0           # sub-level text weight; 0 → same as body_weight
    bullet_sub_color: str = ""               # sub-level text colour; "" → same as body_color
    # Deck-wide section spans for the progress bar, filled in by the deck builder:
    # [{"start": <0-based slide index>, "color": "#AARRGGBB"}], in order.
    chrome_sections: list = field(default_factory=list)
    # Deck-wide per-speaker colour runs for the progress bar: contiguous slides sharing a
    # speaker/author colour → [{"start", "end", "color"}]. Colours the bar by *who's speaking*
    # (which changes at include boundaries), independent of where the section marks fall.
    chrome_speaker_spans: list = field(default_factory=list)
    # Content reveal: how bullets/content blocks appear when a slide loads.
    content_reveal: str = "immediate"   # immediate (appear at once) | stagger (cascade in)
    reveal_delay: float = 0.0           # seconds before the first item animates
    reveal_stagger: float = 0.12        # seconds between successive items
    reveal_duration: float = 0.32       # per-item animation duration
    reveal_rise: float = 26.0           # px each item slides up as it fades in
    reveal_steps: bool = False          # also split content across multiple .rc files
    # Autosize: shrink a slide's body font just enough that overflowing text/bullets fit the
    # available height (shrink-only; never enlarges). On by default; disable per slide (e.g.
    # when using scroll steps) with `autosize = false`.
    autosize: bool = True
    autosize_min: float = 0.5           # never shrink the body font past this fraction
    # `:: same` shared-element transition (enter/exit for appearing/disappearing content).
    same_enter: str = "fade"        # fade | slide-left | slide-right | slide-up | slide-down
    same_exit: str = "fade"
    same_duration: float = 0.5
    same_delay: float = 0.05
    # Per-author colours: {name -> #AARRGGBB}. Author names appearing in body text
    # (e.g. the title slide byline) are tinted with their colour.
    authors: dict = field(default_factory=dict)
    # The author (``@name``) this slide is attributed to — shown in the chrome and
    # used as the slide's accent. Empty for unattributed slides.
    slide_author: str = ""
    fonts: dict = field(default_factory=lambda: dict(DEFAULT_FONTS))
    syntax: dict = field(default_factory=lambda: dict(DEFAULT_SYNTAX))

    def title_size(self, slide_type: str) -> float:
        return self.fonts.get(f"{slide_type}_title", self.fonts["content_title"])

    def body_size(self, slide_type: str) -> float:
        return self.fonts.get(f"{slide_type}_body", self.fonts["content_body"])
    # Animated background shaders (SkSL source) by slide type, plus a "default"
    # applied to any type without its own. Empty = solid `background` colour.
    shaders: dict = field(default_factory=dict)
    # Custom background inclusions (.json / .rc / image) by slide type + "default".
    bg_docs: dict = field(default_factory=dict)
    bg_doc_override: str | None = None
    # Overlay shader drawn on top of the slide *only during a transition*, driven by an
    # ``iProgress`` uniform (0→1 across the transition). Empty = none.
    transition_shader: str = ""
    # Shader drawn behind the *title element* of a content slide (on top of the slide
    # background), so the heading gets its own animated backdrop. Empty = none.
    title_shader: str = ""
    # RemoteCompose doc (.json / .rc / image) drawn behind the title element.
    title_background_doc: str = ""
    # Per-heading-level (1..6) styling and background inclusions ([heading.1], [heading.2], etc.).
    headings: dict = field(default_factory=dict)
    # Section slides auto-numbering (1. Section Title). False drops the leading number.
    section_numbered: bool = True
    # Image corner radius in px (0 = square). Rounds embedded images.
    image_corner_radius: float = 0.0
    # Embedded prebuilt `.rc` documents: how the nested doc is scaled into its box.
    embed_fit: str = "fit"          # fit (aspect, centred) | fill (cover) | native (1:1)
    # Graph (graphviz) rendering colours.
    graph_node_fill: str = "#FF1B2A3D"
    graph_node_stroke: str = "#FF4FC3F7"
    graph_node_text: str = "#FFE6EEF6"
    graph_edge: str = "#FF89A7C2"
    graph_glow: bool = True          # neon light-bleed around node borders
    graph_glow_radius: float = 9.0   # gaussian blur radius of the glow
    graph_glow_strength: float = 1.0  # scales the glow blur radius

    def syntax_color(self, token_type: str) -> str:
        return self.syntax.get(token_type, self.code_foreground)

    def shader_for(self, slide_type: str) -> str | None:
        return self.shaders.get(slide_type) or self.shaders.get("default")

    def bg_doc_for(self, slide_type: str) -> str | None:
        if self.bg_doc_override is not None:
            return self.bg_doc_override or None
        return self.bg_docs.get(slide_type) or self.bg_docs.get("default")

    def title_color_for(self, slide_type: str = "content") -> str:
        if self.title_color_override is not None:
            return self.title_color_override
        return self.title_colors.get(slide_type, self.title_color)

    def slide_type_spec(self, stype: str, default_spec: dict) -> dict:
        spec = dict(default_spec)
        override = self.slide_types.get(stype)
        if override:
            if "h_align" in override:
                spec["h_align"] = str(override["h_align"])
            if "v_align" in override:
                spec["v_align"] = str(override["v_align"])
            if "align" in override:
                spec["h_align"] = str(override["align"])
            if "padding" in override:
                spec["padding"] = override["padding"]
            elif "pad" in override:
                spec["padding"] = override["pad"]
        return spec

    def heading_config(self, level: int, slide_type: str = "content",
                       default_size: float | None = None) -> dict:
        """Resolved configuration for heading/section level (1..6)."""
        if default_size is not None:
            base_size = float(default_size)
        elif level == 1:
            base_size = self.title_size(slide_type)
        elif level == 2:
            base_size = float(self.fonts.get("heading", 44.0))
        elif level == 3:
            base_size = round(float(self.fonts.get("content_body", 40.0)) * 0.88, 1)
        else:
            base_size = round(float(self.fonts.get("content_body", 40.0)) * 0.65, 1)

        cfg = dict(self.headings.get(level, {}))
        shader = cfg.get("shader") or (self.title_shader if level == 1 else "")
        bg_doc = cfg.get("background_doc") or (self.title_background_doc if level == 1 else "")
        has_bg = bool(shader or bg_doc or cfg.get("bg_color") or cfg.get("band_height"))
        fallback_color = self.title_color_for(slide_type) if level == 1 else self.title_color
        return {
            "font_size": float(cfg.get("font_size", base_size)),
            "color": str(cfg.get("color", fallback_color)),
            "weight": float(cfg.get("weight", self.title_weight if level == 1 else max(self.title_weight, 600.0))),
            "family": str(cfg.get("family", self.title_font)),
            "shader": shader,
            "background_doc": bg_doc,
            "bg_color": cfg.get("bg_color"),
            "corner_radius": float(cfg.get("corner_radius", 0.0)),
            "pad_left": float(cfg.get("pad_left", 0.0)),
            "pad_top": float(cfg.get("pad_top", 0.0)),
            "pad_right": float(cfg.get("pad_right", 0.0)),
            "pad_bottom": float(cfg.get("pad_bottom", 14.0 if (bg_doc and level >= 2) else 0.0)),
            "gap": float(cfg.get("gap", self.title_gap if level == 1 else round(base_size * 0.35, 1))),
            # Line pitch as a fraction of the font size for a multi-line heading. 0 = let the
            # text component size itself, which is what every deck that does not say otherwise
            # wants; a converted deck sets it to match the source's line spacing.
            "line_height": float(cfg.get("line_height", 0.0)),
            "band_height": float(cfg["band_height"]) if cfg.get("band_height") is not None else None,
            "fill_width": bool(cfg.get("fill_width", True)),
            "has_bg": has_bg,
        }


def _resolve_asset_path(val, deck_dir: str, fallback_dirs=()) -> str | None:
    """Resolve a relative asset path (in deck_dir, deck_dir/includes, or deck_dir/theme/include) to an
    absolute path. ``fallback_dirs`` (the root deck, for a sub-deck slide) are searched the same way
    when the deck's own folders have no such file."""
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s or s.lower() in ("none", "off", "false"):
        return ""
    candidates = []
    for base in [deck_dir, *[d for d in fallback_dirs if d and os.path.abspath(d) != os.path.abspath(deck_dir)]]:
        candidates += [
            os.path.join(base, s),
            os.path.join(base, "includes", s),
            os.path.join(base, "theme", "include", s),
            os.path.join(base, "theme", "includes", s),
            os.path.join(base, "themes", "include", s),
            os.path.join(base, "themes", "includes", s),
        ]
    candidates.append(s)
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return os.path.abspath(os.path.join(deck_dir, s))


def _shader_source(cfg: dict, deck_dir: str) -> str | None:
    """Resolve a shader config table to SkSL source (inline ``source`` or ``file``)."""
    if not isinstance(cfg, dict) or cfg.get("enabled") is False:
        return None
    if cfg.get("source"):
        return cfg["source"]
    if cfg.get("file"):
        path = os.path.join(deck_dir, cfg["file"])
        try:
            with open(path) as f:
                return f.read()
        except OSError as e:
            print(f"warning: could not read shader {path}: {e}", file=sys.stderr)
    return None


def build_theme(settings: dict, deck_dir: str = ".") -> Theme:
    """Build a Theme from a parsed settings.toml dict.

    [theme]   background / title_color / body_color
    [code]    background / foreground / font_size, and [code.syntax] token colours
    [shader]  default background shader (inline ``source`` or ``file``); optional
              per-type subtables [shader.title] / [shader.section] / [shader.content]
    """
    t = Theme()
    th = settings.get("theme", {})
    # Apply a named preset first (its fields become the new defaults), then user overrides.
    preset = PRESETS.get(str(th.get("preset", "")).lower())
    if preset:
        for k, v in preset.items():
            setattr(t, k, v)
    t.background = th.get("background", t.background)
    t.title_color = th.get("title_color", t.title_color)
    for stype in ("title", "section", "content", "split", "max"):
        sub = th.get(stype, {})
        if isinstance(sub, dict) and ("title_color" in sub or "color" in sub):
            t.title_colors[stype] = str(sub.get("title_color") or sub.get("color"))
    t.body_color = th.get("body_color", t.body_color)
    t.accent = th.get("accent", t.accent)
    # Deck brand colour: explicit [theme] primary wins, else fall back to the accent so
    # existing decks keep working. Unlike accent, it is never overridden per slide.
    t.primary = th.get("primary", t.accent)
    t.table_bg = th.get("table_bg", t.table_bg)
    t.table_header_bg = th.get("table_header_bg", t.table_header_bg)
    if "table_corner_radius" in th:
        t.table_corner_radius = float(th["table_corner_radius"])

    code = settings.get("code", {})
    t.code_background = code.get("background", th.get("code_background", t.code_background))
    t.code_foreground = code.get("foreground", th.get("code_foreground", t.code_foreground))
    if "font_size" in code:
        t.code_font_size = float(code["font_size"])
    if "corner_radius" in code:
        t.code_corner_radius = float(code["corner_radius"])
    if "renderer" in code:
        t.code_renderer = str(code["renderer"]).lower()
    if "char_advance" in code:
        t.code_char_advance = float(code["char_advance"])
    if "line_height" in code:
        t.code_line_height = float(code["line_height"])
    if "jagged" in code:
        t.code_jagged_scroll = bool(code["jagged"])
    if "jagged_amp" in code:
        t.code_jagged_amp = float(code["jagged_amp"])
    if "jagged_tooth" in code:
        t.code_jagged_tooth = float(code["jagged_tooth"])
    for token_type, color in (code.get("syntax", {}) or {}).items():
        t.syntax[token_type] = color

    # [font]: friendly aliases (body/content, title, section, heading, subtitle,
    # table, code) plus any direct internal key (e.g. content_body, title_title).
    font = settings.get("font", {})
    # Family + weight keys are handled separately from the size keys.
    _font_meta = {"title_family", "title_weight", "body_family", "body_weight",
                  "code_family"}
    for key, val in font.items():
        if key in _font_meta:
            continue
        target = FONT_ALIASES.get(key, key)
        if target == "code":
            t.code_font_size = float(val)
        elif target in t.fonts:
            t.fonts[target] = float(val)
    t.title_font = str(font.get("title_family", t.title_font))
    t.title_weight = float(font.get("title_weight", t.title_weight))
    t.body_font = str(font.get("body_family", t.body_font))
    t.body_weight = float(font.get("body_weight", t.body_weight))
    t.code_font_family = str(font.get("code_family", t.code_font_family))

    layout = {**settings.get("slide", {}), **settings.get("layout", {})}
    if "title_gap" in layout:
        t.title_gap = float(layout["title_gap"])
    if "autosize" in layout:
        t.autosize = bool(layout["autosize"])
    if "autosize_min" in layout:
        t.autosize_min = float(layout["autosize_min"])
    for stype in ("title", "section", "content", "split", "max"):
        st_cfg = settings.get("layout", {}).get(stype) or settings.get("slide", {}).get(stype)
        if isinstance(st_cfg, dict):
            t.slide_types[stype] = dict(st_cfg)

    chrome = settings.get("chrome", {})
    t.chrome_page = bool(chrome.get("page", t.chrome_page))
    t.chrome_footer = str(chrome.get("footer", t.chrome_footer))
    t.chrome_progress = bool(chrome.get("progress", t.chrome_progress))
    t.chrome_color = chrome.get("color", t.chrome_color)
    t.chrome_alpha = float(chrome.get("alpha", t.chrome_alpha))
    t.chrome_progress_marks = bool(chrome.get("section_marks", t.chrome_progress_marks))
    t.progress_mark_at = str(chrome.get("mark_at", t.progress_mark_at)).lower()
    t.chrome_progress_color = str(chrome.get("progress_color", t.chrome_progress_color)).lower()
    t.progress_mark_shape = str(chrome.get("mark_shape", t.progress_mark_shape)).lower()
    t.progress_mark_filled = bool(chrome.get("mark_filled", t.progress_mark_filled))

    bullet = settings.get("bullet", {})
    t.bullet_shape = str(bullet.get("shape", t.bullet_shape)).lower()
    t.bullet_filled = bool(bullet.get("filled", t.bullet_filled))
    t.bullet_color = str(bullet.get("color", t.bullet_color))
    t.bullet_sub_shape = str(bullet.get("sub_shape", t.bullet_sub_shape)).lower()
    t.bullet_sub_font = str(bullet.get("sub_font", t.bullet_sub_font))
    t.bullet_sub_weight = float(bullet.get("sub_weight", t.bullet_sub_weight) or 0.0)
    t.bullet_sub_color = str(bullet.get("sub_color", t.bullet_sub_color))

    for name, color in (settings.get("authors", {}) or {}).items():
        t.authors[name] = color

    same = settings.get("same", {})
    t.same_enter = same.get("enter", t.same_enter)
    t.same_exit = same.get("exit", t.same_exit)
    t.same_duration = float(same.get("duration", t.same_duration))
    t.same_delay = float(same.get("delay", t.same_delay))

    reveal = settings.get("reveal", {})
    t.content_reveal = str(reveal.get("mode", t.content_reveal)).lower()
    t.reveal_delay = float(reveal.get("delay", t.reveal_delay))
    t.reveal_stagger = float(reveal.get("stagger", t.reveal_stagger))
    t.reveal_duration = float(reveal.get("duration", t.reveal_duration))
    t.reveal_rise = float(reveal.get("rise", t.reveal_rise))
    t.reveal_steps = bool(reveal.get("steps", t.reveal_steps))

    image = settings.get("image", {})
    if "corner_radius" in image:
        t.image_corner_radius = float(image["corner_radius"])
    elif image.get("rounded"):
        t.image_corner_radius = 28.0

    t.embed_fit = str(settings.get("embed", {}).get("fit", t.embed_fit)).lower()

    graph = settings.get("graph", {})
    t.graph_node_fill = graph.get("node_fill", t.graph_node_fill)
    t.graph_node_stroke = graph.get("node_stroke", t.graph_node_stroke)
    t.graph_node_text = graph.get("node_text", t.graph_node_text)
    t.graph_edge = graph.get("edge", t.graph_edge)
    t.graph_glow = bool(graph.get("glow", t.graph_glow))
    t.graph_glow_radius = float(graph.get("glow_radius", t.graph_glow_radius))
    t.graph_glow_strength = float(graph.get("glow_strength", t.graph_glow_strength))

    shader = settings.get("shader", {})
    default_src = _shader_source(shader, deck_dir)
    if default_src:
        t.shaders["default"] = default_src
    for stype in ("title", "section", "content"):
        src = _shader_source(shader.get(stype, {}), deck_dir)
        if src:
            t.shaders[stype] = src
    trans_src = _shader_source(shader.get("transition", {}), deck_dir)
    if trans_src:
        t.transition_shader = trans_src

    # Custom slide background inclusions: [background] default/title/section/content/split/max
    bg_cfg = settings.get("background", {})
    if isinstance(bg_cfg, dict):
        for k, val in bg_cfg.items():
            p = _resolve_asset_path(val, deck_dir)
            if p:
                t.bg_docs[k] = p
    elif isinstance(bg_cfg, str):
        p = _resolve_asset_path(bg_cfg, deck_dir)
        if p:
            t.bg_docs["default"] = p
    if isinstance(th.get("background_doc"), str):
        p = _resolve_asset_path(th["background_doc"], deck_dir)
        if p:
            t.bg_docs["default"] = p

    def _load_heading_level(lvl: int, cfg: dict):
        if not isinstance(cfg, dict):
            return
        cur = dict(t.headings.get(lvl, {}))
        for k in ("font_size", "weight", "pad_left", "pad_top", "pad_right",
                  "pad_bottom", "gap", "band_height", "corner_radius", "line_height"):
            if k in cfg and cfg[k] is not None:
                cur[k] = float(cfg[k])
        if "size" in cfg and cfg["size"] is not None:
            cur["font_size"] = float(cfg["size"])
        for k in ("color", "family", "bg_color"):
            if k in cfg and cfg[k] is not None:
                cur[k] = str(cfg[k])
        if "fill_width" in cfg:
            cur["fill_width"] = bool(cfg["fill_width"])
        ts = cfg.get("shader")
        sh_src = _shader_source({"file": ts} if isinstance(ts, str) else (ts or {}), deck_dir)
        if sh_src:
            cur["shader"] = sh_src
        bg_val = cfg.get("background") or cfg.get("doc") or cfg.get("include")
        if bg_val:
            p = _resolve_asset_path(bg_val, deck_dir)
            if p:
                cur["background_doc"] = p
        t.headings[lvl] = cur

    # Title-element backdrop: [title] shader = "file.sksl" or background = "file.json"
    title_cfg = settings.get("title", {})
    if isinstance(title_cfg, dict):
        if "color" in title_cfg:
            t.title_colors["title"] = str(title_cfg["color"])
        _load_heading_level(1, {k: v for k, v in title_cfg.items() if k != "color"})
        if t.headings.get(1, {}).get("shader"):
            t.title_shader = t.headings[1]["shader"]
        if t.headings.get(1, {}).get("background_doc"):
            t.title_background_doc = t.headings[1]["background_doc"]

    # Section / Heading levels: [heading.1], [heading.2], [section.2], etc.
    for tbl_name in ("heading", "section"):
        sec_tbl = settings.get(tbl_name, {})
        if isinstance(sec_tbl, dict):
            if tbl_name == "section":
                if "color" in sec_tbl and not any(k.isdigit() for k in sec_tbl):
                    t.title_colors["section"] = str(sec_tbl["color"])
                if "numbered" in sec_tbl:
                    t.section_numbered = bool(sec_tbl["numbered"])
                elif "number" in sec_tbl:
                    t.section_numbered = bool(sec_tbl["number"])
            for k, sub in sec_tbl.items():
                try:
                    lvl = int(k)
                    _load_heading_level(lvl, sub)
                except ValueError:
                    pass
    for lvl in range(1, 7):
        h_tbl = settings.get(f"h{lvl}")
        if isinstance(h_tbl, dict):
            _load_heading_level(lvl, h_tbl)

    return t

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
    body_color: str = "#FFE6EEF6"
    accent: str = "#FF4FC3F7"           # subtitles, table headers, emphasis
    table_bg: str = "#1AFFFFFF"
    table_header_bg: str = "#22FFFFFF"
    code_background: str = "#FF1E1E1E"
    code_foreground: str = "#FFD4D4D4"
    code_font_size: float = 28.0
    code_corner_radius: float = 0.0
    title_gap: float = 44.0             # vertical gap between the title and content
    # Slide chrome (page number / footer / progress bar). Rendered in the theme's own
    # colours (body / accent) and made translucent via chrome_alpha, so it reads as a
    # soft glassy overlay rather than a flat grey.
    chrome_page: bool = False
    chrome_footer: str = ""
    chrome_progress: bool = False
    chrome_color: str = "#66FFFFFF"     # deprecated (kept for back-compat); use chrome_alpha
    chrome_alpha: float = 0.55          # translucency of the whole chrome overlay
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
    # Overlay shader drawn on top of the slide *only during a transition*, driven by an
    # ``iProgress`` uniform (0→1 across the transition). Empty = none.
    transition_shader: str = ""
    # Shader drawn behind the *title element* of a content slide (on top of the slide
    # background), so the heading gets its own animated backdrop. Empty = none.
    title_shader: str = ""
    # Image corner radius in px (0 = square). Rounds embedded images.
    image_corner_radius: float = 0.0
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
    t.body_color = th.get("body_color", t.body_color)
    t.accent = th.get("accent", t.accent)
    t.table_bg = th.get("table_bg", t.table_bg)
    t.table_header_bg = th.get("table_header_bg", t.table_header_bg)

    code = settings.get("code", {})
    t.code_background = code.get("background", th.get("code_background", t.code_background))
    t.code_foreground = code.get("foreground", th.get("code_foreground", t.code_foreground))
    if "font_size" in code:
        t.code_font_size = float(code["font_size"])
    if "corner_radius" in code:
        t.code_corner_radius = float(code["corner_radius"])
    for token_type, color in (code.get("syntax", {}) or {}).items():
        t.syntax[token_type] = color

    # [font]: friendly aliases (body/content, title, section, heading, subtitle,
    # table, code) plus any direct internal key (e.g. content_body, title_title).
    font = settings.get("font", {})
    for key, val in font.items():
        target = FONT_ALIASES.get(key, key)
        if target == "code":
            t.code_font_size = float(val)
        elif target in t.fonts:
            t.fonts[target] = float(val)

    layout = {**settings.get("slide", {}), **settings.get("layout", {})}
    if "title_gap" in layout:
        t.title_gap = float(layout["title_gap"])

    chrome = settings.get("chrome", {})
    t.chrome_page = bool(chrome.get("page", t.chrome_page))
    t.chrome_footer = str(chrome.get("footer", t.chrome_footer))
    t.chrome_progress = bool(chrome.get("progress", t.chrome_progress))
    t.chrome_color = chrome.get("color", t.chrome_color)
    t.chrome_alpha = float(chrome.get("alpha", t.chrome_alpha))

    for name, color in (settings.get("authors", {}) or {}).items():
        t.authors[name] = color

    same = settings.get("same", {})
    t.same_enter = same.get("enter", t.same_enter)
    t.same_exit = same.get("exit", t.same_exit)
    t.same_duration = float(same.get("duration", t.same_duration))
    t.same_delay = float(same.get("delay", t.same_delay))

    image = settings.get("image", {})
    if "corner_radius" in image:
        t.image_corner_radius = float(image["corner_radius"])
    elif image.get("rounded"):
        t.image_corner_radius = 28.0

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

    # Title-element backdrop: [title] shader = "file.sksl" (or a [title.shader] table).
    title_cfg = settings.get("title", {})
    ts = title_cfg.get("shader")
    title_src = _shader_source({"file": ts} if isinstance(ts, str) else (ts or {}), deck_dir)
    if title_src:
        t.title_shader = title_src
    return t

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


@dataclass
class Theme:
    background: str = "#FF0D1B2A"
    title_color: str = "#FFFFFFFF"
    body_color: str = "#FFE6EEF6"
    code_background: str = "#FF1E1E1E"
    code_foreground: str = "#FFD4D4D4"
    code_font_size: float = 28.0
    syntax: dict = field(default_factory=lambda: dict(DEFAULT_SYNTAX))
    # Animated background shaders (SkSL source) by slide type, plus a "default"
    # applied to any type without its own. Empty = solid `background` colour.
    shaders: dict = field(default_factory=dict)

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
    t.background = th.get("background", t.background)
    t.title_color = th.get("title_color", t.title_color)
    t.body_color = th.get("body_color", t.body_color)

    code = settings.get("code", {})
    t.code_background = code.get("background", th.get("code_background", t.code_background))
    t.code_foreground = code.get("foreground", th.get("code_foreground", t.code_foreground))
    if "font_size" in code:
        t.code_font_size = float(code["font_size"])
    for token_type, color in (code.get("syntax", {}) or {}).items():
        t.syntax[token_type] = color

    shader = settings.get("shader", {})
    default_src = _shader_source(shader, deck_dir)
    if default_src:
        t.shaders["default"] = default_src
    for stype in ("title", "section", "content"):
        src = _shader_source(shader.get(stype, {}), deck_dir)
        if src:
            t.shaders[stype] = src
    return t

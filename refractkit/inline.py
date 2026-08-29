"""Inline text styling: ``**bold**``, ``*italic*`` / ``_italic_``, `` `code` ``.

A line with markup renders as a Row of styled Text spans (bold=fontWeight 700,
italic=fontStyle italic, code=monospace + accent). A line with no markup stays a
single plain Text so it keeps wrapping.
"""

from __future__ import annotations

import re

from .components import dbg

# Ordered so ** is matched before *; code spans win over emphasis inside them.
_TOKEN = re.compile(r"(\*\*.+?\*\*|__.+?__|\*.+?\*|_.+?_|`.+?`)")
_BOLD_W = 700.0


def has_markup(text: str) -> bool:
    return bool(_TOKEN.search(text))


def parse_spans(line: str) -> list[tuple[str, set]]:
    """Split a line into (text, styles) spans; styles ⊆ {'bold','italic','code'}."""
    spans: list[tuple[str, set]] = []
    pos = 0
    for m in _TOKEN.finditer(line):
        if m.start() > pos:
            spans.append((line[pos:m.start()], set()))
        tok = m.group(0)
        if tok.startswith("**") or tok.startswith("__"):
            spans.append((tok[2:-2], {"bold"}))
        elif tok.startswith("`"):
            spans.append((tok[1:-1], {"code"}))
        else:
            spans.append((tok[1:-1], {"italic"}))
        pos = m.end()
    if pos < len(line):
        spans.append((line[pos:], set()))
    return spans or [(line, set())]


def styled_line(line: str, size: float, color: str, theme, debug: bool) -> dict:
    """A Row of styled Text spans for one line of inline-marked-up text."""
    children = []
    for txt, styles in parse_spans(line):
        if not txt:
            continue
        comp = {"type": "text", "value": txt, "fontSize": size, "color": color}
        if "bold" in styles:
            comp["fontWeight"] = _BOLD_W
        if "italic" in styles:
            comp["fontStyle"] = "italic"
        if "code" in styles:
            comp["fontFamily"] = "monospace"
            comp["color"] = theme.accent
        if debug:
            comp["modifiers"] = dbg([], debug)
        children.append(comp)
    return {"type": "row", "children": children}

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


def has_author(text: str, authors: dict | None) -> bool:
    return bool(authors) and any(name in text for name in authors)


def _author_segments(line: str, authors: dict | None) -> list[tuple[str, str | None]]:
    """Split a line into (text, color) segments, tagging author-name runs with their
    colour and everything else with None. Longer names match first so 'John Hoford'
    wins over 'John', and matches are whole-word so 'Nico' doesn't tint 'Nicolas'."""
    if not authors:
        return [(line, None)]
    names = sorted(authors, key=len, reverse=True)
    segments: list[tuple[str, str | None]] = [(line, None)]
    for name in names:
        color = authors[name]
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        next_segments: list[tuple[str, str | None]] = []
        for text, seg_color in segments:
            if seg_color is not None:
                next_segments.append((text, seg_color))
                continue
            pos = 0
            for m in pat.finditer(text):
                if m.start() > pos:
                    next_segments.append((text[pos:m.start()], None))
                next_segments.append((m.group(0), color))
                pos = m.end()
            if pos < len(text):
                next_segments.append((text[pos:], None))
        segments = next_segments
    return segments


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


def styled_line(line: str, size: float, color: str, theme, debug: bool,
                align: str = "start") -> dict:
    """A wrapping Flow of styled word tokens for one line of inline-marked-up text.

    Each span is split into word / whitespace pieces (whitespace kept as its own
    token so spacing — and mid-word emphasis — is preserved exactly). A Flow wraps
    *between* children, so word-level tokens let a long styled line wrap to the
    available width instead of overflowing like a plain Row would. Author names are
    tinted with their per-author colour. ``align`` sets the Flow's horizontal
    alignment (``center`` for centred title/section slides).
    """
    authors = getattr(theme, "authors", None)
    children = []
    for seg_text, seg_color in _author_segments(line, authors):
        base_color = seg_color or color
        for txt, styles in parse_spans(seg_text):
            for piece in re.split(r"(\s+)", txt):
                if not piece:
                    continue
                comp = {"type": "text", "value": piece, "fontSize": size, "color": base_color}
                if "bold" in styles:
                    comp["fontWeight"] = _BOLD_W
                if "italic" in styles:
                    comp["fontStyle"] = "italic"
                if "code" in styles:
                    comp["fontFamily"] = "monospace"
                    comp["color"] = theme.accent
                # Align every token on its text baseline so mixed styles (and the
                # slightly different metrics of italic/monospace runs) share one baseline.
                comp["modifiers"] = dbg(["alignByBaseline"], debug)
                children.append(comp)
    return {"type": "flow", "horizontalAlignment": align,
            "modifiers": dbg(["fillMaxWidth"], debug), "children": children}

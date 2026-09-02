"""Syntax highlighting for fenced code blocks.

Architecture — adding a language is one function + a registry entry:

    def tokenize_foo(code): return _lines(_scan(code, _FOO_RULES))
    LANGUAGES["foo"] = tokenize_foo

A tokenizer returns a list of *lines*, each a list of ``(text, token_type)`` spans
covering every character (whitespace included) so a line reconstructs exactly.
``token_type`` keys into Theme.syntax for the colour. Rendering lays each line out
as a Row of monospace Text spans, stacked in a Column.
"""

from __future__ import annotations

import re

from .components import dbg, text, torn_fill_commands

# ── Generic regex scanner ────────────────────────────────────────────────────
def _scan(code: str, rules: list[tuple]) -> list[tuple[str, str]]:
    """Scan ``code`` with ordered (regex, token_type) rules into (text, type) tokens.

    At each position the first matching rule wins; unmatched characters become
    ``default`` tokens, so every character is covered."""
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(code)
    while i < n:
        for rx, ttype in rules:
            m = rx.match(code, i)
            if m and m.end() > i:
                tokens.append((m.group(0), ttype))
                i = m.end()
                break
        else:
            tokens.append((code[i], "default"))
            i += 1
    return tokens


def _lines(tokens: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Break tokens (which may contain newlines) into per-line span lists."""
    lines: list[list[tuple[str, str]]] = [[]]
    for txt, ttype in tokens:
        parts = txt.split("\n")
        for k, part in enumerate(parts):
            if k > 0:
                lines.append([])
            if part:
                lines[-1].append((part, ttype))
    return lines


# ── Kotlin ───────────────────────────────────────────────────────────────────
_KOTLIN_KEYWORDS = {
    "fun", "val", "var", "class", "object", "interface", "typealias", "if", "else",
    "for", "while", "do", "when", "is", "in", "return", "break", "continue", "import",
    "package", "private", "public", "protected", "internal", "override", "open",
    "abstract", "final", "companion", "data", "sealed", "enum", "const", "lateinit",
    "by", "get", "set", "suspend", "this", "super", "null", "true", "false", "as",
    "try", "catch", "finally", "throw", "init", "operator", "inline", "vararg", "out",
    "reified", "crossinline", "noinline", "annotation",
}
_KOTLIN_RULES = [
    (re.compile(r"//[^\n]*"), "comment"),
    (re.compile(r"/\*.*?\*/", re.S), "comment"),
    (re.compile(r'"""(?:.|\n)*?"""'), "string"),
    (re.compile(r'"(?:\\.|[^"\\\n])*"'), "string"),
    (re.compile(r"'(?:\\.|[^'\\\n])*'"), "string"),
    (re.compile(r"@\w+"), "annotation"),
    (re.compile(r"\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?[fFlLuU]*\b"), "number"),
    (re.compile(r"[A-Za-z_]\w*"), "_ident"),
    (re.compile(r"[{}()\[\].,:;=+\-*/%<>!&|?@]+"), "punct"),
]


def _resolve_idents(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out = []
    for txt, ttype in tokens:
        if ttype == "_ident":
            if txt in _KOTLIN_KEYWORDS:
                ttype = "keyword"
            elif txt[:1].isupper():
                ttype = "type"
            else:
                ttype = "default"
        out.append((txt, ttype))
    return out


def tokenize_kotlin(code: str) -> list[list[tuple[str, str]]]:
    return _lines(_resolve_idents(_scan(code, _KOTLIN_RULES)))


# ── JSON ─────────────────────────────────────────────────────────────────────
_JSON_RULES = [
    (re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)'), "key"),     # property name
    (re.compile(r'"(?:\\.|[^"\\])*"'), "string"),
    (re.compile(r"\b(?:true|false|null)\b"), "literal"),
    (re.compile(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?"), "number"),
    (re.compile(r"[{}\[\],:]"), "punct"),
]


def tokenize_json(code: str) -> list[list[tuple[str, str]]]:
    return _lines(_scan(code, _JSON_RULES))


# ── Registry ─────────────────────────────────────────────────────────────────
LANGUAGES = {
    "kotlin": tokenize_kotlin,
    "kt": tokenize_kotlin,
    "java": tokenize_kotlin,   # close enough token-wise for slides
    "json": tokenize_json,
}


def highlight(code: str, lang: str) -> list[list[tuple[str, str]]]:
    """Tokenize ``code`` for ``lang``; unknown languages render as plain text."""
    fn = LANGUAGES.get((lang or "").lower())
    if fn is None:
        return [[(line, "default")] if line else [] for line in code.split("\n")]
    return fn(code)


# ── Rendering ────────────────────────────────────────────────────────────────
def _panel_mods(theme, debug: bool, bg: bool = True) -> list:
    """Shared outer-panel modifiers: full width, (optional rounded clip + bg), padding.

    ``bg=False`` drops the background and clip — used for a scrolled code panel whose
    background is drawn separately as a fixed jagged-edged shape (see _jagged_bg_canvas),
    with the text scrolling transparently on top."""
    mods = ["fillMaxWidth"]
    if bg:
        if theme.code_corner_radius > 0:
            mods.append({"clip": float(theme.code_corner_radius)})   # rounds the panel
        mods.append({"background": theme.code_background})
    mods.append({"padding": 24.0})
    return dbg(mods, debug)


def _fit_code_size(block: dict, theme, avail_w, avail_h) -> float:
    """The code font size at which the block fits (avail_w, avail_h): shrink-only from
    ``code_font_size``. Code never wraps, so the longest source line drives the width fit and
    the line count the height fit; both account for the panel's 24px padding. Returns the base
    size unchanged when no area is given (e.g. a scrolled panel) or it already fits."""
    base = float(theme.code_font_size)
    if not avail_w and not avail_h:
        return base
    lines = highlight(block.get("text", ""), block.get("lang", ""))
    nlines = max(1, len(lines))
    maxlen = max((sum(len(t) for t, _ in ln) for ln in lines if ln), default=1) or 1
    pad = 48.0                                   # panel padding, both sides
    size = base
    if avail_w:
        adv = float(getattr(theme, "code_char_advance", 0.6))
        size = min(size, (float(avail_w) - pad) / (maxlen * adv))
    if avail_h:
        lh = float(getattr(theme, "code_line_height", 1.35))
        size = min(size, (float(avail_h) - pad) / (nlines * lh))
    return max(6.0, round(size, 2))


def render_code(block: dict, theme, debug: bool, panel_bg: bool = True,
                avail_w: float | None = None, avail_h: float | None = None) -> list[dict]:
    """Render a code block as a dark panel of syntax-highlighted monospace lines.

    Two renderers (see Theme.code_renderer): "components" lays each token as its own
    Text (precise, but one layout component per span — heavy for large files), "canvas"
    draws positioned monospace runs on a single canvas (~2 components total).
    ``panel_bg=False`` omits the panel background/clip (the scrolled jagged-edge case).
    ``avail_w``/``avail_h`` shrink the font so the block fits that area (no autosize when
    omitted, e.g. the scroll path renders full-size).

    A ``<base>-extract`` language (e.g. ``json-extract``) highlights as ``<base>`` but draws a
    torn zigzag top+bottom edge on the panel — a snippet cut from a larger document."""
    lang = block.get("lang", "") or ""
    jagged = lang.lower().endswith("-extract")
    base_lang = lang[: -len("-extract")] if jagged else lang
    size = _fit_code_size(block, theme, avail_w, avail_h)
    if getattr(theme, "code_renderer", "components") == "canvas":
        return render_code_canvas(block, theme, debug, panel_bg, size,
                                  lang=base_lang, jagged=jagged, avail_w=avail_w)
    fam = getattr(theme, "code_font_family", "monospace")
    lines = highlight(block.get("text", ""), base_lang)
    rows = []
    for line in lines:
        if not line:
            spans = [text(" ", size, theme.code_foreground, debug, family=fam)]
        else:
            spans = [text(t, size, theme.syntax_color(tt), debug, family=fam)
                     for t, tt in line]
        rows.append({"type": "row", "children": spans})
    return [{
        "type": "column",
        "modifiers": _panel_mods(theme, debug, panel_bg),
        "children": rows,
    }]


def _coalesce(line: list[tuple[str, str]]) -> list[tuple[int, str, str]]:
    """Merge adjacent same-colour spans into (start_column, text, token_type) runs so a
    long stretch of one colour is a single drawTextRun. Whitespace-only runs are dropped
    (nothing to draw) but still advance the column."""
    runs: list[tuple[int, str, str]] = []
    col = 0
    buf, buf_tt, buf_col = "", None, 0
    def flush():
        if buf and buf.strip():
            runs.append((buf_col, buf, buf_tt))
    for t, tt in line:
        t = t.replace("\t", "    ")   # expand tabs so the monospace grid stays aligned
        if tt != buf_tt:
            flush()
            buf, buf_tt, buf_col = "", tt, col
        buf += t
        col += len(t)
    flush()
    return runs


def render_code_canvas(block: dict, theme, debug: bool, panel_bg: bool = True,
                       size: float | None = None, lang: str | None = None,
                       jagged: bool = False, avail_w: float | None = None) -> list[dict]:
    """Code panel drawn as a single canvas of positioned monospace runs.

    Tokens sit on a fixed grid: x = column * (size*char_advance), baseline advances by
    size*line_height per line. One typeface/size paint op up front, then a colour op only
    when the colour changes. Collapses hundreds of Text components to one canvas node —
    trivial layout, cheap paint — at the cost of exact per-glyph metrics (fine for a
    monospace font). ``size`` overrides the font size (e.g. an autosized fit); ``lang``
    overrides the highlight language. ``jagged`` (needs ``avail_w``) draws the panel background
    and text on ONE canvas with a torn zigzag top+bottom edge — an "extract" snippet."""
    size = float(size if size is not None else theme.code_font_size)
    char_w = size * float(getattr(theme, "code_char_advance", 0.6))
    line_h = size * float(getattr(theme, "code_line_height", 1.35))
    ascent = size * 0.82                      # baseline offset of the first line
    lines = highlight(block.get("text", ""), lang if lang is not None else block.get("lang", ""))

    jagged = jagged and bool(avail_w)         # the torn shape needs a concrete panel width
    pad = 24.0
    ty = (pad if jagged else 0.0)             # jagged draws its own bg+padding on the canvas
    tx = (pad if jagged else 0.0)

    cmds: list[dict] = []
    if jagged:
        # Panel background + torn top/bottom edge, filled before the text on the same canvas.
        panel_h = round(max(1, len(lines)) * line_h + 2 * pad, 2)
        cmds += torn_fill_commands("czz", float(avail_w), panel_h, True, True,
                                   float(getattr(theme, "code_jagged_amp", 12.0)),
                                   float(getattr(theme, "code_jagged_tooth", 32.0)),
                                   theme.code_background, outward=False)
    cmds.append({"type": "paint", "ops": [
        {"style": "fill"}, {"fontType": "monospace"}, {"textSize": float(size)},
        {"color": theme.code_foreground}]})
    cur_color = theme.code_foreground
    for i, line in enumerate(lines):
        y = round(ty + ascent + i * line_h, 2)
        for col, txt, tt in _coalesce(line):
            color = theme.syntax_color(tt)
            if color != cur_color:
                cmds.append({"type": "paint", "ops": [{"color": color}]})
                cur_color = color
            # Explicit UTF-16 start/end: the player draws chars [start,end); the parser's
            # default end=-1 would draw nothing.
            n = len(txt.encode("utf-16-le")) // 2
            cmds.append({"type": "drawtextrun", "text": txt, "start": 0, "end": n,
                         "x": round(tx + col * char_w, 2), "y": y})

    if jagged:
        # The canvas is the whole panel (bg + padding baked in); the wrapper only sets width.
        canvas = {"type": "canvas",
                  "modifiers": dbg(["fillMaxWidth", {"height": panel_h}], debug),
                  "commands": cmds}
        return [{"type": "column", "modifiers": dbg(["fillMaxWidth"], debug),
                 "children": [canvas]}]

    canvas_h = round(max(1, len(lines)) * line_h, 2)
    canvas = {"type": "canvas",
              "modifiers": dbg(["fillMaxWidth", {"height": canvas_h}], debug),
              "commands": cmds}
    return [{
        "type": "column",
        "modifiers": _panel_mods(theme, debug, panel_bg),
        "children": [canvas],
    }]

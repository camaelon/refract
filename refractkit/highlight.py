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

from .components import dbg, text

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
    "json": tokenize_json,
}


def highlight(code: str, lang: str) -> list[list[tuple[str, str]]]:
    """Tokenize ``code`` for ``lang``; unknown languages render as plain text."""
    fn = LANGUAGES.get((lang or "").lower())
    if fn is None:
        return [[(line, "default")] if line else [] for line in code.split("\n")]
    return fn(code)


# ── Rendering ────────────────────────────────────────────────────────────────
def render_code(block: dict, theme, debug: bool) -> list[dict]:
    """Render a code block as a dark panel of syntax-highlighted monospace lines."""
    size = theme.code_font_size
    lines = highlight(block.get("text", ""), block.get("lang", ""))
    rows = []
    for line in lines:
        if not line:
            spans = [text(" ", size, theme.code_foreground, debug, mono=True)]
        else:
            spans = [text(t, size, theme.syntax_color(tt), debug, mono=True)
                     for t, tt in line]
        rows.append({"type": "row", "children": spans})
    return [{
        "type": "column",
        "modifiers": dbg(["fillMaxWidth", {"background": theme.code_background},
                          {"padding": 24.0}], debug),
        "children": rows,
    }]

"""Markdown parsing: slide text -> {meta, title, blocks}.

Grammar (deliberately small):
  ---            slide separator
  :: <type> [: <params>] [ratio]   slide metadata (first line of a slide)
  # Title        slide title (first heading)
  - item         bullet (indent two spaces per sub-level)
  ``` lang       fenced code block
  +++            pane separator
  <name>         include (image / .json / .rc / sub-deck)
  (anything else)  paragraph text
"""

from __future__ import annotations

import re

SLIDE_SEP = re.compile(r"(?m)^\s*---\s*$")
TITLE_RE = re.compile(r"^#\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)-\s+(.+)$")
INCLUDE_LINE = re.compile(r"^<([^>]+)>$")
RATIO_RE = re.compile(r"\[(\d+(?::\d+)+)\]")


def parse_meta(spec: str) -> dict:
    """Parse a ``::`` metadata line: ``<type> [: <params>] [ratio]``.

    A pane ratio like ``[2:3]`` or ``[2:2:4]`` may appear anywhere on the line (its
    inner ``:`` would otherwise confuse the type/params split, so it is pulled out
    first)."""
    ratio = None
    m = RATIO_RE.search(spec)
    if m:
        ratio = [int(x) for x in m.group(1).split(":")]
        spec = (spec[:m.start()] + spec[m.end():]).strip()
    kind, _, params = spec.strip().strip(":").partition(":")
    return {"type": kind.strip(), "params": params.strip(), "ratio": ratio}


def parse_slide(chunk: str) -> dict | None:
    """Parse one slide chunk into {meta, title, blocks}."""
    lines = chunk.strip("\n").split("\n")
    meta = None
    title = None
    blocks: list[dict] = []
    para: list[str] = []
    bullets: list[dict] = []

    def flush_para():
        if para:
            blocks.append({"kind": "text", "text": "\n".join(para)})
            para.clear()

    def flush_bullets():
        if bullets:
            blocks.append({"kind": "bullets", "items": list(bullets)})
            bullets.clear()

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # metadata: leading ``::`` line before any content
        if meta is None and title is None and not blocks and not para and not bullets \
                and stripped.startswith("::"):
            meta = parse_meta(stripped[2:])
            i += 1
            continue

        # fenced code block
        if stripped.startswith("```"):
            flush_para()
            flush_bullets()
            lang = stripped[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append({"kind": "code", "lang": lang, "text": "\n".join(code_lines)})
            continue

        if not stripped:
            flush_para()
            flush_bullets()
            i += 1
            continue

        m = TITLE_RE.match(stripped)
        if m and title is None and not blocks and not para and not bullets:
            title = m.group(1).strip()
            i += 1
            continue

        if stripped == "+++":
            flush_para()
            flush_bullets()
            blocks.append({"kind": "pane_break"})
            i += 1
            continue

        mi = INCLUDE_LINE.match(stripped)
        if mi:
            flush_para()
            flush_bullets()
            blocks.append({"kind": "include", "name": mi.group(1).strip()})
            i += 1
            continue

        mb = BULLET_RE.match(raw)
        if mb:
            flush_para()
            indent = len(mb.group(1).expandtabs(4))
            bullets.append({"level": indent // 2, "text": mb.group(2).strip()})
            i += 1
            continue

        flush_bullets()
        para.append(stripped)
        i += 1

    flush_para()
    flush_bullets()

    if meta is None and title is None and not blocks:
        return None
    return {"meta": meta, "title": title, "blocks": blocks}


def parse_markdown(text: str) -> list[dict]:
    slides = []
    for chunk in SLIDE_SEP.split(text):
        slide = parse_slide(chunk)
        if slide:
            slides.append(slide)
    return slides

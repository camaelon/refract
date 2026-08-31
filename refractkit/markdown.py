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

GRAPH_ENGINES = {"dot", "neato", "fdp", "sfdp", "twopi", "circo", "graphviz"}

SLIDE_SEP = re.compile(r"(?m)^\s*---\s*$")
TITLE_RE = re.compile(r"^#\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)-\s+(.+)$")
INCLUDE_LINE = re.compile(r"^<([^>]+)>$")
RATIO_RE = re.compile(r"\[(\d+(?::\d+)+)\]")
SUBTITLE_RE = re.compile(r"^\*(.+)\*$")
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_meta(spec: str) -> dict:
    """Parse a ``::`` metadata line: ``<type> [: <params>] [ratio] [key=value…] [flags]``.

    - A pane ratio like ``[2:3]`` may appear anywhere (its inner ``:`` would confuse
      the type/params split, so it is pulled out first).
    - ``key=value`` tokens become per-slide overrides (bg, accent, shader, …).
    - Bare word flags (e.g. ``fragment``) become boolean flags.
    - The remaining leading word after the type is the speaker/params.
    """
    ratio = None
    m = RATIO_RE.search(spec)
    if m:
        ratio = [int(x) for x in m.group(1).split(":")]
        spec = (spec[:m.start()] + spec[m.end():]).strip()

    # Pull out key=value overrides and ``@author`` attributions from anywhere.
    overrides = {}
    author = None
    kept = []
    for tok in spec.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            overrides[k.strip()] = v.strip()
        elif tok.startswith("@") and len(tok) > 1:
            author = tok[1:]
        else:
            kept.append(tok)

    # ``type [flags] [: params]`` — flags are bare words before the colon; params
    # (speaker / include name, possibly multi-word) is everything after the colon.
    left, sep, right = " ".join(kept).partition(":")
    left_toks = left.split()
    kind = left_toks[0] if left_toks else ""
    flags = left_toks[1:]
    params = right.strip()
    return {"type": kind, "params": params, "ratio": ratio,
            "overrides": overrides, "flags": flags, "author": author}


def parse_slide(chunk: str) -> dict | None:
    """Parse one slide chunk into {meta, title, blocks}."""
    lines = chunk.strip("\n").split("\n")
    meta = None
    title = None
    blocks: list[dict] = []
    para: list[str] = []
    bullets: list[dict] = []
    notes = None

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

        # speaker notes: a ``???`` line; everything after it (to slide end) is notes.
        if stripped == "???" or stripped.startswith("??? "):
            flush_para()
            flush_bullets()
            rest = [stripped[4:]] if stripped.startswith("??? ") else []
            rest += lines[i + 1:]
            notes = "\n".join(rest).strip()
            break

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
            body = "\n".join(code_lines)
            low = lang.lower()
            if low in GRAPH_ENGINES:
                blocks.append({"kind": "graph", "engine": low, "dot": body})
            elif low.startswith("chart"):
                ctype = low.split("-", 1)[1] if "-" in low else "bar"
                data = []
                for ln in code_lines:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        try:
                            data.append((k.strip(), float(v.strip())))
                        except ValueError:
                            pass
                blocks.append({"kind": "chart", "chart": ctype, "data": data})
            else:
                blocks.append({"kind": "code", "lang": lang, "text": body})
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

        # Subtitle: an *italic* line, right after the title, before other content.
        ms = SUBTITLE_RE.match(stripped)
        if ms and title is not None and not blocks and not para and not bullets:
            blocks.append({"kind": "subtitle", "text": ms.group(1).strip()})
            i += 1
            continue

        # Markdown table: a run of | ... | rows (an optional |---| separator row).
        if TABLE_ROW_RE.match(stripped):
            flush_para()
            flush_bullets()
            rows = []
            while i < len(lines) and TABLE_ROW_RE.match(lines[i].strip()):
                if not TABLE_SEP_RE.match(lines[i].strip()):
                    rows.append(_table_cells(lines[i].strip()))
                i += 1
            blocks.append({"kind": "table", "rows": rows})
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
            inner = mi.group(1).strip()
            # A URL becomes an interactive web page embedded in the slide (a custom
            # component); optional label after "|": <https://demo.dev | Live demo>.
            if re.match(r"https?://", inner, re.I):
                url, _, label = inner.partition("|")
                blocks.append({"kind": "weblink", "url": url.strip(),
                               "label": label.strip()})
            else:
                blocks.append({"kind": "include", "name": inner})
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

    if meta is None and title is None and not blocks and not notes:
        return None
    return {"meta": meta, "title": title, "blocks": blocks, "notes": notes}


def parse_markdown(text: str) -> list[dict]:
    slides = []
    for chunk in SLIDE_SEP.split(text):
        slide = parse_slide(chunk)
        if slide:
            slides.append(slide)
    return slides

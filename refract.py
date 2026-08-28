#!/usr/bin/env python3
"""refract — turn a simple markdown slide deck into RemoteCompose slides.

Pipeline:  markdown -> component JSON (androidx format) -> [json2rc] -> .rc

Deck layout on disk::

    <deck>/
      slides.md          # the deck
      includes/          # images, sub-decks, .rc / .json resources
      out/               # generated .rc files          (created)
      out/json/          # generated .json documents     (created)

Markdown grammar
----------------
* ``---`` on its own line separates slides; each becomes one ``.rc`` file.
* An optional ``:: <type> : <parameters>`` line right after the separator sets
  the slide metadata. ``<type>`` is one of ``title``, ``section``, ``content``
  (default) or ``include`` (splice another deck, see below).
* The first ``# heading`` in a slide is the title.
* Content is a sequence of blocks, in order:
    - paragraphs of text
    - bullet lists (``- item``, indent two spaces per sub-level)
    - fenced code blocks (```` ``` ````)
    - includes on their own line: ``<name>`` resolved from ``includes/``
      (``.png/.jpg`` image, ``.json`` RemoteCompose sub-document spliced inline,
      ``.rc`` prebuilt document used as a whole passthrough slide).

Deck includes
-------------
A slide ``:: include : <deckname>`` splices the deck at
``includes/<deckname>/slides.md`` into the master sequence. If it isn't found, a
placeholder ``<section <deckname> will go there>`` slide is emitted instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tomllib

SLIDE_SEP = re.compile(r"(?m)^\s*---\s*$")
TITLE_RE = re.compile(r"^#\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)-\s+(.+)$")
INCLUDE_LINE = re.compile(r"^<([^>]+)>$")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
INCLUDE_PROBE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".rc", ".json")

PADDING = 80
PANE_GAP = 48
LOGO_H_FRAC = 0.32   # image height on a title/section slide, as a fraction of slide height
SLIDE_BG = "#FF0D1B2A"
TITLE_COLOR = "#FFFFFFFF"
BODY_COLOR = "#FFE6EEF6"
CODE_BG = "#FF1E1E1E"
CODE_FG = "#FFD4D4D4"
DEBUG_BORDER = {"border": {"width": 1.0, "cornerRadius": 0.0, "color": "#FFFF0000", "shape": 0}}

# Basic slide types, selected via the ``:: <type> : ...`` metadata line.
SLIDE_TYPES = {
    "title":   {"h_align": "center", "v_align": "center", "title_size": 120.0, "body_size": 44.0},
    "section": {"h_align": "center", "v_align": "center", "title_size": 96.0,  "body_size": 36.0},
    "content": {"h_align": "start",  "v_align": "top",    "title_size": 72.0,  "body_size": 36.0},
}
DEFAULT_TYPE = "content"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
RATIO_RE = re.compile(r"\[(\d+(?::\d+)+)\]")


def parse_meta(spec: str) -> dict:
    """Parse a ``::`` metadata line: ``<type> [: <params>] [ratio]``.

    A pane ratio like ``[2:3]`` or ``[2:2:4]`` may appear anywhere on the line
    (its inner ``:`` would otherwise confuse the type/params split, so it is
    pulled out first)."""
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


# --------------------------------------------------------------------------- #
# Deck loading (with recursive deck includes)
# --------------------------------------------------------------------------- #
def load_deck(deck_dir: str, visited: set[str]) -> list[dict]:
    """Return a flat list of slides, expanding ``:: include`` deck references."""
    deck_dir = os.path.abspath(deck_dir)
    md_path = os.path.join(deck_dir, "slides.md")
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"no slides.md in {deck_dir}")
    with open(md_path) as f:
        raw_slides = parse_markdown(f.read())

    result = []
    for slide in raw_slides:
        meta = slide.get("meta") or {}
        if meta.get("type", "").lower() == "include":
            name = meta.get("params", "").strip()
            sub_dir = os.path.join(deck_dir, "includes", name)
            sub_md = os.path.join(sub_dir, "slides.md")
            if name and os.path.isfile(sub_md) and os.path.abspath(sub_dir) not in visited:
                result.extend(load_deck(sub_dir, visited | {os.path.abspath(sub_dir)}))
            else:
                result.append({
                    "meta": {"type": "section", "params": ""},
                    "title": None,
                    "blocks": [{"kind": "text", "text": f"<section {name} will go there>"}],
                    "base_dir": deck_dir,
                })
        else:
            slide["base_dir"] = deck_dir
            result.append(slide)
    return result


def image_size(path: str) -> tuple[int, int]:
    """Return (width, height) for a PNG/JPEG/GIF, or (1, 1) if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return w, h
            if head[:2] == b"\xff\xd8":  # JPEG: scan for a start-of-frame marker
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if not marker:
                        break
                    m = marker[0]
                    if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    seg = f.read(2)
                    if len(seg) < 2:
                        break
                    f.read(struct.unpack(">H", seg)[0] - 2)
    except (OSError, struct.error):
        pass
    return 1, 1


def resolve_include(name: str, includes_dir: str) -> dict:
    """Resolve an ``<name>`` include to a concrete block with an absolute path."""
    _, ext = os.path.splitext(name)
    candidates = [name] if ext else [name + e for e in INCLUDE_PROBE]
    for cand in candidates:
        path = os.path.join(includes_dir, cand)
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in IMAGE_EXTS:
                return {"kind": "image", "path": os.path.abspath(path)}
            if ext == ".rc":
                return {"kind": "rc_include", "path": os.path.abspath(path), "name": name}
            if ext == ".json":
                return {"kind": "json_include", "path": os.path.abspath(path)}
    return {"kind": "missing", "name": name}


def resolve_blocks(slide: dict) -> list[dict]:
    includes_dir = os.path.join(slide["base_dir"], "includes")
    resolved = []
    for block in slide["blocks"]:
        if block["kind"] == "include":
            resolved.append(resolve_include(block["name"], includes_dir))
        else:
            resolved.append(block)
    return resolved


# --------------------------------------------------------------------------- #
# Rendering to RemoteCompose component JSON
# --------------------------------------------------------------------------- #
def slide_type(slide: dict) -> str:
    meta = slide.get("meta") or {}
    kind = (meta.get("type") or DEFAULT_TYPE).lower()
    return kind if kind in SLIDE_TYPES else DEFAULT_TYPE


def dbg(mods: list, debug: bool) -> list:
    return mods + [DEBUG_BORDER] if debug else mods


def text_component(value: str, size: float, color: str, debug: bool, extra: list | None = None) -> dict:
    comp = {"type": "text", "value": value, "fontSize": size, "color": color}
    mods = dbg(list(extra or []), debug)
    if mods:
        comp["modifiers"] = mods
    return comp


def render_block(block: dict, spec: dict, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    kind = block["kind"]
    if kind == "text":
        return [text_component(block["text"], spec["body_size"], BODY_COLOR, debug)]

    if kind == "bullets":
        # One Text per bullet so each is its own line; indent sub-levels with spaces.
        return [
            text_component("    " * item["level"] + "•  " + item["text"],
                           spec["body_size"], BODY_COLOR, debug)
            for item in block["items"]
        ]

    if kind == "code":
        code_text = text_component(block["text"], 28.0, CODE_FG, debug)
        code_text["fontFamily"] = "monospace"
        return [{
            "type": "column",
            "modifiers": dbg(["fillMaxWidth", {"background": CODE_BG}, {"padding": 24.0}], debug),
            "children": [code_text],
        }]

    if kind == "image":
        # Temporary: the C++ viewer doesn't paint the image layout component, but it
        # does paint canvas bitmap draws. So emit a fixed-size canvas, compute the
        # fully-contained (aspect-preserving) rect here, and draw the bitmap into it.
        iw, ih = image_size(block["path"])
        cw = float(avail_w)
        ch = float(avail_h)
        scale = min(cw / iw, ch / ih)
        dw, dh = iw * scale, ih * scale
        left = round((cw - dw) / 2.0, 2)
        top = round((ch - dh) / 2.0, 2)
        counter[0] += 1
        var = f"__img{counter[0]}"
        return [{
            "type": "canvas",
            "modifiers": dbg([{"width": cw}, {"height": ch}], debug),
            "commands": [
                {"type": "addbitmap", "image": block["path"], "varName": var},
                {"type": "drawbitmap", "image": "$" + var,
                 "left": left, "top": top,
                 "right": round(left + dw, 2), "bottom": round(top + dh, 2)},
            ],
        }]

    if kind == "json_include":
        with open(block["path"]) as f:
            sub = json.load(f)
        root = sub.get("root")
        if isinstance(root, list):
            return root
        if isinstance(root, dict):
            return [root]
        return []

    if kind == "rc_include":
        # A prebuilt .rc can't be embedded into a JSON tree; only whole-slide
        # passthrough is supported. Reaching here means it was mixed with other
        # content, so show a placeholder.
        return [text_component(f"[rc include: {block['name']}]", spec["body_size"], BODY_COLOR, debug)]

    if kind == "missing":
        return [text_component(f"<{block['name']} missing>", spec["body_size"], BODY_COLOR, debug)]

    return []


def split_panes(blocks: list[dict]) -> list[list[dict]]:
    """Split a block list on ``pane_break`` markers into one list per pane."""
    panes: list[list[dict]] = [[]]
    for block in blocks:
        if block["kind"] == "pane_break":
            panes.append([])
        else:
            panes[-1].append(block)
    return panes


# Index expression for slide transitions: 0 on the first rendered frame, flipping to
# 1 at ~0.17s so the StateLayout crossfades from the previous slide to the new one.
TRANSITION_EXPR = "min(floor(animTime * 6), 1)"


def build_slide_root(slide: dict, blocks: list[dict], width: int, height: int,
                     index: int, debug: bool, counter: list) -> dict:
    """Build the root Column for one slide (no header wrapper)."""
    spec = SLIDE_TYPES[slide_type(slide)]
    content_w = width - 2 * PADDING
    centered = slide_type(slide) in ("title", "section")

    title_comp = None
    title_h = 0
    if slide.get("title"):
        title_comp = text_component(slide["title"], spec["title_size"], TITLE_COLOR, debug)
        title_h = int(spec["title_size"] * 1.8)
    avail_h = height - 2 * PADDING - title_h

    children = []
    panes = split_panes(blocks)
    if len(panes) <= 1:
        pane_blocks = panes[0] if panes else []
        if centered:
            # Title/section slides: image (e.g. a logo) sits ABOVE the title, at a
            # logo size, then the title, then the remaining content — all centered.
            imgs = [b for b in pane_blocks if b["kind"] == "image"]
            rest = [b for b in pane_blocks if b["kind"] != "image"]
            for block in imgs:
                children.extend(render_block(block, spec, debug, content_w, height * LOGO_H_FRAC, counter))
            if title_comp:
                children.append(title_comp)
            for block in rest:
                children.extend(render_block(block, spec, debug, content_w, avail_h, counter))
        else:
            if title_comp:
                children.append(title_comp)
            for block in pane_blocks:
                children.extend(render_block(block, spec, debug, content_w, avail_h, counter))
    else:
        if title_comp:
            children.append(title_comp)
        n = len(panes)
        ratio = (slide.get("meta") or {}).get("ratio")
        if not ratio or len(ratio) != n:
            ratio = [1] * n
        total = sum(ratio)
        avail = content_w - PANE_GAP * (n - 1)
        pane_nodes = []
        for i, pane_blocks in enumerate(panes):
            pane_w = avail * ratio[i] / total
            inner_w = pane_w - PANE_GAP
            inner_h = avail_h - PANE_GAP
            pane_children = []
            for block in pane_blocks:
                pane_children.extend(render_block(block, spec, debug, inner_w, inner_h, counter))
            pane_nodes.append({
                "type": "column",
                "modifiers": dbg([{"width": round(pane_w, 2)}, {"padding": float(PANE_GAP / 2)}], debug),
                "children": pane_children,
            })
        children.append({
            "type": "row",
            "modifiers": dbg(["fillMaxWidth"], debug),
            "children": pane_nodes,
        })

    return {
        "type": "column",
        "horizontalAlignment": spec["h_align"],
        "verticalAlignment": spec["v_align"],
        "modifiers": dbg(["fillMaxSize", {"background": SLIDE_BG}, {"padding": float(PADDING)}], debug),
        "children": children,
    }


def blank_root(debug: bool) -> dict:
    """An empty slide-coloured background (state 0 for the first slide's fade-in)."""
    return {
        "type": "column",
        "modifiers": dbg(["fillMaxSize", {"background": SLIDE_BG}], debug),
        "children": [],
    }


def _header(slide: dict, width: int, height: int, index: int) -> dict:
    return {
        "width": width,
        "height": height,
        "contentDescription": slide.get("title") or f"Slide {index + 1}",
    }


def build_doc(slide: dict, blocks: list[dict], width: int, height: int, index: int, debug: bool) -> dict:
    counter = [0]
    return {
        "header": _header(slide, width, height, index),
        "root": build_slide_root(slide, blocks, width, height, index, debug, counter),
    }


def build_transition_doc(prev: tuple | None, cur: tuple, width: int, height: int,
                         index: int, debug: bool) -> dict:
    """A StateLayout that crossfades from the previous slide (state 0) to the
    current slide (state 1); the index auto-advances on load via animTime."""
    counter = [0]
    prev_root = (blank_root(debug) if prev is None
                 else build_slide_root(prev[0], prev[1], width, height, index - 1, debug, counter))
    cur_root = build_slide_root(cur[0], cur[1], width, height, index, debug, counter)
    return {
        "header": _header(cur[0], width, height, index),
        "root": [
            {"type": "variable", "name": "__t", "vtype": "float", "value": TRANSITION_EXPR},
            {"type": "stateLayout", "indexId": "$__t", "modifiers": ["fillMaxSize"],
             "children": [prev_root, cur_root]},
        ],
    }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def slug(slide: dict, index: int) -> str:
    label = slide.get("title") or (slide.get("meta") or {}).get("type") or "slide"
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"{index + 1:02d}_{base or 'slide'}"


def load_settings(deck_dir: str) -> dict:
    """Load an optional ``settings.toml`` from the deck root (stdlib tomllib)."""
    path = os.path.join(deck_dir, "settings.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return {}


def apply_settings(settings: dict) -> None:
    """Apply theme colours from settings.toml to the module-level defaults."""
    global SLIDE_BG, TITLE_COLOR, BODY_COLOR, CODE_BG, CODE_FG
    theme = settings.get("theme", {})
    SLIDE_BG = theme.get("background", SLIDE_BG)
    TITLE_COLOR = theme.get("title_color", TITLE_COLOR)
    BODY_COLOR = theme.get("body_color", BODY_COLOR)
    CODE_BG = theme.get("code_background", CODE_BG)
    CODE_FG = theme.get("code_foreground", CODE_FG)


def find_json2rc(repo_root: str) -> str | None:
    for rel in ("prebuilt/json2rc/bin/json2rc",
                "json2rc/build/install/json2rc/bin/json2rc"):
        cand = os.path.join(repo_root, rel)
        if os.path.isfile(cand):
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown deck -> RemoteCompose .rc slides")
    ap.add_argument("deck", nargs="?", default=".", help="deck directory containing slides.md")
    ap.add_argument("--width", type=int, default=None, help="slide width (default 1600 or settings.toml)")
    ap.add_argument("--height", type=int, default=None, help="slide height (default 900 or settings.toml)")
    ap.add_argument("--debug", action="store_true", help="outline each component with a 1px red border")
    ap.add_argument("--transitions", action="store_true",
                    help="emit each slide as a StateLayout that crossfades from the previous slide")
    ap.add_argument("--json-only", action="store_true", help="emit JSON only; do not run json2rc")
    ap.add_argument("--json2rc", default=None, help="path to the json2rc launcher (default: auto-detect)")
    args = ap.parse_args()

    try:
        slides = load_deck(args.deck, {os.path.abspath(args.deck)})
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if not slides:
        print("no slides found", file=sys.stderr)
        return 1

    deck_dir = os.path.abspath(args.deck)
    out_dir = os.path.join(deck_dir, "out")
    json_dir = os.path.join(out_dir, "json")
    os.makedirs(json_dir, exist_ok=True)
    repo_root = os.path.dirname(os.path.abspath(__file__))

    # Fresh output: remove previously generated files so renamed or deleted slides
    # don't leave stale .rc/.json behind (the player would keep showing them).
    for d, exts in ((out_dir, (".rc",)), (json_dir, (".json",))):
        for fname in os.listdir(d):
            if fname.endswith(exts):
                os.remove(os.path.join(d, fname))

    # Settings precedence: CLI flag > settings.toml > built-in default.
    settings = load_settings(deck_dir)
    apply_settings(settings)
    slide_cfg = settings.get("slide", {})
    trans_cfg = settings.get("transition", {})
    width = args.width if args.width is not None else slide_cfg.get("width", 1600)
    height = args.height if args.height is not None else slide_cfg.get("height", 900)
    transitions = args.transitions or bool(trans_cfg.get("enabled", False))

    pairs = []       # (json_path, rc_path) to convert
    copies = []      # (src_rc, dst_rc) whole-slide passthroughs
    prev = None      # (slide, blocks) of the previous non-passthrough slide
    for i, slide in enumerate(slides):
        blocks = resolve_blocks(slide)
        name = slug(slide, i)
        rc_path = os.path.join(out_dir, name + ".rc")

        passthrough = (not slide.get("title") and len(blocks) == 1
                       and blocks[0]["kind"] == "rc_include")
        if passthrough:
            copies.append((blocks[0]["path"], rc_path))
            print(f"copy {rc_path}  [rc passthrough]")
            prev = None  # can't crossfade from a prebuilt .rc
            continue

        if transitions:
            doc = build_transition_doc(prev, (slide, blocks),
                                       width, height, i, args.debug)
            tag = "transition"
        else:
            doc = build_doc(slide, blocks, width, height, i, args.debug)
            tag = slide_type(slide)
        json_path = os.path.join(json_dir, name + ".json")
        with open(json_path, "w") as f:
            json.dump(doc, f, indent=2)
        pairs.append((json_path, rc_path))
        print(f"wrote {json_path}  [{tag}]")
        prev = (slide, blocks)

    for src, dst in copies:
        shutil.copyfile(src, dst)

    if args.json_only:
        return 0

    json2rc = args.json2rc or find_json2rc(repo_root)
    if not json2rc:
        print("json2rc launcher not found. Build it: (cd json2rc && ./gradlew installDist)\n"
              "or pass --json-only to stop at JSON.", file=sys.stderr)
        return 2

    if not pairs:
        return 0
    cmd = [json2rc]
    for json_path, rc_path in pairs:
        cmd += [json_path, rc_path]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())

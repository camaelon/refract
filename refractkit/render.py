"""Render slides (parsed blocks + theme) into RemoteCompose component JSON."""

from __future__ import annotations

import json

from .components import dbg, text
from .highlight import render_code
from .images import render_image
from .theme import Theme

PADDING = 80
PANE_GAP = 48
LOGO_H_FRAC = 0.32   # image height on a title/section slide, as a fraction of slide height

# Slide types, selected via the ``:: <type>`` metadata line.
SLIDE_TYPES = {
    "title":   {"h_align": "center", "v_align": "center", "title_size": 120.0, "body_size": 44.0},
    "section": {"h_align": "center", "v_align": "center", "title_size": 96.0,  "body_size": 36.0},
    "content": {"h_align": "start",  "v_align": "top",    "title_size": 72.0,  "body_size": 36.0},
}
DEFAULT_TYPE = "content"

# Transition index: 0 on the first frame, flipping to 1 at ~0.17s so the StateLayout
# crossfades from the previous slide to the new one on load.
TRANSITION_EXPR = "min(floor(animTime * 6), 1)"


def slide_type(slide: dict) -> str:
    kind = ((slide.get("meta") or {}).get("type") or DEFAULT_TYPE).lower()
    return kind if kind in SLIDE_TYPES else DEFAULT_TYPE


def shader_canvas(source: str, width: int, height: int) -> dict:
    """A full-slide canvas that fills the slide with an animated SkSL shader.

    ``iResolution`` is the slide size; ``iTime`` references animTime so the shader
    animates (the player re-evaluates the uniform from the variable each frame)."""
    w, h = float(width), float(height)
    return {
        "type": "canvas",
        "modifiers": ["fillMaxSize"],
        "commands": [
            {"type": "paint", "shader": {
                "agsl": source,
                "uniforms": {"iResolution": [w, h], "iTime": "animTime"}}},
            {"type": "drawrect", "left": 0.0, "top": 0.0, "right": w, "bottom": h},
        ],
    }


def split_panes(blocks: list[dict]) -> list[list[dict]]:
    """Split a block list on ``pane_break`` markers into one list per pane."""
    panes: list[list[dict]] = [[]]
    for block in blocks:
        if block["kind"] == "pane_break":
            panes.append([])
        else:
            panes[-1].append(block)
    return panes


def render_block(block: dict, spec: dict, theme: Theme, debug: bool,
                 avail_w: float, avail_h: float, counter: list) -> list[dict]:
    kind = block["kind"]
    if kind == "text":
        return [text(block["text"], spec["body_size"], theme.body_color, debug)]

    if kind == "bullets":
        # One Text per bullet so each is its own line; indent sub-levels with spaces.
        return [
            text("    " * item["level"] + "•  " + item["text"],
                 spec["body_size"], theme.body_color, debug)
            for item in block["items"]
        ]

    if kind == "code":
        return render_code(block, theme, debug)

    if kind == "image":
        return render_image(block, debug, avail_w, avail_h, counter)

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
        return [text(f"[rc include: {block['name']}]", spec["body_size"], theme.body_color, debug)]

    if kind == "missing":
        return [text(f"<{block['name']} missing>", spec["body_size"], theme.body_color, debug)]

    return []


def build_slide_root(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                     index: int, debug: bool, counter: list) -> dict:
    """Build the root Column for one slide (no header wrapper)."""
    spec = SLIDE_TYPES[slide_type(slide)]
    content_w = width - 2 * PADDING
    centered = slide_type(slide) in ("title", "section")

    title_comp = None
    title_h = 0
    if slide.get("title"):
        title_comp = text(slide["title"], spec["title_size"], theme.title_color, debug)
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
                children.extend(render_block(block, spec, theme, debug, content_w, height * LOGO_H_FRAC, counter))
            if title_comp:
                children.append(title_comp)
            for block in rest:
                children.extend(render_block(block, spec, theme, debug, content_w, avail_h, counter))
        else:
            if title_comp:
                children.append(title_comp)
            for block in pane_blocks:
                children.extend(render_block(block, spec, theme, debug, content_w, avail_h, counter))
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
                pane_children.extend(render_block(block, spec, theme, debug, inner_w, inner_h, counter))
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

    shader = theme.shader_for(slide_type(slide))
    bg_mods = [] if shader else [{"background": theme.background}]
    col = {
        "type": "column",
        "horizontalAlignment": spec["h_align"],
        "verticalAlignment": spec["v_align"],
        "modifiers": dbg(["fillMaxSize", *bg_mods, {"padding": float(PADDING)}], debug),
        "children": children,
    }
    if shader:
        # Layer the shader behind the (transparent) content column.
        return {
            "type": "box",
            "modifiers": dbg(["fillMaxSize"], debug),
            "children": [shader_canvas(shader, width, height), col],
        }
    return col


def blank_root(theme: Theme, width: int, height: int, debug: bool) -> dict:
    """An empty slide background (state 0 for the first slide's fade-in)."""
    shader = theme.shader_for("default")
    if shader:
        return {
            "type": "box",
            "modifiers": dbg(["fillMaxSize"], debug),
            "children": [shader_canvas(shader, width, height),
                         {"type": "column", "modifiers": ["fillMaxSize"], "children": []}],
        }
    return {
        "type": "column",
        "modifiers": dbg(["fillMaxSize", {"background": theme.background}], debug),
        "children": [],
    }


def header(slide: dict, width: int, height: int, index: int, profiles: int | None = None) -> dict:
    h = {
        "width": width,
        "height": height,
        "contentDescription": slide.get("title") or f"Slide {index + 1}",
    }
    if profiles is not None:
        h["profiles"] = profiles       # 512 = ANDROIDX (required to enable shader ops)
    return h


def _profiles(theme: Theme) -> int | None:
    return 512 if theme.shaders else None


def build_doc(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
              index: int, debug: bool) -> dict:
    counter = [0]
    return {
        "header": header(slide, width, height, index, _profiles(theme)),
        "root": build_slide_root(slide, blocks, theme, width, height, index, debug, counter),
    }


def build_transition_doc(prev: tuple | None, cur: tuple, theme: Theme, width: int, height: int,
                         index: int, debug: bool) -> dict:
    """A StateLayout that crossfades from the previous slide (state 0) to the current
    slide (state 1); the index auto-advances on load via animTime."""
    counter = [0]
    prev_root = (blank_root(theme, width, height, debug) if prev is None
                 else build_slide_root(prev[0], prev[1], theme, width, height, index - 1, debug, counter))
    cur_root = build_slide_root(cur[0], cur[1], theme, width, height, index, debug, counter)
    return {
        "header": header(cur[0], width, height, index, _profiles(theme)),
        "root": [
            {"type": "variable", "name": "__t", "vtype": "float", "value": TRANSITION_EXPR},
            {"type": "stateLayout", "indexId": "$__t", "modifiers": ["fillMaxSize"],
             "children": [prev_root, cur_root]},
        ],
    }

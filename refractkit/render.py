"""Render slides (parsed blocks + theme) into RemoteCompose component JSON."""

from __future__ import annotations

import json

from .chart import render_chart
from .components import dbg, text
from .graph import render_graph, render_graph_morph
from .highlight import render_code
from .inline import has_author, has_markup, styled_line
from .images import render_image
from .theme import Theme

PADDING = 80
PANE_GAP = 48
LOGO_H_FRAC = 0.32   # image height on a title/section slide, as a fraction of slide height

# Slide types (alignment only; font sizes come from the Theme, see theme.py [font]).
SLIDE_TYPES = {
    "title":   {"h_align": "center", "v_align": "center"},
    "section": {"h_align": "center", "v_align": "center"},
    "content": {"h_align": "start",  "v_align": "top"},
}
DEFAULT_TYPE = "content"

# Transition index: 0 on the first frame, flipping to 1 at ~0.17s so the StateLayout
# crossfades from the previous slide to the new one on load.
TRANSITION_EXPR = "min(floor(animTime * 6), 1)"

# Graph "magic move" progress. Kept as two small variables (expressions have a tight
# size limit): __gp is the linear clamp, __gt eases it (snappy ease-out-cubic: fast
# start, decelerating into place) over ~0.5s.
GRAPH_P_EXPR = "min(1.0, max(0.0, (animTime - 0.12) / 0.5))"
GRAPH_EASE_EXPR = "1.0 - (1.0 - $__gp) * (1.0 - $__gp) * (1.0 - $__gp)"
GRAPH_PROGRESS_VAR = "$__gt"

# `:: same` shared-element transition progress (eased 0→1), two small variables.
SAME_VAR = "$__st"


def _same_exprs(theme: Theme):
    p = f"min(1.0, max(0.0, (animTime - {theme.same_delay}) / {theme.same_duration}))"
    ease = "1.0 - (1.0 - $__sp) * (1.0 - $__sp) * (1.0 - $__sp)"
    return p, ease


def graph_block(blocks: list[dict]) -> dict | None:
    """The first graph block in a slide's blocks, if any."""
    for block in blocks:
        if block["kind"] == "graph":
            return block
    return None


def is_graph_slide(blocks: list[dict]) -> bool:
    """True only if a graph is the slide's *sole* content (so it can magic-move).
    A slide mixing a graph with bullets/panes/etc. is not a graph slide."""
    content = [b for b in blocks if b["kind"] != "pane_break"]
    return len(content) == 1 and content[0]["kind"] == "graph"


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


def vspacer(px: float) -> dict:
    """An empty fixed-height box, used as vertical spacing in a column."""
    return {"type": "box", "modifiers": [{"height": float(px)}], "children": []}


def split_panes(blocks: list[dict]) -> list[list[dict]]:
    """Split a block list on ``pane_break`` markers into one list per pane."""
    panes: list[list[dict]] = [[]]
    for block in blocks:
        if block["kind"] == "pane_break":
            panes.append([])
        else:
            panes[-1].append(block)
    return panes


def _splice_json(path: str) -> list[dict]:
    """Splice a RemoteCompose JSON document's root in as live components."""
    with open(path) as f:
        root = json.load(f).get("root")
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        return [root]
    return []


def render_table(rows: list[list[str]], theme: Theme, debug: bool) -> list[dict]:
    """A markdown table as a Column of Rows; first row is a header (accent, bold-ish)."""
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    out_rows = []
    for ri, cells in enumerate(rows):
        cells = cells + [""] * (ncols - len(cells))
        is_header = ri == 0
        color = theme.accent if is_header else theme.body_color
        cell_nodes = []
        for c in cells:
            cell_nodes.append({
                "type": "text", "value": c, "fontSize": theme.fonts["table"], "color": color,
                "modifiers": dbg([{"weight": 1.0}, {"padding": [10.0, 8.0]}], debug),
            })
        row_mods = ["fillMaxWidth"]
        if is_header:
            row_mods.append({"background": theme.table_header_bg})
        out_rows.append({"type": "row", "modifiers": dbg(row_mods, debug), "children": cell_nodes})
    return [{
        "type": "column",
        "modifiers": dbg(["fillMaxWidth", {"background": theme.table_bg}, {"padding": 16.0}], debug),
        "children": out_rows,
    }]


def _styled(line: str, size: float, color: str, theme: Theme, debug: bool,
            align: str = "start") -> dict:
    """A wrapping styled Flow if the line has inline markup or an author name to tint,
    else a plain wrapping Text. ``align`` centres the Flow on title/section slides."""
    if has_markup(line) or has_author(line, theme.authors):
        return styled_line(line, size, color, theme, debug, align)
    comp = text(line, size, color, debug)
    if align == "center":
        comp["textAlign"] = "center"
    return comp


def _enter_mods(theme: Theme) -> list:
    """Modifiers that animate an appearing (`:: same`) component in, driven by $__st."""
    t = SAME_VAR
    mods: list = [{"graphicsLayer": {"alpha": t}}]                 # fade in
    style = theme.same_enter
    if style == "slide-left":
        mods.append({"offset": {"x": f"(-160.0) * (1.0 - {t})", "y": 0.0}})
    elif style == "slide-right":
        mods.append({"offset": {"x": f"(160.0) * (1.0 - {t})", "y": 0.0}})
    elif style == "slide-up":
        mods.append({"offset": {"x": 0.0, "y": f"(60.0) * (1.0 - {t})"}})
    elif style == "slide-down":
        mods.append({"offset": {"x": 0.0, "y": f"(-60.0) * (1.0 - {t})"}})
    return mods


def _apply_enter(comp: dict, theme: Theme) -> dict:
    comp = dict(comp)
    comp["modifiers"] = list(comp.get("modifiers", [])) + _enter_mods(theme)
    return comp


def _apply_exit(comp: dict, theme: Theme, line_h: float) -> dict:
    """Wrap a disappearing (`:: same`) component so it fades out and collapses its
    height to 0 — the parent column reflows its neighbours up as it shrinks."""
    t = SAME_VAR
    mods: list = [{"height": f"({round(line_h, 2)}) * (1.0 - {t})"},
                  {"clip": 0.0}, {"graphicsLayer": {"alpha": f"1.0 - {t}"}}]
    style = theme.same_exit
    if style == "slide-left":
        mods.append({"offset": {"x": f"(-160.0) * {t}", "y": 0.0}})
    elif style == "slide-right":
        mods.append({"offset": {"x": f"(160.0) * {t}", "y": 0.0}})
    return {"type": "box", "modifiers": mods, "children": [comp]}


def _bullet_display(cur_items: list, same_ctx: dict) -> list:
    """Interleave disappearing bullets (state 'exit') into the current bullets (state
    'enter'/'static') at their previous position, so removed bullets collapse in place."""
    new = same_ctx["bullets_new"]
    gone = same_ctx["bullets_gone_ordered"] if not same_ctx.get("_gone_done") else []
    same_ctx["_gone_done"] = True
    out, gi = [], 0
    for i, it in enumerate(cur_items):
        while gi < len(gone) and gone[gi][0] <= i:
            out.append((gone[gi][1], "exit"))
            gi += 1
        out.append((it, "enter" if (it["level"], it["text"]) in new else "static"))
    while gi < len(gone):
        out.append((gone[gi][1], "exit"))
        gi += 1
    return out


def render_block(block: dict, body_size: float, theme: Theme, debug: bool,
                 avail_w: float, avail_h: float, counter: list,
                 same_ctx: dict | None = None, align: str = "start") -> list[dict]:
    kind = block["kind"]

    # `:: same`: graph that changed → morph in place; else fall through to static.
    if kind == "graph" and same_ctx and same_ctx.get("graph_changed"):
        return render_graph_morph(same_ctx["graph_prev"], block, theme, debug,
                                  avail_w, avail_h, SAME_VAR)

    if kind == "text":
        out = [_styled(line, body_size, theme.body_color, theme, debug, align)
               for line in block["text"].split("\n")]
    elif kind == "subtitle":
        out = [_styled(block["text"], theme.fonts["subtitle"], theme.accent, theme, debug, align)]
    elif kind == "table":
        out = render_table(block["rows"], theme, debug)
    elif kind == "bullets":
        # One line per bullet. For `:: same`, appearing bullets fade in and disappearing
        # ones (from the previous slide) collapse out in their old position.
        display = (_bullet_display(block["items"], same_ctx) if same_ctx
                   else [(it, "static") for it in block["items"]])
        out = []
        for item, state in display:
            comp = _styled("    " * item["level"] + "•  " + item["text"],
                           body_size, theme.body_color, theme, debug)
            if state == "enter":
                comp = _apply_enter(comp, theme)
            elif state == "exit":
                comp = _apply_exit(comp, theme, body_size * 1.5)
            out.append(comp)
        return out
    elif kind == "code":
        out = render_code(block, theme, debug)
    elif kind == "image":
        out = render_image(block, theme, debug, avail_w, avail_h, counter)
    elif kind == "graph":
        out = render_graph(block, theme, debug, avail_w, avail_h, counter)
    elif kind == "chart":
        out = render_chart(block, theme, debug, avail_w, avail_h, counter)
    else:
        out = None

    if out is not None:
        # A whole non-bullet block that only appears on the current slide animates in.
        if same_ctx and same_ctx["key"](block) in same_ctx["blocks_new"]:
            out = [_apply_enter(c, theme) for c in out]
        return out

    if kind == "json_include":
        return _splice_json(block["path"])

    if kind == "rc_include":
        # Embed the running document live by splicing its source JSON components.
        if block.get("json"):
            return _splice_json(block["json"])
        return [text(f"[rc include: {block['name']} — no .json sibling to embed live]",
                     body_size, theme.body_color, debug)]

    if kind == "missing":
        return [text(f"<{block['name']} missing>", body_size, theme.body_color, debug)]

    return []


def build_slide_root(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                     index: int, debug: bool, counter: list, same_ctx: dict | None = None) -> dict:
    """Build the root Column for one slide (no header wrapper)."""
    stype = slide_type(slide)
    spec = SLIDE_TYPES[stype]
    title_size = theme.title_size(stype)
    body_size = theme.body_size(stype)
    content_w = width - 2 * PADDING
    centered = stype in ("title", "section")

    # Title, followed by a configurable vertical gap before the content.
    title_group = []
    title_h = 0
    if slide.get("title"):
        title_group = [text(slide["title"], title_size, theme.title_color, debug),
                       vspacer(theme.title_gap)]
        title_h = int(title_size * 1.8 + theme.title_gap)
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
                children.extend(render_block(block, body_size, theme, debug, content_w, height * LOGO_H_FRAC, counter, same_ctx))
            children.extend(title_group)
            for block in rest:
                children.extend(render_block(block, body_size, theme, debug, content_w, avail_h, counter, same_ctx, align="center"))
        else:
            children.extend(title_group)
            for block in pane_blocks:
                children.extend(render_block(block, body_size, theme, debug, content_w, avail_h, counter, same_ctx))
    else:
        children.extend(title_group)
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
                pane_children.extend(render_block(block, body_size, theme, debug, inner_w, inner_h, counter, same_ctx))
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

    return frame_slide(children, spec, theme, slide_type(slide), width, height, debug)


def frame_slide(children: list, spec: dict, theme: Theme, stype: str,
                width: int, height: int, debug: bool) -> dict:
    """Wrap slide children in the root column, layering a shader background behind
    (in a Box) when the slide type has one, else a solid background."""
    shader = theme.shader_for(stype)
    bg_mods = [] if shader else [{"background": theme.background}]
    col = {
        "type": "column",
        "horizontalAlignment": spec["h_align"],
        "verticalAlignment": spec["v_align"],
        "modifiers": dbg(["fillMaxSize", *bg_mods, {"padding": float(PADDING)}], debug),
        "children": children,
    }
    if shader:
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


def _chrome_overlay(theme: Theme, index: int, total: int, width: int, height: int, debug: bool):
    """A bottom overlay: footer (left), page number (right), progress bar (very bottom).
    Returns None if no chrome is enabled."""
    author = getattr(theme, "slide_author", "")
    if not (theme.chrome_page or theme.chrome_footer or theme.chrome_progress or author):
        return None
    col = theme.chrome_color
    rows = []

    if theme.chrome_footer or theme.chrome_page or author:
        line = []
        if theme.chrome_footer:
            line.append({"type": "text", "value": theme.chrome_footer, "fontSize": 24.0,
                         "color": col})
        line.append({"type": "spacer", "modifiers": [{"weight": 1.0}]})
        # The attributed author (@name), tinted in their own accent colour.
        if author:
            line.append({"type": "text", "value": author, "fontSize": 24.0,
                         "color": theme.accent})
            if theme.chrome_page and total:
                line.append({"type": "text", "value": "   ", "fontSize": 24.0, "color": col})
        if theme.chrome_page and total:
            line.append({"type": "text", "value": f"{index + 1} / {total}", "fontSize": 24.0,
                         "color": col})
        rows.append({"type": "row",
                     "modifiers": dbg(["fillMaxWidth", {"padding": [float(PADDING), 20.0]}], debug),
                     "children": line})

    if theme.chrome_progress and total:
        frac = round((index + 1) / total, 4)
        filled = round(width * frac, 2)
        rows.append({"type": "box", "modifiers": ["fillMaxWidth", {"height": 6.0},
                     {"background": theme.table_bg}], "children": [
                        {"type": "box", "modifiers": [{"width": filled}, {"height": 6.0},
                         {"background": col}], "children": []}]})

    # Anchor the chrome column to the bottom of the slide.
    return {"type": "box", "horizontalAlignment": "start", "verticalAlignment": "bottom",
            "modifiers": dbg(["fillMaxSize"], debug), "children": [
                {"type": "column", "modifiers": ["fillMaxWidth"], "children": rows}]}


def with_chrome(content: dict, theme: Theme, index: int, total: int,
                width: int, height: int, debug: bool, stype: str = "content") -> dict:
    """Layer the chrome overlay on top of a slide's content node. The title slide is
    a clean cover — it never carries footer / page number / progress chrome."""
    if stype == "title":
        return content
    overlay = _chrome_overlay(theme, index, total, width, height, debug)
    if overlay is None:
        return content
    return {"type": "box", "modifiers": dbg(["fillMaxSize"], debug),
            "children": [content, overlay]}


def header(slide: dict, width: int, height: int, index: int, profiles: int | None = None) -> dict:
    h = {
        "width": width,
        "height": height,
        "contentDescription": slide.get("title") or f"Slide {index + 1}",
    }
    if profiles is not None:
        h["profiles"] = profiles       # 512 = ANDROIDX (required to enable shader ops)
    return h


PROFILE_EXPERIMENTAL = 0x1
PROFILE_ANDROIDX = 0x200          # 512


def _contains_shader(node) -> bool:
    if isinstance(node, dict):
        if "shader" in node or "runtimeShader" in node:
            return True
        return any(_contains_shader(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_shader(v) for v in node)
    return False


def _contains_type(node, type_name: str) -> bool:
    if isinstance(node, dict):
        if node.get("type") == type_name:
            return True
        return any(_contains_type(v, type_name) for v in node.values())
    if isinstance(node, list):
        return any(_contains_type(v, type_name) for v in node)
    return False


def _finalize(doc: dict) -> dict:
    """Set the header ``profiles`` bitmask to enable the extended ops the doc uses:
    ANDROIDX (512) for shader ops, and ANDROIDX+EXPERIMENTAL (513) for the Flow layout
    (op 240) emitted by wrapping inline-styled text."""
    root = doc.get("root")
    profiles = 0
    if _contains_shader(root):
        profiles |= PROFILE_ANDROIDX
    if _contains_type(root, "flow"):
        profiles |= PROFILE_ANDROIDX | PROFILE_EXPERIMENTAL
    if profiles:
        doc["header"]["profiles"] = profiles
    return doc


def build_doc(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
              index: int, debug: bool, total: int = 0) -> dict:
    counter = [0]
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, counter)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": with_chrome(root, theme, index, total, width, height, debug, slide_type(slide)),
    })


def build_transition_doc(prev: tuple | None, cur: tuple, theme: Theme, width: int, height: int,
                         index: int, debug: bool, total: int = 0) -> dict:
    """A StateLayout that crossfades from the previous slide (state 0) to the current
    slide (state 1); the index auto-advances on load via animTime."""
    counter = [0]
    prev_root = (blank_root(theme, width, height, debug) if prev is None
                 else build_slide_root(prev[0], prev[1], theme, width, height, index - 1, debug, counter))
    cur_root = build_slide_root(cur[0], cur[1], theme, width, height, index, debug, counter)
    state = {"type": "stateLayout", "indexId": "$__t", "modifiers": ["fillMaxSize"],
             "children": [prev_root, cur_root]}
    return _finalize({
        "header": header(cur[0], width, height, index),
        "root": [
            {"type": "variable", "name": "__t", "vtype": "float", "value": TRANSITION_EXPR},
            with_chrome(state, theme, index, total, width, height, debug, slide_type(cur[0])),
        ],
    })


# Push/slide transition: progress eased 0→1 over `duration` seconds after a short delay.
PUSH_DELAY = 0.05
PUSH_DURATION = 0.45
PUSH_EASE_EXPR = "1.0 - (1.0 - $__pp) * (1.0 - $__pp) * (1.0 - $__pp)"


def build_push_doc(prev: tuple | None, cur: tuple, theme: Theme, width: int, height: int,
                   index: int, debug: bool, total: int = 0, axis: str = "x", sign: int = 1,
                   duration: float = PUSH_DURATION) -> dict:
    """A push/slide transition: the previous slide slides out while the new one slides
    in from the opposite side, driven by an eased progress variable. No StateLayout —
    both roots are offset by expressions, so it animates in the current player.
    ``duration`` is the slide time in seconds (larger = slower)."""
    push_p_expr = f"min(1.0, max(0.0, (animTime - {PUSH_DELAY}) / {round(duration, 3)}))"
    counter = [0]
    d = sign * (width if axis == "x" else height)
    t = "$__pt"
    prev_off = {axis: f"(0.0) + (({-d}) - (0.0)) * {t}"}          # 0 → -d
    cur_off = {axis: f"({d}) + ((0.0) - ({d})) * {t}"}            # +d → 0

    def wrap(root, off):
        return {"type": "box", "modifiers": dbg(["fillMaxSize", {"offset": off}], debug),
                "children": [root]}

    children = []
    if prev is not None:
        prev_root = build_slide_root(prev[0], prev[1], theme, width, height, index - 1, debug, counter)
        children.append(wrap(prev_root, prev_off))
    cur_root = build_slide_root(cur[0], cur[1], theme, width, height, index, debug, counter)
    children.append(wrap(cur_root, cur_off))

    stage = {"type": "box", "modifiers": dbg(["fillMaxSize"], debug), "children": children}
    return _finalize({
        "header": header(cur[0], width, height, index),
        "root": [
            {"type": "variable", "name": "__pp", "vtype": "float", "value": push_p_expr},
            {"type": "variable", "name": "__pt", "vtype": "float", "value": PUSH_EASE_EXPR},
            with_chrome(stage, theme, index, total, width, height, debug, slide_type(cur[0])),
        ],
    })


def build_graph_transition_doc(prev: tuple, cur: tuple, theme: Theme, width: int, height: int,
                               index: int, debug: bool, total: int = 0) -> dict:
    """A graph "magic move": one morphing graph whose matched nodes (by dot id) glide
    and resize from the previous layout to the new one, driven by a progress variable.
    Unmatched nodes fade; edges crossfade."""
    slide, blocks = cur
    stype = slide_type(slide)
    spec = SLIDE_TYPES[stype]
    content_w = width - 2 * PADDING

    children = []
    title_h = 0
    if slide.get("title"):
        title_size = theme.title_size(stype)
        children.append(text(slide["title"], title_size, theme.title_color, debug))
        children.append(vspacer(theme.title_gap))
        title_h = int(title_size * 1.8 + theme.title_gap)
    avail_h = height - 2 * PADDING - title_h

    children.extend(render_graph_morph(graph_block(prev[1]), graph_block(blocks),
                                       theme, debug, content_w, avail_h, GRAPH_PROGRESS_VAR))
    root_col = frame_slide(children, spec, theme, slide_type(slide), width, height, debug)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": [
            {"type": "variable", "name": "__gp", "vtype": "float", "value": GRAPH_P_EXPR},
            {"type": "variable", "name": "__gt", "vtype": "float", "value": GRAPH_EASE_EXPR},
            with_chrome(root_col, theme, index, total, width, height, debug, stype),
        ],
    })


def build_same_doc(prev: tuple, cur: tuple, theme: Theme, width: int, height: int,
                   index: int, debug: bool, total: int = 0) -> dict:
    """A `:: same` shared-element transition (lerp backend).

    The current slide is rendered normally so matched, unchanged content stays put
    (and text keeps proper wrapping); a matched graph morphs in place; content that
    appears fades/slides in. Matching lives in ``samematch`` and the animation is
    driven by the eased progress variable ``$__st`` — this whole function is the single
    swap point for a future StateLayout+animationId backend.
    """
    from .samematch import diff_slides
    slide, blocks = cur
    same_ctx = diff_slides(prev[1], blocks)
    counter = [0]
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, counter, same_ctx)
    p_expr, ease_expr = _same_exprs(theme)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": [
            {"type": "variable", "name": "__sp", "vtype": "float", "value": p_expr},
            {"type": "variable", "name": "__st", "vtype": "float", "value": ease_expr},
            with_chrome(root, theme, index, total, width, height, debug, slide_type(slide)),
        ],
    })

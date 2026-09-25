"""Render slides (parsed blocks + theme) into RemoteCompose component JSON."""

from __future__ import annotations

import json
import os

from .chart import render_chart
from .components import dbg, text, torn_fill_commands
from .graph import render_graph, render_graph_morph
from .highlight import render_code
from .inline import has_author, has_markup, styled_line
from .images import render_image
from .markers import marker_canvas, marker_commands, normalize_shape
from .measure import fit_body_size
from .theme import Theme

PADDING = 80
PANE_GAP = 48
LOGO_H_FRAC = 0.32   # image height on a title/section slide, as a fraction of slide height
CHROME_BAND = 80.0   # approx height of the bottom chrome (footer row + progress bar)


def _pad_sides(pad) -> tuple[float, float, float, float]:
    """Normalise a slide's ``padding`` spec to (left, top, right, bottom). A number is
    uniform; a 4-list is [left, top, right, bottom]; a dict uses those named keys."""
    if isinstance(pad, dict):
        return (float(pad.get("left", 0)), float(pad.get("top", 0)),
                float(pad.get("right", 0)), float(pad.get("bottom", 0)))
    if isinstance(pad, (list, tuple)) and len(pad) == 4:
        return tuple(float(v) for v in pad)  # type: ignore[return-value]
    return (float(pad), float(pad), float(pad), float(pad))


def _pad_for(spec: dict, theme) -> tuple[float, float, float, float]:
    """The slide's effective padding (left, top, right, bottom): its type's base margin plus
    any per-slide ``pad_extra`` delta (from ``pad_left=`` / ``pad=`` overrides)."""
    base = _pad_sides(spec.get("padding", PADDING))
    extra = getattr(theme, "pad_extra", (0.0, 0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0, 0.0)
    return tuple(b + e for b, e in zip(base, extra))  # type: ignore[return-value]


def _chrome_reserve(theme: "Theme", stype: str, pad: float) -> float:
    """Vertical space to keep free at the bottom for the chrome, so content (especially a
    native webview/video overlay) doesn't sit under it. Zero unless the chrome is shown
    and the slide's margin is smaller than the chrome band. The title slide has no chrome."""
    if stype == "title" or getattr(theme, "chrome_hidden", False):
        return 0.0
    shown = (theme.chrome_page or theme.chrome_footer or theme.chrome_progress
             or bool(getattr(theme, "slide_author", "")))
    return max(0.0, CHROME_BAND - pad) if shown else 0.0

# Slide types (alignment + margin; font sizes come from the Theme, see theme.py [font]).
# ``max`` is near-fullscreen: a small margin so the content is maximised, a smaller
# title, and the chrome still shown.
SLIDE_TYPES = {
    "title":   {"h_align": "center", "v_align": "center", "padding": PADDING},
    "section": {"h_align": "center", "v_align": "center", "padding": PADDING},
    "content": {"h_align": "start",  "v_align": "top",    "padding": PADDING},
    # Near-fullscreen: tight top/left/right margins to maximise the content, but keep a
    # normal bottom margin so the footer chrome still has room.
    "max":     {"h_align": "start",  "v_align": "top",
                "padding": {"left": 16.0, "top": 16.0, "right": 16.0, "bottom": 32.0}},
    # Two columns from `+++`, but laid out row-first: the last column runs full-height (from
    # the top, past the title), and the title is confined to the left column's width.
    "split":   {"h_align": "start",  "v_align": "top",    "padding": PADDING},
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
    meta = slide.get("meta") or {}
    kind = (meta.get("type") or DEFAULT_TYPE).lower()
    if kind == "as":
        kind = (meta.get("as_type") or meta.get("layout") or DEFAULT_TYPE).lower()
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


def transition_overlay_canvas(source: str, width: int, height: int, progress_var: str) -> dict:
    """A full-slide canvas running an overlay shader during a transition. Besides
    ``iResolution``/``iTime`` it gets ``iProgress`` — the transition's 0→1 progress
    variable — so the effect lives only while the transition plays."""
    w, h = float(width), float(height)
    return {
        "type": "canvas",
        "modifiers": ["fillMaxSize"],
        "commands": [
            {"type": "paint", "shader": {
                "agsl": source,
                "uniforms": {"iResolution": [w, h], "iTime": "animTime",
                             "iProgress": progress_var}}},
            {"type": "drawrect", "left": 0.0, "top": 0.0, "right": w, "bottom": h},
        ],
    }


def with_transition_shader(content: dict, theme: Theme, width: int, height: int,
                           progress_var: str, debug: bool) -> dict:
    """Layer the transition overlay shader on top of a slide's content (below chrome)."""
    if not theme.transition_shader:
        return content
    return {"type": "box", "modifiers": dbg(["fillMaxSize"], debug),
            "children": [content, transition_overlay_canvas(
                theme.transition_shader, width, height, progress_var)]}


def _render_bg_asset(path: str, theme: Theme, width: float, height: float,
                     debug: bool) -> list[dict]:
    """Render a background inclusion (.json / .rc / image) at full (width, height)."""
    import os
    if not path or not os.path.isfile(path):
        return []
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        nodes = _splice_json(path)
        return [{"type": "box", "modifiers": dbg(["fillMaxSize"], debug), "children": nodes}]
    if ext == ".rc":
        return render_rc_embed({"path": path, "fit": "fill"}, theme, debug, width, height)
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return render_image({"path": path}, theme, debug, width, height, [0])
    return []


def _heading_bg_box(title: str, level: int, hcfg: dict, content_w: float,
                    theme: Theme, debug: bool, h_align: str = "start") -> tuple[dict, float]:
    """Render a heading (title or subheading level) over its shader or RemoteCompose doc/color
    backdrop. Returns (box_node, reserved_height)."""
    from dataclasses import replace as _replace
    size = hcfg["font_size"]
    pad_l, pad_t, pad_r, pad_b = (hcfg["pad_left"], hcfg["pad_top"],
                                  hcfg["pad_right"], hcfg["pad_bottom"])
    txt_theme = _replace(
        theme,
        body_font=hcfg["family"] or theme.title_font or theme.body_font,
        body_weight=hcfg["weight"] or theme.title_weight or theme.body_weight,
        body_color=hcfg["color"],
    )
    lines = title.split("\n")
    if len(lines) > 1:
        txt = {"type": "column", "modifiers": dbg([], debug),
               "children": [_styled(l, size, hcfg["color"], txt_theme, debug, h_align) for l in lines]}
    else:
        txt = _styled(title, size, hcfg["color"], txt_theme, debug, h_align)
    pad_mod = None
    if any((pad_l, pad_t, pad_r, pad_b)):
        pad_mod = {"padding": [round(pad_l, 2), round(pad_t, 2),
                               round(pad_r, 2), round(pad_b, 2)]}

    from .measure import _text_height
    text_h = _text_height(title, size, max(1.0, content_w - pad_l - pad_r))
    if not hcfg.get("fill_width", True):
        if pad_mod:
            txt["modifiers"] = list(txt.get("modifiers", [])) + [pad_mod]
        mods = []
        if hcfg.get("bg_color"):
            mods.append({"background": hcfg["bg_color"]})
        if hcfg.get("corner_radius", 0.0) > 0:
            mods.append({"clip": float(hcfg["corner_radius"])})
        children = []
        if hcfg.get("background_doc"):
            est_w = min(content_w, len(title) * size * 0.55 + pad_l + pad_r + 24)
            est_h = text_h + pad_t + pad_b
            children.extend(_render_bg_asset(hcfg["background_doc"], theme, est_w, est_h, debug))
        children.append(txt)
        box = {
            "type": "box",
            "horizontalAlignment": "center", "verticalAlignment": "center",
            "modifiers": dbg(mods, debug),
            "children": children,
        }
        return box, round(text_h + pad_t + pad_b, 2)

    if pad_mod:
        txt = {"type": "box", "modifiers": ["fillMaxWidth", pad_mod], "children": [txt]}

    band_h = hcfg.get("band_height")
    if band_h is None:
        if hcfg.get("shader") and level == 1:
            band_h = round(size * 2.1, 2)
        else:
            band_h = round(text_h + pad_t + pad_b, 2)
    bg_children = []
    if hcfg.get("shader"):
        bg_children.append(shader_canvas(hcfg["shader"], content_w, band_h))
    if hcfg.get("background_doc"):
        bg_children.extend(_render_bg_asset(hcfg["background_doc"], theme, content_w, band_h, debug))
    box_mods: list = ["fillMaxWidth", {"height": round(band_h, 2)}]
    if hcfg.get("bg_color"):
        box_mods.append({"background": hcfg["bg_color"]})
    if hcfg.get("corner_radius", 0.0) > 0:
        box_mods.append({"clip": float(hcfg["corner_radius"])})
    v_align = "center" if (hcfg.get("shader") and level == 1) else ("bottom" if pad_b > 0 else "center")
    box = {
        "type": "box",
        "horizontalAlignment": h_align, "verticalAlignment": v_align,
        "modifiers": dbg(box_mods, debug),
        "children": [*bg_children, txt],
    }
    return box, band_h


def _numbered_title_row(number: int, title: str, size: float, theme: Theme,
                        debug: bool, color: str | None = None) -> dict:
    """A section heading whose leading ``N.`` is tinted with the deck's primary colour.
    A Row that wraps to its content, so the parent column centres it like a plain title."""
    ttl_color = color or theme.title_color
    num = text(f"{number}.", size, theme.primary, debug,
               family=theme.title_font, weight=theme.title_weight)
    ttl = text(f" {title}", size, ttl_color, debug,
               family=theme.title_font, weight=theme.title_weight)
    return {"type": "row", "verticalAlignment": "center",
            "modifiers": dbg([], debug), "children": [num, ttl]}


def _title_group(slide: dict, stype: str, title_size: float, content_w: float,
                 theme: Theme, centered: bool, debug: bool) -> tuple:
    """Build the [title, gap-spacer] nodes and reserved title height for a slide. Applies
    the title-element shader or background doc unless the slide *type* already has a
    full-slide shader/bg_doc of its own. Shared by the normal layout and magic-move builder."""
    if not slide.get("title"):
        return [], 0
    gap = theme.title_gap * (0.5 if stype == "max" else 1.0)
    meta = slide.get("meta") or {}
    overrides = meta.get("overrides") or {}
    flags = meta.get("flags") or []
    num = slide.get("section_number")
    if not getattr(theme, "section_numbered", True) or \
       str(overrides.get("numbered", overrides.get("number", "true"))).lower() in ("false", "0", "off", "no") or \
       "unnumbered" in flags or "plain" in flags:
        num = None
    hcfg = theme.heading_config(1, stype, title_size)
    t_size = hcfg["font_size"]
    t_color = hcfg["color"]
    t_family = hcfg["family"] or theme.title_font
    t_weight = hcfg["weight"] or theme.title_weight
    is_centered = centered or getattr(theme, "h_align", None) == "center"
    if hcfg["has_bg"] and stype not in theme.shaders and stype not in theme.bg_docs:
        disp = f"{num}. {slide['title']}" if num else slide["title"]
        node, band_h = _heading_bg_box(disp, 1, hcfg, content_w, theme,
                                       debug, "center" if is_centered else "start")
        title_h = int(band_h + gap)
    elif num:
        node = _numbered_title_row(num, slide["title"], t_size, theme, debug, t_color)
        title_h = int(t_size * 1.8 + gap)
    else:
        title_str = str(slide["title"]).replace("<br>", "\n").replace("<br/>", "\n")
        lines = title_str.split("\n")
        from dataclasses import replace as _replace
        txt_theme = _replace(
            theme,
            title_font=t_family,
            title_weight=t_weight,
            body_font=t_family,
            body_weight=t_weight,
            body_color=t_color,
        )
        if len(lines) == 1:
            if has_markup(lines[0]) or has_author(lines[0], theme.authors):
                node = _styled(lines[0], t_size, t_color, txt_theme, debug, "center" if is_centered else "start")
            else:
                node = text(lines[0], t_size, t_color, debug,
                            family=t_family, weight=t_weight)
                if is_centered:
                    node["textAlign"] = "center"
            title_h = int(t_size * 1.8 + gap)
        else:
            # `line_height` (a fraction of the font size) pins the pitch of a multi-line
            # title. Without it each line is as tall as the font asks to be, which is right
            # for a deck written by hand and wrong for one traced off a source that set its
            # own line spacing.
            lh = float(hcfg.get("line_height") or 0.0)
            line_h = t_size * lh if lh else 0.0
            line_nodes = []
            for l in lines:
                if has_markup(l) or has_author(l, theme.authors):
                    tnode = _styled(l, t_size, t_color, txt_theme, debug, "center" if is_centered else "start")
                else:
                    tnode = text(l, t_size, t_color, debug, family=t_family, weight=t_weight)
                    if is_centered:
                        tnode["textAlign"] = "center"
                if line_h:
                    tnode = {"type": "box", "modifiers": dbg([{"height": line_h}], debug),
                             "horizontalAlignment": "center" if is_centered else "start",
                             "verticalAlignment": "center",
                             "children": [tnode]}
                line_nodes.append(tnode)
            node = {"type": "column", "modifiers": dbg([], debug), "children": line_nodes}
            if is_centered:
                node["horizontalAlignment"] = "center"
            title_h = int((line_h or t_size * 1.35) * len(lines) + gap)
    t_pad_top = float(overrides.get("title_pad_top", hcfg.get("pad_top", 0.0)))
    if t_pad_top:
        node = {"type": "column", "modifiers": dbg([], debug), "children": [vspacer(t_pad_top), node]}
        title_h += int(t_pad_top)
    # Horizontal insets. These indent the title alone; the slide's own `[layout]`
    # padding is the wrong lever for that because it shifts every other block too.
    t_pad_l = float(hcfg.get("pad_left", 0.0))
    t_pad_r = float(hcfg.get("pad_right", 0.0))
    if t_pad_l or t_pad_r:
        wrap = {"type": "column",
                "modifiers": dbg(["fillMaxWidth", {"padding": [t_pad_l, 0.0, t_pad_r, 0.0]}], debug),
                "children": [node]}
        if is_centered:
            wrap["horizontalAlignment"] = "center"
        node = wrap
    return [node, vspacer(gap)], title_h


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
    base_dir = os.path.dirname(os.path.abspath(path))
    with open(path) as f:
        root = json.load(f).get("root")
    if not root:
        return []

    def _resolve_images(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "addbitmap" and "image" in obj:
                img = obj["image"]
                if isinstance(img, str) and not os.path.isabs(img) and not img.startswith("$"):
                    search_dirs = [
                        base_dir,
                        os.path.normpath(os.path.join(base_dir, "..", "include")),
                        os.path.normpath(os.path.join(base_dir, "..", "includes")),
                        os.path.normpath(os.path.join(base_dir, "..", "..", "includes")),
                        os.path.normpath(os.path.join(base_dir, "..", "..", "theme", "include")),
                        os.path.normpath(os.path.join(base_dir, "..", "..", "theme", "includes")),
                    ]
                    for d in search_dirs:
                        cand = os.path.join(d, img)
                        if os.path.isfile(cand):
                            obj["image"] = os.path.abspath(cand)
                            break
            for v in obj.values():
                _resolve_images(v)
        elif isinstance(obj, list):
            for item in obj:
                _resolve_images(item)

    _resolve_images(root)
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        return [root]
    return []


def _clipped_splice(path: str, theme: Theme, debug: bool, avail_h: float,
                    block: dict | None = None) -> list[dict]:
    """Splice a document's components into the slide, wrapped in a clip frame so its canvas
    draw instructions can't spill past the area it occupies (a fillMaxSize embed otherwise
    draws unclipped). Rounds the corners if ``[image] corner_radius`` is set. A ``title``
    option on the block draws a centred caption below the spliced content."""
    _, _, cap_h = _caption_metrics(block or {}, theme)
    mods: list = ["fillMaxWidth", {"height": round(float(avail_h - cap_h), 2)},
                  {"clip": float(theme.image_corner_radius or 0.0)}]
    box = {"type": "box", "modifiers": dbg(mods, debug), "children": _splice_json(path)}
    return _with_caption(box, block or {}, theme, debug, avail_h)


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
    mods: list = ["fillMaxWidth"]
    if theme.table_corner_radius > 0:
        mods.append({"clip": float(theme.table_corner_radius)})   # round the panel (+ header)
    mods += [{"background": theme.table_bg}, {"padding": 16.0}]
    return [{
        "type": "column",
        "modifiers": dbg(mods, debug),
        "children": out_rows,
    }]


def _styled(line: str, size: float, color: str, theme: Theme, debug: bool,
            align: str = "start") -> dict:
    """A wrapping styled Flow if the line has inline markup or an author name to tint,
    else a plain wrapping Text. ``align`` centres the Flow on title/section slides."""
    if has_markup(line) or has_author(line, theme.authors):
        return styled_line(line, size, color, theme, debug, align)
    comp = text(line, size, color, debug, family=theme.body_font, weight=theme.body_weight)
    if align == "center":
        comp["textAlign"] = "center"
    return comp


def _bullet_row(item: dict, size: float, theme: Theme, debug: bool, counter: list) -> dict:
    """A bullet as a Row: a drawn shape marker aligned to the first text line, then the
    wrapping text. Sub-levels (level >= 1) are indented and may use a different marker,
    font family, weight and colour (theme ``bullet_sub_*``, else inherit the top level)."""
    from dataclasses import replace as _replace
    level = item["level"]
    sub = level >= 1
    shape = (theme.bullet_sub_shape or theme.bullet_shape) if sub else theme.bullet_shape
    marker_color = theme.bullet_color or theme.primary        # its own colour, default primary
    text_color = (theme.bullet_sub_color or theme.body_color) if sub else theme.body_color
    # Render the text through a theme whose body font/weight/colour carry the sub overrides.
    txt_theme = theme
    if sub and (theme.bullet_sub_font or theme.bullet_sub_weight or theme.bullet_sub_color):
        txt_theme = _replace(theme,
                             body_font=theme.bullet_sub_font or theme.body_font,
                             body_weight=theme.bullet_sub_weight or theme.body_weight,
                             body_color=text_color)
    line_h = round(size * 1.2, 1)
    slot_w = round(size * 0.9, 1)          # marker column width
    r = round(size * (0.28 if normalize_shape(shape) in ("four", "asanoha", "quad") else 0.2), 1)
    counter[0] += 1
    # Marker centred vertically on the first line's cap (a touch above the line midpoint).
    marker = marker_canvas(shape, slot_w, line_h, r, marker_color, theme.bullet_filled,
                           debug, uid=f"bm{counter[0]}", cy=round(size * 0.56, 1))
    txt = _styled(item["text"], size, text_color, txt_theme, debug)
    txt = dict(txt)
    txt["modifiers"] = list(txt.get("modifiers", [])) + [{"weight": 1.0}]  # take remaining width
    kids: list = []
    if level:
        kids.append({"type": "box", "modifiers": [{"width": round(size * 1.3 * level, 1)}],
                     "children": []})
    kids += [marker, {"type": "box", "modifiers": [{"width": round(size * 0.32, 1)}],
                      "children": []}, txt]
    return {"type": "row", "verticalAlignment": "top",
            "modifiers": dbg(["fillMaxWidth"], debug), "children": kids}


def _reveal_wrap(node: dict, theme: Theme, i: int) -> dict:
    """Give a content node a staggered fade-and-rise entrance driven by the built-in
    ``animTime``: item ``i`` starts at ``delay + i*stagger`` and eases in over ``duration``.
    Alpha is a linear fade; the upward slide uses a snappy ease-out (kept within the 32-token
    expression budget — the clamp appears at most twice)."""
    s = round(theme.reveal_delay + i * theme.reveal_stagger, 3)
    d = round(max(0.01, theme.reveal_duration), 3)
    p = f"min(1.0, max(0.0, (animTime - {s}) / {d}))"      # 0→1 clamp for this item
    node = dict(node)
    mods = list(node.get("modifiers", []))
    mods.append({"graphicsLayer": {"alpha": p}})
    if theme.reveal_rise:
        rise = round(theme.reveal_rise, 2)
        mods.append({"offset": {"x": 0.0, "y": f"({rise}) * (1.0 - {p}) * (1.0 - {p})"}})
    node["modifiers"] = mods
    return node


def _stagger(nodes: list, theme: Theme, start: int = 0) -> list:
    """Apply a staggered entrance to each node (skipping any that are None/empty)."""
    return [_reveal_wrap(n, theme, start + i) for i, n in enumerate(nodes)]


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


def render_weblink(block: dict, theme: Theme, debug: bool,
                   avail_w: float, avail_h: float) -> list[dict]:
    """An interactive web page as a native custom component (op 93). The viewer's web
    host positions a real, clickable WKWebView over this box — so the page is embedded
    in the slide (and follows transitions) rather than a separate window."""
    mods: list = ["fillMaxWidth", {"height": round(float(avail_h), 2)}]
    if theme.image_corner_radius > 0:
        mods.append({"clip": float(theme.image_corner_radius)})
    return [{"type": "custom", "config": f"web:{block['url']}",
             "modifiers": dbg(mods, debug), "children": []}]


def _media_config(kind: str, src: str, opts: dict) -> str:
    """Build a custom-component config string ``kind:src`` with an optional ``#k=v&k=v``
    option suffix. Both native hosts parse this scheme (a bare ``#value`` is still read as
    the fit, for back-compat)."""
    parts = [f"{k}={v}" for k, v in opts.items() if v not in (None, "")]
    return f"{kind}:{src}" + ("#" + "&".join(parts) if parts else "")


def _crop_opt(block: dict) -> str:
    """A ``crop`` option value (``l,t,r,b``) from the block, or empty."""
    crop = block.get("crop")
    return ",".join(str(round(float(c), 4)) for c in crop) if crop else ""


def _caption_metrics(block: dict, theme: Theme) -> tuple:
    """(caption text, font size, reserved height) for an embed's optional ``title`` caption,
    or (None, 0, 0) when it has none. The caption is a touch smaller than body text."""
    cap = block.get("caption")
    if not cap:
        return None, 0.0, 0.0
    size = round(theme.body_size("content") * 0.78, 1)
    gap = round(size * 0.5, 1)
    return cap, size, size * 1.5 + gap


def _with_caption(content, block: dict, theme: Theme, debug: bool, avail_h: float) -> list[dict]:
    """Wrap an embed's node(s) in a column with a centred caption beneath (from the block's
    ``title`` option). ``content`` is the embed node or a list of them; the caller has already
    shrunk it by the reserved caption height so the pair still fits ``avail_h``. Returns the
    content unwrapped (as a list) when there's no caption."""
    children = content if isinstance(content, list) else [content]
    cap, size, _ = _caption_metrics(block, theme)
    if not cap:
        return children
    node = text(cap, size, theme.body_color, debug,
                family=theme.body_font, weight=theme.body_weight,
                extra=["fillMaxWidth", {"padding": [0.0, round(size * 0.5, 1), 0.0, 0.0]}])
    node["textAlign"] = "center"
    return [{"type": "column",
             "modifiers": dbg(["fillMaxWidth", {"height": round(float(avail_h), 2)}], debug),
             "children": [*children, node]}]


def _embed_box(inner: dict, avail_w: float, box_h: float, ratio, corner: float,
               debug: bool) -> dict:
    """Size an embed's box. By default it fills the width at ``box_h`` tall; when ``ratio``
    (width / height) is set the box is fitted to that aspect ratio within (avail_w, box_h) and
    centred in the area, so a square face doesn't stretch to fill a wide slide. ``inner`` is the
    embed node — this sets its size/clip modifiers (it must not already carry them)."""
    framed = ratio is not None
    if framed:
        bh = float(box_h)
        bw = bh * ratio
        if bw > avail_w:
            bw, bh = float(avail_w), float(avail_w) / ratio
        mods: list = [{"width": round(bw, 2)}, {"height": round(bh, 2)}]
    else:
        mods = ["fillMaxWidth", {"height": round(float(box_h), 2)}]
    if corner and corner > 0:
        mods.append({"clip": float(corner)})
    inner["modifiers"] = dbg(mods, debug)
    if not framed:
        return inner
    return {"type": "box",
            "modifiers": dbg(["fillMaxWidth", {"height": round(float(box_h), 2)}], debug),
            "horizontalAlignment": "center", "verticalAlignment": "center",
            "children": [inner]}


def render_video(block: dict, theme: Theme, debug: bool,
                 avail_w: float, avail_h: float) -> list[dict]:
    """An embedded video as a native custom component (op 93). The box fills the available
    area (width × height); the viewer's video host plays the clip **aspect-fit** inside it,
    so a portrait phone recording fills the height and a landscape clip fills the width —
    refract doesn't need to know the clip's real aspect. An optional ``crop`` (source
    fractions ``l,t,r,b``) trims the frame, e.g. to remove black bars. A ``title`` option
    draws a centred caption below the clip."""
    _, _, cap_h = _caption_metrics(block, theme)
    box_h = avail_h - cap_h
    src = block.get("src") or block["path"].rsplit("/", 1)[-1]
    config = _media_config("video", src, {"crop": _crop_opt(block)})
    box = _embed_box({"type": "custom", "config": config, "children": []},
                     avail_w, box_h, block.get("ratio"), theme.image_corner_radius, debug)
    return _with_caption(box, block, theme, debug, avail_h)


def render_rc_embed(block: dict, theme: Theme, debug: bool,
                    avail_w: float, avail_h: float) -> list[dict]:
    """A prebuilt binary ``.rc`` embedded live as a native custom component (op 93). The
    player loads it into a nested document and paints it — fit, aspect-preserved — into the
    box. ``[embed] fit`` chooses fit/fill/native; an optional ``crop`` (source fractions
    ``l,t,r,b``) shows only that region of the sub-document. A ``title`` option draws a
    centred caption below the embed."""
    import os
    src = block.get("src") or os.path.basename(block["path"])
    _, _, cap_h = _caption_metrics(block, theme)
    box_h = avail_h - cap_h
    fit = block.get("fit") or getattr(theme, "embed_fit", "fit")   # per-include > global
    opts = {"fit": fit if fit and fit != "fit" else "", "crop": _crop_opt(block)}
    for k in ("persist", "step", "stepid", "timeid"):      # slide-driven documents, see deck.py
        if block.get(k): opts[k] = block[k]
    config = _media_config("rc", src, opts)
    box = _embed_box({"type": "custom", "config": config, "children": []},
                     avail_w, box_h, block.get("ratio"), theme.image_corner_radius, debug)
    return _with_caption(box, block, theme, debug, avail_h)


# A staggered embed fades in over this window (seconds) on the step that reveals it.
STAGGER_FADE_EXPR = "min(1.0, max(0.0, (animTime - 0.05) / 0.4))"


def _apply_reveal(nodes: list, block: dict) -> list:
    """Gate an embed for a `stagger` step (see ``expand_embed_stagger``). ``hidden`` → replace
    the embed with an empty box of the same footprint: nothing is drawn (custom hosts like the
    video host ignore ``alpha=0``) yet the layout is preserved so revealed embeds don't shift.
    ``fade`` → animate the embed in on load. ``shown``/absent → unchanged."""
    state = block.get("_reveal")
    if not state or state == "shown" or not nodes:
        return nodes
    if state == "hidden":
        size = [m for m in nodes[0].get("modifiers", [])
                if m == "fillMaxWidth" or (isinstance(m, dict) and ("height" in m or "width" in m))]
        return [{"type": "box", "modifiers": size, "children": []}]
    head = dict(nodes[0])
    head["modifiers"] = list(head.get("modifiers", [])) + \
        [{"graphicsLayer": {"alpha": STAGGER_FADE_EXPR}}]
    return [head, *nodes[1:]]


def render_heading(block: dict, body_size: float, theme: Theme, debug: bool,
                   avail_w: float, counter: list, align: str = "start") -> list[dict]:
    """Render a subheading/section heading block (level 1..6), applying its theme config
    and optional shader/background document."""
    from dataclasses import replace as _replace
    level = int(block.get("level", 2))
    hcfg = dict(theme.heading_config(level, "content"))
    base_body = float(theme.fonts.get("content_body", 40.0))
    scale = (body_size / base_body) if base_body > 0 else 1.0
    if scale < 0.99:
        hcfg["font_size"] = round(hcfg["font_size"] * scale, 2)
        hcfg["gap"] = round(hcfg["gap"] * scale, 2)
        hcfg["pad_bottom"] = round(hcfg["pad_bottom"] * scale, 2)
        hcfg["pad_top"] = round(hcfg["pad_top"] * scale, 2)
    raw_text = block.get("text", "").replace("<br>", "\n").replace("<br/>", "\n")
    if hcfg["has_bg"]:
        node, _ = _heading_bg_box(raw_text, level, hcfg, avail_w, theme, debug, align)
    else:
        txt_theme = _replace(
            theme,
            body_font=hcfg["family"] or theme.title_font or theme.body_font,
            body_weight=hcfg["weight"] or theme.title_weight or theme.body_weight,
            body_color=hcfg["color"],
        )
        node = _styled(raw_text, hcfg["font_size"], hcfg["color"],
                       txt_theme, debug, align)
    out = [node]
    if hcfg.get("pad_top", 0.0) > 0:
        out.insert(0, vspacer(hcfg["pad_top"]))
    if hcfg["gap"] > 0:
        out.append(vspacer(hcfg["gap"]))
    return out


def render_block(block: dict, body_size: float, theme: Theme, debug: bool,
                 avail_w: float, avail_h: float, counter: list,
                 same_ctx: dict | None = None, align: str = "start") -> list[dict]:
    kind = block["kind"]

    # `:: same`: graph that changed → morph in place; else fall through to static.
    if kind == "graph" and same_ctx and same_ctx.get("graph_changed"):
        return render_graph_morph(same_ctx["graph_prev"], block, theme, debug,
                                  avail_w, avail_h, SAME_VAR)

    if kind == "heading":
        out = render_heading(block, body_size, theme, debug, avail_w, counter, align)
    elif kind == "text":
        lines = block["text"].replace("<br>", "\n").replace("<br/>", "\n").split("\n")
        out = [(vspacer(round(body_size * 0.7, 1)) if not line.strip()
                else _styled(line, body_size, theme.body_color, theme, debug, align))
               for line in lines]
    elif kind == "subtitle":
        out = [_styled(block["text"], theme.fonts["subtitle"], theme.accent, theme, debug, align)]
    elif kind == "table":
        out = render_table(block["rows"], theme, debug)
    elif kind == "bullets":
        # One row per bullet: a drawn shape marker + the (wrapping) text. For `:: same`,
        # appearing bullets fade in and disappearing ones collapse out in their old spot.
        display = (_bullet_display(block["items"], same_ctx) if same_ctx
                   else [(it, "static") for it in block["items"]])
        out = []
        for item, state in display:
            comp = _bullet_row(item, body_size, theme, debug, counter)
            if state == "enter":
                comp = _apply_enter(comp, theme)
            elif state == "exit":
                comp = _apply_exit(comp, theme, body_size * 1.5)
            out.append(comp)
        return out
    elif kind == "code":
        out = render_code(block, theme, debug, avail_w=avail_w, avail_h=avail_h)
    elif kind == "image":
        _, _, cap_h = _caption_metrics(block, theme)
        out = _with_caption(render_image(block, theme, debug, avail_w, avail_h - cap_h, counter, align=align),
                            block, theme, debug, avail_h)
    elif kind == "graph":
        out = render_graph(block, theme, debug, avail_w, avail_h, counter)
    elif kind == "chart":
        out = render_chart(block, theme, debug, avail_w, avail_h, counter)
    elif kind == "weblink":
        out = render_weblink(block, theme, debug, avail_w, avail_h)
    elif kind == "video":
        out = render_video(block, theme, debug, avail_w, avail_h)
    elif kind == "outline":
        from .measure import _outline_size
        out = render_outline(block, theme, debug, _outline_size(theme, body_size))
    else:
        out = None

    if out is not None:
        # A whole non-bullet block that only appears on the current slide animates in.
        if same_ctx and same_ctx["key"](block) in same_ctx["blocks_new"]:
            out = [_apply_enter(c, theme) for c in out]
        return _apply_reveal(out, block)

    if kind == "json_include":
        return _apply_reveal(_clipped_splice(block["path"], theme, debug, avail_h, block), block)

    if kind == "rc_include":
        # Prefer splicing the source JSON (a flat document, no host needed); otherwise embed
        # the prebuilt .rc live as a nested document via the rc-document host. A ``ratio`` frames
        # the embed in a fixed-aspect box, which needs the live custom-component path.
        if block.get("json") and not block.get("ratio"):
            return _apply_reveal(_clipped_splice(block["json"], theme, debug, avail_h, block), block)
        return _apply_reveal(render_rc_embed(block, theme, debug, avail_w, avail_h), block)

    if kind == "missing":
        return [text(f"<{block['name']} missing>", body_size, theme.body_color, debug)]

    return []


def _split_gap(slide: dict) -> float:
    meta = slide.get("meta") or {}
    overrides = meta.get("overrides") or {}
    for k in ("pane_gap", "gap"):
        if k in overrides:
            try:
                return float(overrides[k])
            except (TypeError, ValueError):
                pass
    return float(PANE_GAP)


def _split_geometry(slide: dict, theme: Theme, width: int, height: int) -> tuple:
    """The split layout's key measurements — (left_w, right_w, content_h) — shared by the
    renderer and ``split_left_metrics`` so overflow is measured against the real column."""
    spec = theme.slide_type_spec("split", SLIDE_TYPES["split"])
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    content_w = width - pad_l - pad_r
    content_h = height - pad_t - pad_b - _chrome_reserve(theme, "split", pad_b)
    ratio = (slide.get("meta") or {}).get("ratio")
    if not ratio or len(ratio) != 2:
        ratio = [1, 1]
    avail = content_w - _split_gap(slide)
    left_w = round(avail * ratio[0] / sum(ratio), 2)
    right_w = round(avail * ratio[1] / sum(ratio), 2)
    return left_w, right_w, content_h


def split_left_metrics(slide: dict, theme: Theme, width: int, height: int) -> tuple:
    """(left column width, available height below the title) for a `:: split` slide — the
    area its first column scrolls within. Used by the scroll-expansion pass."""
    left_w, _, content_h = _split_geometry(slide, theme, width, height)
    _, title_h = _title_group(slide, "split", theme.title_size("split"), left_w, theme, False, False)
    return left_w, content_h - title_h


def _build_split_root(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                      index: int, debug: bool, counter: list, same_ctx: dict | None,
                      bg: str, do_stagger: bool, scroll: dict | None = None) -> dict:
    """``split`` layout: two side-by-side columns from `+++`. The **right** column runs the
    full content height (from the top, above where the title sits), while the **left** column
    holds the title — sized only to the left column's width — with its content beneath. The
    last pane is the full-height right column; everything before it stacks in the left column.
    Widths come from the slide's `[ratio]` (default 1:1). ``scroll`` (a ``scroll_spec``) clips
    and scrolls the **left** column's content — for a split slide with `scroll = N`/`auto`, so
    the overflowing text column pages while the right column stays put."""
    spec = theme.slide_type_spec("split", SLIDE_TYPES["split"])
    body_size = theme.body_size("split")
    title_size = theme.title_size("split")

    panes = split_panes(blocks)
    right_blocks = panes[-1]
    left_blocks = [b for pane in panes[:-1] for b in pane]

    left_w, right_w, content_h = _split_geometry(slide, theme, width, height)

    # Left column: title (constrained to left_w) then its content beneath.
    title_group, title_h = _title_group(slide, "split", title_size, left_w, theme, False, debug)
    left_avail = content_h - title_h
    # When scrolling, the left content is full-size and clipped to a moving window (no autosize
    # or stagger — the scroll is the entrance); otherwise it autosizes to fit.
    left_size = (body_size if scroll else
                 _autosize_body(left_blocks, theme, left_w, left_avail, body_size, same_ctx))
    left_body: list = []
    for i, block in enumerate(left_blocks):
        if i > 0 and left_blocks[i - 1].get("kind") == "text" and block.get("kind") == "text":
            left_body.append(vspacer(round(left_size * 0.7, 1)))
        left_body.extend(render_block(block, left_size, theme, debug, left_w,
                                      left_avail, counter, same_ctx))
    if scroll:
        left_content = [_scroll_viewport(left_body, left_avail, scroll["y"], debug)]
    else:
        left_content = _stagger(left_body, theme) if do_stagger else left_body
    left_children = list(title_group) + left_content
    left_col = {"type": "column", "modifiers": dbg([{"width": left_w}], debug),
                "children": left_children}
    # The left column is a fixed-width pane, so an `align=` on the slide has to be applied
    # here: the title's own wrapper column sizes to its content and cannot centre within
    # the pane by itself. Only set it when the slide asks, so plain splits stay start-aligned.
    h_align = getattr(theme, "h_align", None)
    if h_align in ("center", "end"):
        left_col["horizontalAlignment"] = h_align

    # Right column: full-height content, starting at the top (level with the title).
    right_size = _autosize_body(right_blocks, theme, right_w, content_h, body_size, same_ctx)
    right_body: list = []
    for block in right_blocks:
        right_body.extend(render_block(block, right_size, theme, debug, right_w,
                                       content_h, counter, same_ctx))
    v_arr = "top" if spec.get("v_align") == "top" else "center"
    right_col = {"type": "column",
                 "modifiers": dbg([{"width": right_w}, "fillMaxHeight"], debug),
                 "verticalArrangement": v_arr,
                 "children": _stagger(right_body, theme) if do_stagger else right_body}

    gap = _split_gap(slide)
    row = {"type": "row", "verticalAlignment": "top",
           "modifiers": dbg(["fillMaxSize"], debug),
           "children": [left_col, {"type": "box", "modifiers": [{"width": float(gap)}],
                                   "children": []}, right_col]}
    return frame_slide([row], spec, theme, "split", width, height, debug, bg)


def _autosize_body(blocks: list[dict], theme: Theme, width: float, avail_h: float,
                   base_size: float, same_ctx: dict | None = None) -> float:
    """Shrink-only autosize: the body size at which ``blocks`` fit ``avail_h``, or the base
    size unchanged when autosizing is off or the content already fits. A stepped-reveal diff
    (bullets appearing across steps) disables it so matched content keeps one size step-to-step;
    an explicit `:: same` (``autosize_ok``) keeps it on so the slide matches the base it
    continues (which autosized) instead of overflowing."""
    if not getattr(theme, "autosize", True):
        return base_size
    if same_ctx is not None and not same_ctx.get("autosize_ok"):
        return base_size
    return fit_body_size(blocks, base_size, theme, width, avail_h,
                         min_scale=getattr(theme, "autosize_min", 0.5))


def content_metrics(slide: dict, theme: Theme, width: int, height: int) -> tuple:
    """The single-column content region's (width, available height, title height) for a
    slide — the same geometry ``build_slide_root`` uses. Shared with the scroll-expansion
    pass so it measures overflow against the exact area the renderer will lay out into."""
    stype = slide_type(slide)
    spec = theme.slide_type_spec(stype, SLIDE_TYPES[stype])
    if getattr(theme, "h_align", None):
        spec["h_align"] = theme.h_align
    if getattr(theme, "v_align", None):
        spec["v_align"] = theme.v_align
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    content_w = width - pad_l - pad_r
    centered = spec.get("h_align") == "center" and spec.get("v_align") == "center"
    _, title_h = _title_group(slide, stype, theme.title_size(stype), content_w,
                              theme, centered, False)
    avail_h = height - pad_t - pad_b - title_h - _chrome_reserve(theme, stype, pad_b)
    return content_w, avail_h, title_h


def _scroll_y(prev_off: float, cur_off: float):
    """The inner-column y translation for a scroll step: a static ``-offset`` when there's no
    change, else an expression animating from ``-prev_off`` to ``-cur_off`` over the load
    progress ($__st). Negative moves content up (scrolls down)."""
    delta = round(cur_off - prev_off, 2)
    if not delta:
        return -round(prev_off, 2)
    return f"-({round(prev_off, 2)} + ({delta}) * {SAME_VAR})"


def scroll_spec(prev_off: float, cur_off: float, viewport: float) -> dict:
    """A ``scroll`` argument for ``build_slide_root`` — the clip viewport plus the animated
    y translation from ``prev_off`` to ``cur_off``. Shared by ``scroll = N`` pages
    (``build_scroll_doc``) and scroll-aware `:: same` (``build_same_doc``)."""
    return {"viewport": round(float(viewport), 2), "y": _scroll_y(prev_off, cur_off)}


def _jagged_bg_canvas(jag: dict, viewport: float, debug: bool) -> dict:
    """A fixed, viewport-sized canvas that fills the code panel background as a shape whose cut
    edges (``top``/``bottom``) are torn into zigzag teeth pointing *outward* — beyond the text
    clip, into the margin — so the teeth never eat into the text. The canvas doesn't clip its
    own drawing, so the outward teeth render even though it's the size of the viewport; it must
    sit outside the viewport's rectangular clip (see _scroll_viewport). The slide background
    shows through the gaps between teeth."""
    w = float(jag["width"])
    h = round(float(viewport), 2)
    cmds = torn_fill_commands("czz", w, h, bool(jag.get("top")), bool(jag.get("bottom")),
                              float(jag.get("amp", 12.0)), float(jag.get("tooth", 32.0)),
                              jag["color"], outward=True)
    return {"type": "canvas",
            "modifiers": dbg([{"width": round(w, 2)}, {"height": h}], debug),
            "commands": cmds}


def _scroll_viewport(content: list, viewport: float, y, debug: bool,
                     jag: dict | None = None) -> dict:
    """Wrap a slide's content nodes in a fixed-height, clipped viewport whose inner column is
    translated up by ``y`` (a number for a static page, or an expression string to animate the
    scroll). Content taller than ``viewport`` is clipped, so only the current scroll window
    shows — the mechanism behind both ``scroll = N`` pages and scroll-aware `:: same``.

    ``jag`` (a dict with width/color/top/bottom) draws a fixed torn zigzag panel background
    whose teeth extend *outside* the text clip, so the cut edges look ripped from the deck."""
    inner = {"type": "column",
             "modifiers": dbg(["fillMaxWidth", {"offset": {"x": 0.0, "y": y}}], debug),
             "children": content}
    vp = round(float(viewport), 2)
    viewport_box = {"type": "box",
                    "modifiers": dbg(["fillMaxWidth", {"height": vp}, {"clip": 0.0}], debug),
                    "children": [inner]}
    if not jag:
        return viewport_box
    # The torn background sits behind the rect-clipped text, in a parent that does NOT clip, so
    # its outward teeth spill into the margin instead of being cut off.
    return {"type": "box",
            "modifiers": dbg(["fillMaxWidth", {"height": vp}], debug),
            "children": [_jagged_bg_canvas(jag, viewport, debug), viewport_box]}


# ── Stacked layout sections (``===``) ─────────────────────────────────────────
_MEDIA_KINDS = {"image", "rc_include", "json_include", "video", "weblink", "graph",
                "chart", "include", "missing"}


def _section_is_media(section: dict) -> bool:
    """A section is 'media' (fills leftover height) if it has ``+++`` panes or any media block;
    otherwise it's 'text' (title/bullets/paragraphs) and takes only its natural height."""
    blocks = section["blocks"]
    return (any(b.get("kind") == "pane_break" for b in blocks)
            or any(b.get("kind") in _MEDIA_KINDS for b in blocks))


def _section_type(section: dict) -> str:
    """A section's layout type: its own ``:: <type>`` when it names a known one, else content."""
    t = (section["meta"] or {}).get("type") if section["meta"] else None
    return t if t in SLIDE_TYPES else "content"


def _section_overrides(section: dict) -> dict:
    """The ``key=value`` words on a section's own ``::`` line."""
    meta = section.get("meta") or {}
    return (meta.get("overrides") or {}) if meta else {}


def _section_num(section: dict, key: str, default: float | None = None) -> float | None:
    """One numeric section override, or ``default`` when it is absent or unreadable."""
    raw = _section_overrides(section).get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _section_natural_h(section: dict, theme: Theme, stype: str, width: float) -> float:
    """Estimated stacked height of a text section: its title plus content height (the tallest
    pane for a ``+++`` section). ``height=`` on the section's ``::`` line overrides the
    estimate outright — a band of a known height, which is how a traced slide is written."""
    fixed = _section_num(section, "height")
    if fixed is not None:
        return fixed
    from .measure import content_height
    _, title_h = _title_group(section, stype, theme.title_size(stype), width, theme, False, False)
    bsize = theme.body_size(stype)
    panes = split_panes(section["blocks"])
    ch = (content_height(panes[0] if panes else [], bsize, theme, width) if len(panes) <= 1
          else max((content_height(p, bsize, theme, width) for p in panes), default=0.0))
    return title_h + ch + (_section_num(section, "pad_top", 0.0) or 0.0)


def _section_nodes(section: dict, theme: Theme, stype: str, width: float, avail_h: float,
                   debug: bool, counter: list, same_ctx: dict | None, do_stagger: bool,
                   align: str = "start") -> list:
    """Nodes for one stacked layout section — its title (if any) then content, as a single
    column or ``+++`` side-by-side panes, laid out within (width, avail_h).

    A section may carry its own geometry on its ``::`` line: ``pad_left``/``pad_right`` inset
    it, ``pad_top`` drops its content, ``pane_gap`` sets the space between its ``+++``
    columns and ``align`` overrides the slide's. Given those, the pane widths are exact —
    ``[a:b:c]`` divides what is left after the gaps — which is what makes it possible to land
    columns on the same x as a source deck. A section that names none of them keeps the
    original behaviour."""
    body_size = theme.body_size(stype)
    ov = _section_overrides(section)
    align = str(ov.get("align", ov.get("h_align", align)))
    if align == "left":
        align = "start"
    elif align == "right":
        align = "end"
    pad_l = _section_num(section, "pad_left", 0.0)
    pad_r = _section_num(section, "pad_right", 0.0)
    pad_t = _section_num(section, "pad_top", 0.0)
    width = max(1.0, width - pad_l - pad_r)
    tgroup, title_h = _title_group(section, stype, theme.title_size(stype), width, theme,
                                   align == "center", debug)
    inner_h = max(1.0, avail_h - title_h - pad_t)
    panes = split_panes(section["blocks"])
    nodes = list(tgroup)
    if pad_t:
        nodes.insert(0, vspacer(pad_t))
    if len(panes) <= 1:
        pane_blocks = panes[0] if panes else []
        bsize = _autosize_body(pane_blocks, theme, width, inner_h, body_size, same_ctx)
        content: list = []
        for block in pane_blocks:
            content.extend(render_block(block, bsize, theme, debug, width, inner_h, counter,
                                        same_ctx, align=align))
        nodes.extend(_stagger(content, theme) if do_stagger else content)
    else:
        n = len(panes)
        ratio = (section["meta"] or {}).get("ratio") if section["meta"] else None
        if not ratio or len(ratio) != n:
            ratio = [1] * n
        total = sum(ratio)
        exact = "pane_gap" in ov
        gap = _section_num(section, "pane_gap", PANE_GAP)
        avail_w = width - gap * (n - 1) if exact else width
        pane_nodes = []
        for i, pane_blocks in enumerate(panes):
            pane_w = avail_w * ratio[i] / total
            inner_w = pane_w if exact else pane_w - PANE_GAP
            pane_h = inner_h if exact else inner_h - PANE_GAP
            bsize = _autosize_body(pane_blocks, theme, inner_w, pane_h, body_size, same_ctx)
            pane_children = []
            for block in pane_blocks:
                pane_children.extend(render_block(block, bsize, theme, debug, inner_w,
                                                  pane_h, counter, same_ctx, align=align))
            mods: list = [{"width": round(pane_w, 2)}]
            if not exact:
                mods.append({"padding": float(PANE_GAP / 2)})
            if exact and i:
                pane_nodes.append({"type": "box", "modifiers": dbg([{"width": round(gap, 2)}], debug),
                                   "children": []})
            col = {"type": "column", "modifiers": dbg(mods, debug), "children": pane_children}
            if align in ("center", "end"):
                col["horizontalAlignment"] = align
            pane_nodes.append(col)
        nodes.append({"type": "row", "modifiers": dbg(["fillMaxWidth"], debug),
                      "children": pane_nodes})
    if pad_l or pad_r:
        wrap = {"type": "column",
                "modifiers": dbg(["fillMaxWidth", {"padding": [pad_l, 0.0, pad_r, 0.0]}], debug),
                "children": nodes}
        if align in ("center", "end"):
            wrap["horizontalAlignment"] = align
        nodes = [wrap]
    return nodes


def _build_sectioned_root(slide: dict, theme: Theme, width: int, height: int, index: int,
                          debug: bool, counter: list, same_ctx: dict | None, bg: str,
                          do_stagger: bool) -> dict:
    """A slide split by ``===`` into stacked layout sections. Text sections take their natural
    height; media sections (``+++`` panes / images / embeds) share the leftover height via a
    layout weight, so e.g. a couple of links sit above two full-height image columns.

    A section that names its own ``height=`` is neither: it is a band of exactly that height,
    which is how a slide traced off a source deck pins its rows to known y coordinates."""
    sections = slide["sections"]
    stype = slide_type(slide)
    spec = theme.slide_type_spec(stype, SLIDE_TYPES[stype])
    if getattr(theme, "h_align", None):
        spec["h_align"] = theme.h_align
    if getattr(theme, "v_align", None):
        spec["v_align"] = theme.v_align
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    content_w = width - pad_l - pad_r
    gap = round(theme.title_gap, 2)
    avail = height - pad_t - pad_b - _chrome_reserve(theme, stype, pad_b) - gap * max(0, len(sections) - 1)

    fixed = [_section_num(s, "height") for s in sections]
    media = [_section_is_media(s) and f is None for s, f in zip(sections, fixed)]
    stypes = [_section_type(s) for s in sections]
    text_h = sum(_section_natural_h(s, theme, st, content_w)
                 for s, st, m in zip(sections, stypes, media) if not m)
    nmedia = sum(media)
    media_share = max(1.0, (avail - text_h) / nmedia) if nmedia else 0.0

    children: list = []
    for k, sec in enumerate(sections):
        sec_h = media_share if media[k] else _section_natural_h(sec, theme, stypes[k], content_w)
        nodes = _section_nodes(sec, theme, stypes[k], content_w, sec_h, debug, counter,
                               same_ctx, do_stagger, align=spec.get("h_align", "start"))
        if fixed[k] is not None:
            mods = [{"height": round(fixed[k], 2)}, "fillMaxWidth"]
        else:
            mods = ([{"weight": 1.0}, "fillMaxWidth"] if media[k] else ["fillMaxWidth"])
        band = {"type": "column", "modifiers": dbg(mods, debug), "children": nodes}
        if spec.get("h_align") in ("center", "end"):
            band["horizontalAlignment"] = spec["h_align"]
        children.append(band)
        if k < len(sections) - 1:
            children.append(vspacer(gap))
    return frame_slide(children, spec, theme, stype, width, height, debug, bg)


def build_slide_root(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                     index: int, debug: bool, counter: list, same_ctx: dict | None = None,
                     bg: str = "default", animate: bool | None = None,
                     scroll: dict | None = None) -> dict:
    """Build the root Column for one slide (no header wrapper). ``bg="none"`` omits the
    per-slide background (see ``frame_slide``). ``animate`` forces the staggered content
    reveal on/off; None → the theme default. It is off for the *outgoing* slide of a
    transition (that content already appeared) and when a `:: same` diff is animating.
    ``scroll`` ({"viewport": h, "y": <px|expr>}) clips the single-column content to a scroll
    window translated by ``y`` — full-size (autosize and stagger are suppressed)."""
    # Stagger content in when the theme asks for it (or the caller forces it), except on the
    # outgoing transition slide or when `:: same` is already animating the diff.
    do_stagger = (theme.content_reveal == "stagger" if animate is None else animate) \
        and same_ctx is None
    # ``===`` splits a slide into stacked layout sections (each its own type/title/content).
    if slide.get("sections") and not scroll:
        return _build_sectioned_root(slide, theme, width, height, index, debug, counter,
                                     same_ctx, bg, do_stagger)
    stype = slide_type(slide)
    spec = theme.slide_type_spec(stype, SLIDE_TYPES[stype])
    if getattr(theme, "h_align", None):
        spec["h_align"] = theme.h_align
    if getattr(theme, "v_align", None):
        spec["v_align"] = theme.v_align
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    title_size = theme.title_size(stype)
    body_size = theme.body_size(stype)
    content_w = width - pad_l - pad_r
    centered = spec.get("h_align") == "center" and spec.get("v_align") == "center"

    # ``split``: row-first two-column layout (see _build_split_root). With two `+++` panes
    # the last is the full-height right column and the rest stack in the left column; with a
    # single pane (no `+++`) that lone content still goes in the tall right column and the
    # left column holds just the title. Dispatch on *any* pane having content (not just the
    # last), so a split whose right pane is still empty — e.g. the base of a `:: same` reveal —
    # lays out the same way as the follow-up that fills it, rather than falling back to content.
    if stype == "split" and any(split_panes(blocks)):
        return _build_split_root(slide, blocks, theme, width, height, index, debug,
                                 counter, same_ctx, bg, do_stagger, scroll)

    # Title, followed by a configurable vertical gap before the content. ``max`` slides
    # use a tighter gap so the maximised content keeps more room.
    title_group, title_h = _title_group(slide, stype, title_size, content_w,
                                        theme, centered, debug)
    # Keep content clear of the bottom chrome. It only matters when the slide's margin is
    # smaller than the chrome band (e.g. a `max` slide) — a native overlay like a webview
    # would otherwise cover it. Normal slides' larger margins already clear it.
    avail_h = height - pad_t - pad_b - title_h - _chrome_reserve(theme, stype, pad_b)

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
            content: list = []
            for block in rest:
                content.extend(render_block(block, body_size, theme, debug, content_w, avail_h, counter, same_ctx, align="center"))
            children.extend(_stagger(content, theme) if do_stagger else content)
        else:
            children.extend(title_group)
            content = []
            # A scroll page shows full-size content clipped to a moving window: no autosize
            # (that's the alternative to scrolling) and no per-item stagger (the scroll itself
            # is the entrance).
            bsize = (body_size if scroll else
                     _autosize_body(pane_blocks, theme, content_w, avail_h, body_size, same_ctx))
            # Torn zigzag edges on a scrolled code panel: draw the panel background as a fixed
            # jagged shape at the viewport with the code scrolling transparently over it, so the
            # cut edges (top when there's content above, bottom when there's more below) look
            # ripped from the rest of the deck.
            jag = None
            if scroll and getattr(theme, "code_jagged_scroll", True) \
                    and len(pane_blocks) == 1 and pane_blocks[0].get("kind") == "code":
                sp = (slide.get("meta") or {}).get("scroll_page") or {}
                idx, cnt = sp.get("index", 0), sp.get("count", 1)
                jag = {"top": idx > 0, "bottom": idx < cnt - 1, "width": content_w,
                       "color": theme.code_background,
                       "amp": float(getattr(theme, "code_jagged_amp", 12.0)),
                       "tooth": float(getattr(theme, "code_jagged_tooth", 32.0))}
                content = render_code(pane_blocks[0], theme, debug, panel_bg=False)
            else:
                for block in pane_blocks:
                    content.extend(render_block(block, bsize, theme, debug, content_w, avail_h, counter, same_ctx,
                                                align=spec.get("h_align", "start")))
            if scroll:
                children.append(_scroll_viewport(content, scroll["viewport"], scroll["y"], debug, jag))
            else:
                children.extend(_stagger(content, theme) if do_stagger else content)
    else:
        children.extend(title_group)
        n = len(panes)
        ratio = (slide.get("meta") or {}).get("ratio")
        if not ratio or len(ratio) != n:
            ratio = [1] * n
        total = sum(ratio)
        # The panes should span the full content width; the inter-pane gaps come from each
        # column's own PANE_GAP/2 padding (PANE_GAP between neighbours, PANE_GAP/2 inset at
        # the edges). Don't also subtract the gaps from the width or the columns fall short
        # of the content area (leaving dead space on the right of a start-aligned row).
        avail = content_w
        pane_nodes = []
        for i, pane_blocks in enumerate(panes):
            pane_w = avail * ratio[i] / total
            inner_w = pane_w - PANE_GAP
            inner_h = avail_h - PANE_GAP
            pane_children = []
            bsize = _autosize_body(pane_blocks, theme, inner_w, inner_h, body_size, same_ctx)
            for block in pane_blocks:
                pane_children.extend(render_block(block, bsize, theme, debug, inner_w, inner_h, counter, same_ctx))
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

    return frame_slide(children, spec, theme, slide_type(slide), width, height, debug, bg)


def frame_slide(children: list, spec: dict, theme: Theme, stype: str,
                width: int, height: int, debug: bool, bg: str = "default") -> dict:
    """Wrap slide children in the root column, layering a shader or custom background inclusion
    behind (in a Box) when the slide type has one, else a solid background. ``bg="none"`` omits
    the background entirely (transparent) — used by push transitions that draw a single
    shared background behind both sliding slides instead of one per slide."""
    shader = None if bg == "none" else theme.shader_for(stype)
    bg_doc = None if bg == "none" else theme.bg_doc_for(stype)
    bg_mods = [] if (shader or bg_doc or bg == "none") else [{"background": theme.background}]
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    pad_mod = ({"padding": float(pad_l)} if pad_l == pad_t == pad_r == pad_b
               else {"padding": [pad_l, pad_t, pad_r, pad_b]})
    col = {
        "type": "column",
        "horizontalAlignment": spec["h_align"],
        "verticalAlignment": spec["v_align"],
        "modifiers": dbg(["fillMaxSize", *bg_mods, pad_mod], debug),
        "children": children,
    }
    if shader or bg_doc:
        bg_layers = []
        if shader:
            bg_layers.append(shader_canvas(shader, width, height))
        if bg_doc:
            bg_layers.extend(_render_bg_asset(bg_doc, theme, width, height, debug))
        root_mods: list = ["fillMaxSize"]
        if not shader and bg != "none":
            root_mods.append({"background": theme.background})
        return {
            "type": "box",
            "modifiers": dbg(root_mods, debug),
            "children": [*bg_layers, col],
        }
    return col


def render_outline(block: dict, theme: Theme, debug: bool, size: float | None = None) -> list[dict]:
    """A synthesized deck outline: one row per numbered section, the number in the deck's
    primary colour, the section title beside it. Built from the sections collected in
    ``apply_agenda`` (an ``:: outline`` slide). ``size`` (from autosize) overrides the heading
    size so a long outline shrinks to fit."""
    items = block.get("items", [])
    size = float(theme.fonts.get("heading", 44.0)) if size is None else float(size)
    gap = round(size * 0.55, 1)
    # One node per section — returned as a flat list (not wrapped in a column) so the slide's
    # content-reveal staggers each item in turn instead of fading the whole outline at once.
    # The inter-item gap rides on each row's top padding.
    rows: list[dict] = []
    for i, it in enumerate(items):
        num = text(f"{it['num']}.", round(size * 1.05, 1), theme.primary, debug,
                   family=theme.title_font, weight=theme.title_weight)
        ttl = text(str(it["title"]), size, theme.body_color, debug,
                   family=theme.body_font, weight=theme.body_weight)
        mods: list = ["fillMaxWidth"]
        if i:
            mods = [{"padding": [0.0, gap, 0.0, 0.0]}, "fillMaxWidth"]
        rows.append({
            "type": "row", "verticalAlignment": "center",
            "modifiers": dbg(mods, debug),
            "children": [num, {"type": "box", "modifiers": [{"width": round(size * 0.6, 1)}],
                               "children": []}, ttl],
        })
    return rows


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


def _progress_bar_canvas(theme: Theme, index: int, total: int, width: int, debug: bool) -> dict:
    """The bottom progress bar as a single canvas: a thin connecting line coloured by the
    *speaker* at each point (bright up to the current slide, faint beyond), with the section
    marks sitting **on** the line — the line leaving a gap around each mark so it reads as a
    connect-the-dots rail rather than a bar with floating marks."""
    cr = 6.0                                   # mark radius
    line_h = 3.0                               # connecting-line thickness
    canvas_h = round(2 * cr + 8.0, 2)          # a little vertical breathing room
    cy = round(canvas_h / 2, 2)
    fx = (index + 1) / total * width           # progress: line is "filled" up to here
    track = theme.table_bg                     # faint colour for the not-yet-reached line

    # Colour: "section" mode follows who's speaking (spans that change at include boundaries,
    # not only at `:: section` marks); "current" mode paints the whole line in the current
    # slide's accent.
    by_section = getattr(theme, "chrome_progress_color", "current") == "section"
    spans = getattr(theme, "chrome_speaker_spans", None) or []
    if by_section and spans:
        span_px = [(sp["start"] / total * width, sp["end"] / total * width, sp["color"]) for sp in spans]
    else:
        span_px = [(0.0, float(width), theme.accent)]

    def color_at(x):
        for x0, x1, c in span_px:
            if x0 <= x < x1:
                return c
        return span_px[-1][2]

    # Mark positions: at each *speaker change* (default — the dots then delimit the coloured
    # segments) or at each `:: section` start (``mark_at = section``).
    marks = []
    if getattr(theme, "chrome_progress_marks", False):
        if getattr(theme, "progress_mark_at", "speaker") == "section":
            starts = [sec["start"] for sec in (getattr(theme, "chrome_sections", None) or [])]
        else:
            # Speaker changes = each span start after the first (the deck start isn't a change).
            starts = [sp["start"] for sp in (getattr(theme, "chrome_speaker_spans", None) or [])[1:]]
        for s in starts:
            marks.append(max(cr, min(s / total * width, width - cr)))
    half_gap = cr + 4.0
    gaps = [(mx - half_gap, mx + half_gap) for mx in marks]

    def in_gap(x):
        return any(a <= x <= b for a, b in gaps)

    # Cut the line wherever its colour or fill-state can change, then draw each non-gap piece.
    cuts = {0.0, float(width), fx}
    for x0, x1, _ in span_px:
        cuts.update((x0, x1))
    for a, b in gaps:
        cuts.update((a, b))
    cuts = sorted(c for c in cuts if 0.0 <= c <= width)

    cmds = []
    top, bot = round(cy - line_h / 2, 2), round(cy + line_h / 2, 2)
    for i in range(len(cuts) - 1):
        x0, x1 = cuts[i], cuts[i + 1]
        if x1 - x0 < 0.5 or in_gap((x0 + x1) / 2):
            continue
        col = color_at((x0 + x1) / 2) if (x0 + x1) / 2 < fx else track
        cmds.append({"type": "paint", "ops": [{"color": col}, {"style": "fill"}]})
        cmds.append({"type": "drawrect", "left": round(x0, 2), "top": top,
                     "right": round(x1, 2), "bottom": bot})

    # Marks on the line, always in the speaker colour at that point — so the whole rail (and
    # who speaks where) stays legible; the line's fill alone shows how far we are.
    shape = getattr(theme, "progress_mark_shape", "circle")
    filled = getattr(theme, "progress_mark_filled", True)
    for i, mx in enumerate(marks):
        cmds += marker_commands(shape, round(mx, 2), cy, cr, color_at(mx), filled, uid=f"pm{i}")

    return {"type": "canvas",
            "modifiers": dbg(["fillMaxWidth", {"height": canvas_h}], debug), "commands": cmds}


def _chrome_overlay(theme: Theme, index: int, total: int, width: int, height: int, debug: bool):
    """A bottom overlay: footer (left), page number (right), progress bar (very bottom).
    Returns None if no chrome is enabled."""
    author = getattr(theme, "slide_author", "")
    if not (theme.chrome_page or theme.chrome_footer or theme.chrome_progress or author):
        return None
    # Full-opacity theme colours; the whole overlay is made translucent by chrome_alpha
    # (a graphicsLayer), so chrome reads as a soft glassy tint rather than a flat grey.
    text_col = theme.body_color
    rows = []

    if theme.chrome_footer or theme.chrome_page or author:
        line = []
        if theme.chrome_footer:
            line.append({"type": "text", "value": theme.chrome_footer, "fontSize": 24.0,
                         "color": text_col})
        line.append({"type": "spacer", "modifiers": [{"weight": 1.0}]})
        # The attributed author (@name), tinted in their own accent colour.
        if author:
            line.append({"type": "text", "value": author, "fontSize": 24.0,
                         "color": theme.accent})
            if theme.chrome_page and total:
                line.append({"type": "text", "value": "   ", "fontSize": 24.0, "color": text_col})
        if theme.chrome_page and total:
            line.append({"type": "text", "value": f"{index + 1} / {total}", "fontSize": 24.0,
                         "color": text_col})
        rows.append({"type": "row",
                     "modifiers": dbg(["fillMaxWidth", {"padding": [float(PADDING), 20.0]}], debug),
                     "children": line})

    if theme.chrome_progress and total:
        rows.append(_progress_bar_canvas(theme, index, total, width, debug))

    # Anchor the chrome column to the bottom of the slide, translucent as a whole.
    return {"type": "box", "horizontalAlignment": "start", "verticalAlignment": "bottom",
            "modifiers": dbg(["fillMaxSize"], debug), "children": [
                {"type": "column",
                 "modifiers": ["fillMaxWidth",
                               {"graphicsLayer": {"alpha": round(theme.chrome_alpha, 3)}}],
                 "children": rows}]}


def with_chrome(content: dict, theme: Theme, index: int, total: int,
                width: int, height: int, debug: bool, stype: str = "content") -> dict:
    """Layer the chrome overlay on top of a slide's content node. Title and section
    slides are clean covers — they never carry footer / page number / progress chrome."""
    if stype in ("title", "section") or getattr(theme, "chrome_hidden", False):
        return content
    overlay = _chrome_overlay(theme, index, total, width, height, debug)
    if overlay is None:
        return content
    return {"type": "box", "modifiers": dbg(["fillMaxSize"], debug),
            "children": [content, overlay]}


def _no_web(blocks: list[dict]) -> list[dict]:
    """Drop native overlay blocks (web pages and videos). The outgoing (previous) slide in
    a transition is rendered without them: a native WKWebView / AVFoundation video player
    can't slide with the Skia content anyway, and baking it in re-instantiates the player
    on the destination slide (and leaves a lingering off-screen view). The incoming slide
    keeps its own overlay — it's the destination."""
    return [b for b in blocks if b.get("kind") not in ("weblink", "video")]


def _strip_customs(node):
    """Recursively remove custom-component nodes (op 93: video / web / embedded-rc hosts)
    from a built root. Used on the *outgoing* slide of a transition: custom components are
    painted by their native host every frame regardless of which StateLayout branch is
    active, so an embed baked into the inactive (previous) state leaks through and lingers
    on top of the incoming slide. Stripping them leaves the outgoing slide's static Skia
    content to crossfade normally; the incoming slide keeps its own live embeds."""
    if isinstance(node, dict):
        kids = node.get("children")
        if isinstance(kids, list):
            node["children"] = [_strip_customs(c) for c in kids
                                 if not (isinstance(c, dict) and c.get("type") == "custom")]
        return node
    if isinstance(node, list):
        return [_strip_customs(c) for c in node
                if not (isinstance(c, dict) and c.get("type") == "custom")]
    return node


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
    (op 240, wrapping inline-styled text) and Custom components (op 93, embedded video)."""
    root = doc.get("root")
    profiles = 0
    if _contains_shader(root):
        profiles |= PROFILE_ANDROIDX
    if _contains_type(root, "flow") or _contains_type(root, "custom"):
        profiles |= PROFILE_ANDROIDX | PROFILE_EXPERIMENTAL
    if profiles:
        doc["header"]["profiles"] = profiles
    return doc


def build_doc(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
              index: int, debug: bool, total: int = 0, scroll: dict | None = None,
              animate: bool | None = None) -> dict:
    counter = [0]
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, counter,
                            scroll=scroll, animate=animate)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": with_chrome(root, theme, index, total, width, height, debug, slide_type(slide)),
    })


def build_snapshot_doc(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                       index: int, debug: bool = False) -> dict:
    """A plain settled render of a slide's content + background (NO chrome, NO transition, no
    stagger) — rendered to a PNG to seed a `freeze` slide's frozen-transition snapshot."""
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, [0], animate=False)
    return _finalize({"header": header(slide, width, height, index), "root": [root]})


def build_transition_doc(prev: tuple | None, cur: tuple, theme: Theme, width: int, height: int,
                         index: int, debug: bool, total: int = 0, scroll: dict | None = None,
                         prev_theme: Theme | None = None) -> dict:
    """A StateLayout that crossfades from the previous slide (state 0) to the current
    slide (state 1); the index auto-advances on load via animTime. ``prev_theme`` renders the
    outgoing slide with its *own* theme (padding/colour overrides) so it matches how it just
    looked, rather than inheriting the incoming slide's."""
    counter = [0]
    prev_root = (blank_root(theme, width, height, debug) if prev is None
                 else _strip_customs(build_slide_root(prev[0], _no_web(prev[1]), prev_theme or theme, width, height, index - 1, debug, counter, animate=False)))
    cur_root = build_slide_root(cur[0], cur[1], theme, width, height, index, debug, counter,
                                scroll=scroll)
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


def _gate_customs(node, gate: float) -> None:
    """Append ``&gate=<sec>`` to every custom-component config in a built root so its native
    host skips painting until animTime passes the gate — the live embeds stay dormant behind
    the frozen snapshot for the length of the opening transition."""
    if isinstance(node, dict):
        if node.get("type") == "custom" and isinstance(node.get("config"), str):
            cfg = node["config"]
            node["config"] = f"{cfg}{'&' if '#' in cfg else '#'}gate={round(gate, 3)}"
        for v in node.values():
            _gate_customs(v, gate)
    elif isinstance(node, list):
        for v in node:
            _gate_customs(v, gate)


def _frozen_overlay(png: str, gate: float, fade: float, width: int, height: int,
                    debug: bool) -> dict:
    """A full-slide snapshot image, opaque through the transition (animTime < gate) then fading
    out over ``fade`` seconds — dissolving to reveal the now-live content beneath it."""
    a = f"min(1.0, max(0.0, ({round(gate + fade, 3)} - animTime) / {round(fade, 3)}))"
    return {"type": "canvas",
            "modifiers": dbg(["fillMaxSize", {"graphicsLayer": {"alpha": a}}], debug),
            "commands": [
                {"type": "addbitmap", "image": png, "varName": "__frozen"},
                {"type": "drawbitmap", "image": "$__frozen", "left": 0.0, "top": 0.0,
                 "right": float(width), "bottom": float(height)}]}


def _apply_freeze(root: dict, freeze: dict, width: int, height: int, debug: bool) -> dict:
    """Gate the slide's live embeds and lay a fading snapshot over them, so the opening
    transition shows a cheap frozen picture that dissolves to the real content. ``freeze`` is
    {"png": path, "gate": seconds, "fade": seconds}."""
    _gate_customs(root, freeze["gate"])
    overlay = _frozen_overlay(freeze["png"], freeze["gate"], freeze["fade"], width, height, debug)
    return {"type": "box", "modifiers": dbg(["fillMaxSize"], debug), "children": [root, overlay]}


def build_push_doc(prev: tuple | None, cur: tuple, theme: Theme, width: int, height: int,
                   index: int, debug: bool, total: int = 0, axis: str = "x", sign: int = 1,
                   duration: float = PUSH_DURATION, scroll: dict | None = None,
                   prev_theme: Theme | None = None, freeze: dict | None = None) -> dict:
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

    # If both slides share the same background (same shader source, or both solid), draw it
    # ONCE behind the whole stage instead of once per sliding slide. A full-slide animated
    # shader is the dominant per-frame GPU cost, and rendering two of them (plus overdraw)
    # during a push is what makes the transition stutter. The ambient background doesn't
    # need to slide, so a single shared copy is visually equivalent and roughly halves the
    # transition's fragment work.
    shared_bg = None
    if prev is not None:
        p_theme = prev_theme or theme
        prev_st = slide_type(prev[0])
        cur_st = slide_type(cur[0])
        prev_sh = p_theme.shader_for(prev_st)
        cur_sh = theme.shader_for(cur_st)
        prev_doc = p_theme.bg_doc_for(prev_st)
        cur_doc = theme.bg_doc_for(cur_st)
        same_color = (p_theme.background == theme.background)
        if prev_sh and prev_sh == cur_sh and prev_doc == cur_doc and same_color:
            shared_bg = shader_canvas(cur_sh, width, height)
        elif not prev_sh and not cur_sh and prev_doc == cur_doc and same_color:
            if cur_doc:
                bg_layers = _render_bg_asset(cur_doc, theme, width, height, debug)
                shared_bg = {"type": "box", "modifiers": dbg(
                    ["fillMaxSize", {"background": theme.background}], debug),
                    "children": bg_layers}
            else:
                shared_bg = {"type": "box", "modifiers": dbg(
                    ["fillMaxSize", {"background": theme.background}], debug), "children": []}
    root_bg = "none" if shared_bg is not None else "default"

    children = []
    if shared_bg is not None:
        children.append(shared_bg)
    if prev is not None:
        prev_root = _strip_customs(build_slide_root(prev[0], _no_web(prev[1]), prev_theme or theme, width, height,
                                                    index - 1, debug, counter, bg=root_bg, animate=False))
        children.append(wrap(prev_root, prev_off))
    cur_root = build_slide_root(cur[0], cur[1], theme, width, height, index, debug,
                                counter, bg=root_bg, scroll=scroll)
    if freeze:
        cur_root = _apply_freeze(cur_root, freeze, width, height, debug)
    children.append(wrap(cur_root, cur_off))

    stage = {"type": "box", "modifiers": dbg(["fillMaxSize"], debug), "children": children}
    stage = with_transition_shader(stage, theme, width, height, "$__pp", debug)
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
    spec = theme.slide_type_spec(stype, SLIDE_TYPES[stype])
    if getattr(theme, "h_align", None):
        spec["h_align"] = theme.h_align
    if getattr(theme, "v_align", None):
        spec["v_align"] = theme.v_align
    pad_l, pad_t, pad_r, pad_b = _pad_for(spec, theme)
    content_w = width - pad_l - pad_r
    centered = spec.get("h_align") == "center" and spec.get("v_align") == "center"

    children = []
    title_group, title_h = _title_group(slide, stype, theme.title_size(stype), content_w,
                                        theme, centered, debug)
    children.extend(title_group)
    avail_h = height - pad_t - pad_b - title_h - _chrome_reserve(theme, stype, pad_b)

    children.extend(render_graph_morph(graph_block(prev[1]), graph_block(blocks),
                                       theme, debug, content_w, avail_h, GRAPH_PROGRESS_VAR))
    root_col = frame_slide(children, spec, theme, slide_type(slide), width, height, debug)
    root_col = with_transition_shader(root_col, theme, width, height, "$__gp", debug)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": [
            {"type": "variable", "name": "__gp", "vtype": "float", "value": GRAPH_P_EXPR},
            {"type": "variable", "name": "__gt", "vtype": "float", "value": GRAPH_EASE_EXPR},
            with_chrome(root_col, theme, index, total, width, height, debug, stype),
        ],
    })


def build_same_doc(prev: tuple, cur: tuple, theme: Theme, width: int, height: int,
                   index: int, debug: bool, total: int = 0, scroll: dict | None = None,
                   autosize_ok: bool = False) -> dict:
    """A `:: same` shared-element transition (lerp backend).

    The current slide is rendered normally so matched, unchanged content stays put
    (and text keeps proper wrapping); a matched graph morphs in place; content that
    appears fades/slides in. Matching lives in ``samematch`` and the animation is
    driven by the eased progress variable ``$__st`` — this whole function is the single
    swap point for a future StateLayout+animationId backend. ``scroll`` (a ``scroll_spec``)
    additionally clips the content to a window and scrolls it between same-slides — driven
    by the same ``$__st`` so the diff and the scroll animate together."""
    from .samematch import diff_slides
    slide, blocks = cur
    same_ctx = diff_slides(prev[1], blocks)
    same_ctx["autosize_ok"] = autosize_ok   # explicit `:: same` keeps autosize (matches its base)
    counter = [0]
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, counter,
                            same_ctx, scroll=scroll)
    root = with_transition_shader(root, theme, width, height, "$__sp", debug)
    p_expr, ease_expr = _same_exprs(theme)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": [
            {"type": "variable", "name": "__sp", "vtype": "float", "value": p_expr},
            {"type": "variable", "name": "__st", "vtype": "float", "value": ease_expr},
            with_chrome(root, theme, index, total, width, height, debug, slide_type(slide)),
        ],
    })


def build_scroll_doc(slide: dict, blocks: list[dict], theme: Theme, width: int, height: int,
                     index: int, debug: bool, total: int, prev_off: float, cur_off: float,
                     viewport: float) -> dict:
    """A scroll *step*: the slide's full-size content clipped to a fixed window that animates
    from ``prev_off`` to ``cur_off`` pixels on load (reusing the `:: same` progress var), so
    pressing next scrolls the content up. Auto-generated by ``scroll = N`` and by scroll-aware
    `:: same`. The title and chrome stay fixed; only the content window moves."""
    counter = [0]
    root = build_slide_root(slide, blocks, theme, width, height, index, debug, counter,
                            scroll=scroll_spec(prev_off, cur_off, viewport))
    root = with_transition_shader(root, theme, width, height, "$__sp", debug)
    p_expr, ease_expr = _same_exprs(theme)
    return _finalize({
        "header": header(slide, width, height, index),
        "root": [
            {"type": "variable", "name": "__sp", "vtype": "float", "value": p_expr},
            {"type": "variable", "name": "__st", "vtype": "float", "value": ease_expr},
            with_chrome(root, theme, index, total, width, height, debug, slide_type(slide)),
        ],
    })

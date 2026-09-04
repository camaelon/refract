"""Graphs from Graphviz "dot" syntax, rendered with our own drawing.

Graphviz computes the *layout* only (``dot -Tjson`` gives node positions and edge
splines); we draw the nodes (rounded rects + labels), edges (bezier sampled to
polylines) and arrowheads (filled polygons) as canvas commands, mapped into the deck
coordinate space. This mirrors the approach used in Origami.

For "magic move" transitions, geometry is keyed by identity (node name, edge
tail→head) so matched elements can be interpolated between two layouts. Because edge
splines have different control-point counts across layouts, matched edges are
resampled to a fixed number of points (by arc length) before lerping.
"""

from __future__ import annotations

import json
import subprocess
from math import hypot

from .components import dbg, text

GRAPH_ENGINES = {"dot", "neato", "fdp", "sfdp", "twopi", "circo", "graphviz"}

_NODE_STROKE_W = 3.0
_EDGE_W = 2.5
_SPLINE_SEGS = 10          # line segments per cubic bezier when sampling
_MORPH_SAMPLES = 28        # points a matched edge is resampled to before lerping
_PT_PER_INCH = 72.0
# Magic-move: new arrows cascade in only after the boxes have settled (the morph finishes
# ~animTime 0.62). Each new arrow starts a little after the previous, in animTime seconds.
_ARROW_REVEAL_START = 0.66
_ARROW_REVEAL_STAGGER = 0.13
_ARROW_REVEAL_DUR = 0.22


# ── Graphviz ─────────────────────────────────────────────────────────────────
def run_dot(source: str, engine: str) -> dict | None:
    """Run graphviz and return the parsed ``-Tjson`` layout, or None on failure."""
    eng = "dot" if engine in ("graphviz", "", None) else engine
    try:
        proc = subprocess.run([eng, "-Tjson"], input=source,
                              capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _transform(graph: dict, avail_w: float, avail_h: float):
    """(x,y)->(cx,cy) from graphviz points (bottom-left origin, scaled to fit) to
    canvas coords (top-left origin), plus the scale factor."""
    bb = [float(v) for v in graph.get("bb", "0,0,1,1").split(",")]
    bb_w = max(1.0, bb[2] - bb[0])
    bb_h = max(1.0, bb[3] - bb[1])
    scale = min(avail_w / bb_w, avail_h / bb_h)
    ox = (avail_w - bb_w * scale) / 2.0 - bb[0] * scale
    oy = (avail_h - bb_h * scale) / 2.0 + bb[3] * scale

    def tx(x, y):
        return (round(ox + x * scale, 2), round(oy - y * scale, 2))

    return tx, scale


def _is_node(obj: dict) -> bool:
    name = obj.get("name", "")
    return bool(name) and not name.startswith("cluster") \
        and "nodes" not in obj and "subgraphs" not in obj


def graph_geometry(block: dict, avail_w: float, avail_h: float) -> dict | None:
    """Compute {nodes: {name: rect}, edges: {(tail,head): {spline, arrow}}}."""
    graph = run_dot(block.get("dot", ""), block.get("engine", "dot"))
    if not graph:
        return None
    tx, scale = _transform(graph, avail_w, avail_h)

    gvid_name = {}
    for obj in graph.get("objects", []):
        if obj.get("_gvid") is not None:
            gvid_name[obj["_gvid"]] = obj.get("name")

    nodes = {}
    for obj in graph.get("objects", []):
        if not _is_node(obj) or not obj.get("pos"):
            continue
        nx, ny = (float(v) for v in obj["pos"].split(","))
        cx, cy = tx(nx, ny)
        nw = float(obj.get("width", 0.75)) * _PT_PER_INCH * scale
        nh = float(obj.get("height", 0.5)) * _PT_PER_INCH * scale
        label = obj.get("label")
        if label in (None, "\\N"):
            label = obj["name"]
        fill, stroke = _node_colors(obj)
        nodes[obj["name"]] = {"cx": cx, "cy": cy, "nw": nw, "nh": nh,
                              "l": cx - nw / 2, "t": cy - nh / 2,
                              "r": cx + nw / 2, "b": cy + nh / 2, "label": label,
                              "fill": fill, "stroke": stroke}

    edges = {}
    for edge in graph.get("edges", []):
        tail = gvid_name.get(edge.get("tail"))
        head = gvid_name.get(edge.get("head"))
        if tail is None or head is None:
            continue
        spline = None
        color = None
        dash, wid = None, None
        for cmd in edge.get("_draw_", []):
            op = cmd.get("op")
            if op == "b" and cmd.get("points"):
                spline = _sample_spline([tx(p[0], p[1]) for p in cmd["points"]], _SPLINE_SEGS)
            elif op == "S":
                dash, wid = _parse_style(cmd.get("style", ""), scale, dash, wid)
            elif op == "c":
                color = _norm_color(cmd.get("color"))
        arrow = None
        for cmd in edge.get("_hdraw_", []):
            if cmd.get("op") in ("P", "p") and cmd.get("points"):
                arrow = [tx(p[0], p[1]) for p in cmd["points"]]
        edges[(tail, head)] = {"spline": spline, "arrow": arrow,
                               "color": color, "dash": dash, "width": wid}

    clusters = []
    for obj in graph.get("objects", []):
        if not str(obj.get("name", "")).startswith("cluster"):
            continue
        poly, fill, stroke = None, None, None
        dash, wid = None, None
        for cmd in obj.get("_draw_", []):
            if cmd.get("op") in ("P", "p") and cmd.get("points"):
                poly = [tx(p[0], p[1]) for p in cmd["points"]]
            elif cmd.get("op") == "C":
                fill = _norm_color(cmd.get("color"))
            elif cmd.get("op") == "c":
                stroke = _norm_color(cmd.get("color"))
            elif cmd.get("op") == "S":
                dash, wid = _parse_style(cmd.get("style", ""), scale, dash, wid)
        label, lpos = None, None
        for cmd in obj.get("_ldraw_", []):
            if cmd.get("op") == "T":
                label = cmd.get("text")
                if cmd.get("pt"):
                    lpos = tx(cmd["pt"][0], cmd["pt"][1])
        if poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            clusters.append({"l": min(xs), "t": min(ys), "r": max(xs), "b": max(ys),
                             "fill": fill, "stroke": stroke, "label": label, "lpos": lpos,
                             "dash": dash, "width": wid})

    return {"nodes": nodes, "edges": edges, "clusters": clusters}


def _norm_color(c: str | None) -> str | None:
    """Normalize a graphviz colour (#rrggbb) to #AARRGGBB, or None for the default black."""
    if not c or not c.startswith("#"):
        return None
    hexv = c[1:]
    if len(hexv) == 6:
        if hexv.lower() == "000000":
            return None  # graphviz implicit default — let the theme decide
        return "#FF" + hexv.upper()
    if len(hexv) == 8:
        return "#" + hexv.upper()
    return None


def _parse_style(style: str, scale: float, dash, wid):
    """Interpret a graphviz edge 'S' style op → (dash intervals, stroke width)."""
    s = style.lower()
    # Fixed small px dashes (not scaled by the layout ratio, which can be large and would
    # blow the dashes up into long segments).
    if s == "dashed":
        dash = [5.0, 4.0]
    elif s == "dotted":
        dash = [1.5, 3.5]
    elif s.startswith("setlinewidth("):
        try:
            wid = round(float(s[len("setlinewidth("):-1]) * scale, 2)
        except ValueError:
            pass
    return dash, wid


def _node_colors(obj: dict):
    """Node fill (C op) and stroke (c op) colours from the dot source, if any."""
    fill = stroke = None
    for cmd in obj.get("_draw_", []):
        if cmd.get("op") == "C":
            fill = _norm_color(cmd.get("color"))
        elif cmd.get("op") == "c":
            stroke = _norm_color(cmd.get("color"))
    return fill, stroke


# ── Geometry helpers ─────────────────────────────────────────────────────────
def _bezier(p0, p1, p2, p3, u):
    m = 1.0 - u
    return (m*m*m*p0[0] + 3*m*m*u*p1[0] + 3*m*u*u*p2[0] + u*u*u*p3[0],
            m*m*m*p0[1] + 3*m*m*u*p1[1] + 3*m*u*u*p2[1] + u*u*u*p3[1])


def _sample_spline(pts: list, segs: int) -> list:
    """Sample a graphviz spline (control points, len = 3k+1) into a polyline."""
    if len(pts) < 4:
        return list(pts)
    out = [pts[0]]
    i = 0
    while i + 3 < len(pts):
        for k in range(1, segs + 1):
            out.append(_bezier(pts[i], pts[i + 1], pts[i + 2], pts[i + 3], k / segs))
        i += 3
    return out


def _resample(poly: list, n: int) -> list:
    """Resample a polyline to exactly ``n`` points evenly spaced by arc length."""
    if not poly:
        return [(0.0, 0.0)] * n
    if len(poly) == 1:
        return [poly[0]] * n
    acc = [0.0]
    for i in range(1, len(poly)):
        acc.append(acc[-1] + hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1]))
    total = acc[-1] or 1.0
    out = []
    j = 0
    for k in range(n):
        d = total * k / (n - 1)
        while j < len(acc) - 2 and acc[j + 1] < d:
            j += 1
        s0, s1 = acc[j], acc[j + 1]
        u = 0.0 if s1 == s0 else max(0.0, min(1.0, (d - s0) / (s1 - s0)))
        out.append((poly[j][0] + (poly[j + 1][0] - poly[j][0]) * u,
                    poly[j][1] + (poly[j + 1][1] - poly[j][1]) * u))
    return out


def _fit_font(label: str, w: float, h: float) -> float:
    return round(max(10.0, min(38.0, h * 0.42, w / max(1, len(label)) * 1.7)), 1)


def _r2(v):
    """Round a numeric coordinate; pass expression strings (from _lerp) through untouched."""
    return round(v, 2) if isinstance(v, (int, float)) else v


def _lerp(a: float, b: float, t: str):
    """A number if a≈b, else an expression string interpolating a→b by t (var ref)."""
    a, b = round(a, 2), round(b, 2)
    if abs(a - b) < 0.01:
        return a
    return f"({a}) + (({b}) - ({a})) * {t}"


# ── Command emitters ─────────────────────────────────────────────────────────
def _paint(ops: list) -> dict:
    return {"type": "paint", "ops": ops}


def _with_alpha(ops, alpha):
    return ops + ([{"alpha": alpha}] if alpha is not None else [])


def _line(p, q) -> dict:
    return {"type": "drawline", "x1": p[0], "y1": p[1], "x2": q[0], "y2": q[1]}


def _rr(l, t, r, b, rad) -> dict:
    return {"type": "drawroundrect", "left": l, "top": t, "right": r, "bottom": b,
            "rx": rad, "ry": rad}


def _fill_polygon(points: list, pid: list) -> list[dict]:
    pid[0] += 1
    path = f"__gp{pid[0]}"
    out = [{"type": "pathcreate", "id": path, "x": points[0][0], "y": points[0][1]}]
    for x, y in points[1:]:
        out.append({"type": "pathappendlineto", "path": path, "x": x, "y": y})
    out.append({"type": "pathappendclose", "path": path})
    out.append({"type": "drawpath", "path": path})
    return out


_GLOW_STROKE_W = 5.0     # width of the bright stroke drawn into the blurred glow layer


def _node_cmds(l, t, r, b, cx, cy, rad, label, fs, theme, alpha,
               fill=None, stroke=None) -> list[dict]:
    stroke_col = stroke or theme.graph_node_stroke
    return [
        _paint(_with_alpha([{"color": fill or theme.graph_node_fill}, {"style": "fill"}], alpha)),
        _rr(l, t, r, b, rad),
        _paint(_with_alpha([{"color": stroke_col}, {"style": "stroke"},
                            {"strokeWidth": _NODE_STROKE_W}, {"patheffect": None}], alpha)),
        _rr(l, t, r, b, rad),
        _paint(_with_alpha([{"color": theme.graph_node_text}, {"style": "fill"},
                            {"textSize": fs}], alpha)),
        {"type": "drawtextanchored", "text": label, "x": cx, "y": cy, "panX": 0.0, "panY": 0.0},
    ]


def _glow_stroke(l, t, r, b, rad, stroke_col, alpha) -> list[dict]:
    """A single bright border stroke drawn into the blurred glow layer."""
    return [
        _paint(_with_alpha([{"color": stroke_col}, {"style": "stroke"},
                            {"strokeWidth": _GLOW_STROKE_W}, {"patheffect": None}], alpha)),
        _rr(l, t, r, b, rad),
    ]


def _node_glow_cmds(n: dict, theme, alpha) -> list[dict]:
    """Just the node's border stroke, bright — drawn into a blurred layer to make the
    neon light-bleed (a real gaussian blur via a graphicsLayer, not stacked strokes)."""
    rad = round(min(n["nw"], n["nh"]) * 0.28, 2)
    return _glow_stroke(round(n["l"], 2), round(n["t"], 2), round(n["r"], 2),
                        round(n["b"], 2), rad, n.get("stroke") or theme.graph_node_stroke, alpha)


def _static_node(n: dict, theme, alpha) -> list[dict]:
    rad = round(min(n["nw"], n["nh"]) * 0.28, 2)
    return _node_cmds(round(n["l"], 2), round(n["t"], 2), round(n["r"], 2), round(n["b"], 2),
                      round(n["cx"], 2), round(n["cy"], 2), rad, n["label"],
                      _fit_font(n["label"], n["nw"], n["nh"]), theme, alpha,
                      fill=n.get("fill"), stroke=n.get("stroke"))


def _edge_stroke_ops(e: dict, theme, alpha) -> list:
    """Paint ops for an edge stroke: colour, width, and dash effect (explicitly set —
    null for solid — so a previous edge's dash doesn't leak onto this one or the nodes)."""
    ops = [{"color": e.get("color") or theme.graph_edge}, {"style": "stroke"},
           {"strokeWidth": e.get("width") or _EDGE_W},
           {"patheffect": {"intervals": e["dash"], "phase": 0.0} if e.get("dash") else None}]
    return _with_alpha(ops, alpha)


def _stroke_polyline(poly: list, pid: list) -> list[dict]:
    """Stroke a polyline as a single open path, so a dash effect runs continuously
    along the whole edge (drawing separate line segments resets the dash each time)."""
    pts = [(round(x, 2), round(y, 2)) for x, y in poly]
    pid[0] += 1
    path = f"__ge{pid[0]}"
    out = [{"type": "pathcreate", "id": path, "x": pts[0][0], "y": pts[0][1]}]
    for x, y in pts[1:]:
        out.append({"type": "pathappendlineto", "path": path, "x": x, "y": y})
    out.append({"type": "drawpath", "path": path})
    return out


def _static_edge(e: dict, theme, alpha, pid: list, part: str = "both") -> list[dict]:
    """Draw an edge. ``part`` selects the spline, the arrowhead, or both — so callers can
    layer arrowheads on top of everything else."""
    cmds = []
    if part in ("both", "spline") and e.get("spline"):
        cmds.append(_paint(_edge_stroke_ops(e, theme, alpha)))
        cmds.extend(_stroke_polyline(e["spline"], pid))
    if part in ("both", "arrow") and e.get("arrow"):
        # Arrowheads are solid (no dash), in the edge colour.
        cmds.append(_paint(_with_alpha([{"color": e.get("color") or theme.graph_edge},
                                        {"style": "fill"}], alpha)))
        cmds.extend(_fill_polygon([(round(x, 2), round(y, 2)) for x, y in e["arrow"]], pid))
    return cmds


def _cluster_cmds(c: dict, theme, pid: list, alpha=None) -> list[dict]:
    """A subgraph cluster: filled/stroked rounded box with an optional label. ``alpha``
    (literal or expression) fades the whole cluster."""
    l, t, r, b = _r2(c["l"]), _r2(c["t"]), _r2(c["r"]), _r2(c["b"])
    cmds = []
    if c.get("fill"):
        cmds.append(_paint(_with_alpha([{"color": c["fill"]}, {"style": "fill"}], alpha)))
        cmds.append(_rr(l, t, r, b, 12.0))
    # A dashed/dotted cluster (graphviz `style=dashed`) carries dash intervals; set the
    # effect explicitly (null for solid) so it neither leaks onto nor is leaked from siblings.
    cmds.append(_paint(_with_alpha([{"color": c.get("stroke") or theme.graph_edge},
                        {"style": "stroke"}, {"strokeWidth": c.get("width") or 2.0},
                        {"patheffect": {"intervals": c["dash"], "phase": 0.0}
                                       if c.get("dash") else None}], alpha)))
    cmds.append(_rr(l, t, r, b, 12.0))
    if c.get("label") and c.get("lpos"):
        lx, ly = _r2(c["lpos"][0]), _r2(c["lpos"][1])
        cmds.append(_paint(_with_alpha([{"color": c.get("stroke") or theme.graph_node_text},
                            {"style": "fill"}, {"textSize": 24.0}], alpha)))
        cmds.append({"type": "drawtextanchored", "text": c["label"], "x": lx, "y": ly,
                     "panX": 0.0, "panY": 0.0})
    return cmds


def _morph_cluster_cmds(ca: dict, cb: dict, theme, t: str, pid: list) -> list[dict]:
    """A matched cluster (same label in both layouts): lerp its box and label position by
    ``t`` so the dashed frame glides/resizes with its nodes instead of snapping to target."""
    c = dict(cb)
    c["l"], c["t"] = _lerp(ca["l"], cb["l"], t), _lerp(ca["t"], cb["t"], t)
    c["r"], c["b"] = _lerp(ca["r"], cb["r"], t), _lerp(ca["b"], cb["b"], t)
    if ca.get("lpos") and cb.get("lpos"):
        c["lpos"] = [_lerp(ca["lpos"][0], cb["lpos"][0], t),
                     _lerp(ca["lpos"][1], cb["lpos"][1], t)]
    return _cluster_cmds(c, theme, pid)


def _morph_edge(ea: dict, eb: dict, theme, t: str, pid: list, part: str = "both") -> list[dict]:
    """A matched edge: lerp its (resampled) spline and arrowhead by ``t``. ``part`` selects
    the spline, the arrowhead, or both."""
    cmds = []
    if part in ("both", "spline") and ea.get("spline") and eb.get("spline"):
        sa = _resample(ea["spline"], _MORPH_SAMPLES)
        sb = _resample(eb["spline"], _MORPH_SAMPLES)
        pts = [(_lerp(sa[i][0], sb[i][0], t), _lerp(sa[i][1], sb[i][1], t))
               for i in range(_MORPH_SAMPLES)]
        cmds.append(_paint([{"color": theme.graph_edge}, {"style": "stroke"},
                            {"strokeWidth": _EDGE_W}]))
        for p, q in zip(pts, pts[1:]):
            cmds.append(_line(p, q))
    if part in ("both", "arrow") and ea.get("arrow") and eb.get("arrow"):
        n = min(len(ea["arrow"]), len(eb["arrow"]))
        aa, ab = _resample(ea["arrow"], n), _resample(eb["arrow"], n)
        pts = [(_lerp(aa[i][0], ab[i][0], t), _lerp(aa[i][1], ab[i][1], t)) for i in range(n)]
        cmds.append(_paint([{"color": theme.graph_edge}, {"style": "fill"}]))
        cmds.extend(_fill_polygon(pts, pid))
    return cmds


def _canvas(cmds: list, avail_w: float, avail_h: float, debug: bool,
            extra_mods: list | None = None) -> dict:
    return {
        "type": "canvas",
        "modifiers": dbg([{"width": float(avail_w)}, {"height": float(avail_h)},
                          *(extra_mods or [])], debug),
        "commands": cmds,
    }


def _with_glow(main_cmds: list, glow_cmds: list, theme, avail_w, avail_h,
               debug: bool) -> list[dict]:
    """Overlay the crisp graph on a blurred copy of the node borders. The glow layer is a
    canvas with a ``graphicsLayer`` blur render effect (real gaussian blur), so the bright
    strokes bleed into a soft neon halo behind the sharp graph."""
    crisp = _canvas(main_cmds, avail_w, avail_h, debug)
    if not (getattr(theme, "graph_glow", True) and glow_cmds):
        return [crisp]
    radius = round(getattr(theme, "graph_glow_radius", 9.0)
                   * getattr(theme, "graph_glow_strength", 1.0), 2)
    glow = _canvas(glow_cmds, avail_w, avail_h, debug,
                   extra_mods=[{"graphicsLayer": {"blur": radius}}])
    return [{"type": "box",
             "modifiers": dbg([{"width": float(avail_w)}, {"height": float(avail_h)}], debug),
             "children": [glow, crisp]}]


# ── Public rendering ─────────────────────────────────────────────────────────
def render_graph(block: dict, theme, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    geo = graph_geometry(block, avail_w, avail_h)
    if not geo:
        return [text("[graphviz failed — is `dot` installed?]", 32.0, theme.body_color, debug)]
    cmds: list[dict] = []
    glow: list[dict] = []
    arrows: list[dict] = []
    pid = [0]
    for c in geo.get("clusters", []):              # clusters behind everything
        cmds += _cluster_cmds(c, theme, pid)
    for e in geo["edges"].values():                # edge lines under nodes…
        cmds += _static_edge(e, theme, None, pid, "spline")
        arrows += _static_edge(e, theme, None, pid, "arrow")
    for n in geo["nodes"].values():
        cmds += _static_node(n, theme, None)
        glow += _node_glow_cmds(n, theme, None)
    cmds += arrows                                 # …arrowheads on top of everything
    return _with_glow(cmds, glow, theme, avail_w, avail_h, debug)


def render_graph_morph(prev_block, cur_block, theme, debug, avail_w, avail_h,
                       t: str) -> list[dict]:
    """Magic move: matched nodes/edges (by identity) glide+resize by ``t``; the rest
    fades. Edges are resampled to a fixed point count so their splines can lerp."""
    ga = graph_geometry(prev_block, avail_w, avail_h) if prev_block else None
    gb = graph_geometry(cur_block, avail_w, avail_h) if cur_block else None
    if not ga or not gb:
        return render_graph(cur_block or prev_block, theme, debug, avail_w, avail_h, [0])

    cmds: list[dict] = []
    arrows: list[dict] = []
    pid = [0]

    # Clusters, behind everything. Match by label: a cluster present in both layouts stays
    # put; one only in the old layout fades out; a *new* one fades in only after the nodes
    # have finished moving (its alpha ramps up over the tail of the morph).
    ca_by_label = {c.get("label"): c for c in ga.get("clusters", [])}
    gb_labels = {c.get("label") for c in gb.get("clusters", [])}
    new_cluster_alpha = f"min(1.0, max(0.0, ({t} - 0.55) / 0.45))"
    for c in ga.get("clusters", []):
        if c.get("label") not in gb_labels:                    # gone → fade out
            cmds += _cluster_cmds(c, theme, pid, alpha=f"1.0 - {t}")
    for c in gb.get("clusters", []):
        ca = ca_by_label.get(c.get("label"))
        if ca is not None:                                     # persists → morph box + label
            cmds += _morph_cluster_cmds(ca, c, theme, t, pid)
        else:                                                  # new → delayed fade-in
            cmds += _cluster_cmds(c, theme, pid, alpha=new_cluster_alpha)

    # Edge lines (under nodes); arrowheads collected for last. Disappearing edges fade out
    # and matched edges morph over the whole move; *new* edges (arrows) instead cascade in
    # one after another only once the boxes have finished animating.
    # Every one of these walks a *set*, whose iteration order is not stable between runs
    # (Python randomises string hashing per process). Sorting is not cosmetic: the order these
    # are emitted in is the order they are drawn in, so without it two builds of the same deck
    # produce different documents — different z-order where elements overlap, and a slide that
    # can never be reused by an incremental build.
    ea, eb = ga["edges"], gb["edges"]
    for key in sorted(ea.keys() - eb.keys()):
        cmds += _static_edge(ea[key], theme, f"1.0 - {t}", pid, "spline")
        arrows += _static_edge(ea[key], theme, f"1.0 - {t}", pid, "arrow")
    for i, key in enumerate(sorted(eb.keys() - ea.keys())):
        # animTime-based so it can extend past the (already-finished) morph; staggered.
        start = round(_ARROW_REVEAL_START + i * _ARROW_REVEAL_STAGGER, 3)
        reveal = f"min(1.0, max(0.0, (animTime - {start}) / {_ARROW_REVEAL_DUR}))"
        cmds += _static_edge(eb[key], theme, reveal, pid, "spline")
        arrows += _static_edge(eb[key], theme, reveal, pid, "arrow")
    for key in sorted(ea.keys() & eb.keys()):
        cmds += _morph_edge(ea[key], eb[key], theme, t, pid, "spline")
        arrows += _morph_edge(ea[key], eb[key], theme, t, pid, "arrow")

    # Nodes.
    na, nb = ga["nodes"], gb["nodes"]
    glow: list[dict] = []
    for name in sorted(na.keys() - nb.keys()):
        cmds += _static_node(na[name], theme, f"1.0 - {t}")
        glow += _node_glow_cmds(na[name], theme, f"1.0 - {t}")
    for name in sorted(nb.keys() - na.keys()):
        cmds += _static_node(nb[name], theme, t)
        glow += _node_glow_cmds(nb[name], theme, t)
    for name in sorted(na.keys() & nb.keys()):
        a2, b2 = na[name], nb[name]
        rad = _lerp(min(a2["nw"], a2["nh"]) * 0.28, min(b2["nw"], b2["nh"]) * 0.28, t)
        ll, tt = _lerp(a2["l"], b2["l"], t), _lerp(a2["t"], b2["t"], t)
        rr, bb = _lerp(a2["r"], b2["r"], t), _lerp(a2["b"], b2["b"], t)
        # Lerp the label size too (from the source to the target fit) so the text scales
        # with the box, instead of snapping to the target size while the box is still big.
        fs = _lerp(_fit_font(a2["label"], a2["nw"], a2["nh"]),
                   _fit_font(b2["label"], b2["nw"], b2["nh"]), t)
        cmds += _node_cmds(
            ll, tt, rr, bb,
            _lerp(a2["cx"], b2["cx"], t), _lerp(a2["cy"], b2["cy"], t),
            rad, b2["label"], fs, theme, None)
        glow += _glow_stroke(ll, tt, rr, bb, rad,
                             b2.get("stroke") or theme.graph_node_stroke, None)

    cmds += arrows                                 # arrowheads on top of everything
    return _with_glow(cmds, glow, theme, avail_w, avail_h, debug)

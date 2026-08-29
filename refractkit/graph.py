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
        for cmd in obj.get("_draw_", []):
            if cmd.get("op") in ("P", "p") and cmd.get("points"):
                poly = [tx(p[0], p[1]) for p in cmd["points"]]
            elif cmd.get("op") == "C":
                fill = _norm_color(cmd.get("color"))
            elif cmd.get("op") == "c":
                stroke = _norm_color(cmd.get("color"))
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
                             "fill": fill, "stroke": stroke, "label": label, "lpos": lpos})

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
    if s == "dashed":
        dash = [round(9 * scale, 2), round(6 * scale, 2)]
    elif s == "dotted":
        dash = [round(2 * scale, 2), round(5 * scale, 2)]
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


def _node_cmds(l, t, r, b, cx, cy, rad, label, fs, theme, alpha,
               fill=None, stroke=None) -> list[dict]:
    return [
        _paint(_with_alpha([{"color": fill or theme.graph_node_fill}, {"style": "fill"}], alpha)),
        _rr(l, t, r, b, rad),
        _paint(_with_alpha([{"color": stroke or theme.graph_node_stroke}, {"style": "stroke"},
                            {"strokeWidth": _NODE_STROKE_W}, {"patheffect": None}], alpha)),
        _rr(l, t, r, b, rad),
        _paint(_with_alpha([{"color": theme.graph_node_text}, {"style": "fill"},
                            {"textSize": fs}], alpha)),
        {"type": "drawtextanchored", "text": label, "x": cx, "y": cy, "panX": 0.0, "panY": 0.0},
    ]


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


def _static_edge(e: dict, theme, alpha, pid: list) -> list[dict]:
    cmds = []
    if e.get("spline"):
        cmds.append(_paint(_edge_stroke_ops(e, theme, alpha)))
        cmds.extend(_stroke_polyline(e["spline"], pid))
    if e.get("arrow"):
        # Arrowheads are solid (no dash), in the edge colour.
        cmds.append(_paint(_with_alpha([{"color": e.get("color") or theme.graph_edge},
                                        {"style": "fill"}], alpha)))
        cmds.extend(_fill_polygon([(round(x, 2), round(y, 2)) for x, y in e["arrow"]], pid))
    return cmds


def _cluster_cmds(c: dict, theme, pid: list) -> list[dict]:
    """A subgraph cluster: filled/stroked rounded box with an optional label."""
    l, t, r, b = round(c["l"], 2), round(c["t"], 2), round(c["r"], 2), round(c["b"], 2)
    cmds = []
    if c.get("fill"):
        cmds.append(_paint([{"color": c["fill"]}, {"style": "fill"}]))
        cmds.append(_rr(l, t, r, b, 12.0))
    cmds.append(_paint([{"color": c.get("stroke") or theme.graph_edge}, {"style": "stroke"},
                        {"strokeWidth": 2.0}, {"patheffect": None}]))
    cmds.append(_rr(l, t, r, b, 12.0))
    if c.get("label") and c.get("lpos"):
        lx, ly = round(c["lpos"][0], 2), round(c["lpos"][1], 2)
        cmds.append(_paint([{"color": c.get("stroke") or theme.graph_node_text},
                            {"style": "fill"}, {"textSize": 24.0}]))
        cmds.append({"type": "drawtextanchored", "text": c["label"], "x": lx, "y": ly,
                     "panX": 0.0, "panY": 0.0})
    return cmds


def _morph_edge(ea: dict, eb: dict, theme, t: str, pid: list) -> list[dict]:
    """A matched edge: lerp its (resampled) spline and arrowhead by ``t``."""
    cmds = []
    if ea.get("spline") and eb.get("spline"):
        sa = _resample(ea["spline"], _MORPH_SAMPLES)
        sb = _resample(eb["spline"], _MORPH_SAMPLES)
        pts = [(_lerp(sa[i][0], sb[i][0], t), _lerp(sa[i][1], sb[i][1], t))
               for i in range(_MORPH_SAMPLES)]
        cmds.append(_paint([{"color": theme.graph_edge}, {"style": "stroke"},
                            {"strokeWidth": _EDGE_W}]))
        for p, q in zip(pts, pts[1:]):
            cmds.append(_line(p, q))
    if ea.get("arrow") and eb.get("arrow"):
        n = min(len(ea["arrow"]), len(eb["arrow"]))
        aa, ab = _resample(ea["arrow"], n), _resample(eb["arrow"], n)
        pts = [(_lerp(aa[i][0], ab[i][0], t), _lerp(aa[i][1], ab[i][1], t)) for i in range(n)]
        cmds.append(_paint([{"color": theme.graph_edge}, {"style": "fill"}]))
        cmds.extend(_fill_polygon(pts, pid))
    return cmds


def _canvas(cmds: list, avail_w: float, avail_h: float, debug: bool) -> list[dict]:
    return [{
        "type": "canvas",
        "modifiers": dbg([{"width": float(avail_w)}, {"height": float(avail_h)}], debug),
        "commands": cmds,
    }]


# ── Public rendering ─────────────────────────────────────────────────────────
def render_graph(block: dict, theme, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    geo = graph_geometry(block, avail_w, avail_h)
    if not geo:
        return [text("[graphviz failed — is `dot` installed?]", 32.0, theme.body_color, debug)]
    cmds: list[dict] = []
    pid = [0]
    for c in geo.get("clusters", []):              # clusters behind everything
        cmds += _cluster_cmds(c, theme, pid)
    for e in geo["edges"].values():                # edges under nodes
        cmds += _static_edge(e, theme, None, pid)
    for n in geo["nodes"].values():
        cmds += _static_node(n, theme, None)
    return _canvas(cmds, avail_w, avail_h, debug)


def render_graph_morph(prev_block, cur_block, theme, debug, avail_w, avail_h,
                       t: str) -> list[dict]:
    """Magic move: matched nodes/edges (by identity) glide+resize by ``t``; the rest
    fades. Edges are resampled to a fixed point count so their splines can lerp."""
    ga = graph_geometry(prev_block, avail_w, avail_h) if prev_block else None
    gb = graph_geometry(cur_block, avail_w, avail_h) if cur_block else None
    if not ga or not gb:
        return render_graph(cur_block or prev_block, theme, debug, avail_w, avail_h, [0])

    cmds: list[dict] = []
    pid = [0]

    # Clusters (behind everything) crossfade between the two layouts.
    for c in ga.get("clusters", []):
        cmds += [_paint([{"color": (c.get("stroke") or theme.graph_edge)}, {"style": "stroke"},
                         {"strokeWidth": 2.0}, {"alpha": f"1.0 - {t}"}]),
                 _rr(round(c["l"], 2), round(c["t"], 2), round(c["r"], 2), round(c["b"], 2), 12.0)]
    for c in gb.get("clusters", []):
        cmds += _cluster_cmds(c, theme, pid)

    # Edges (under nodes).
    ea, eb = ga["edges"], gb["edges"]
    for key in ea.keys() - eb.keys():
        cmds += _static_edge(ea[key], theme, f"1.0 - {t}", pid)
    for key in eb.keys() - ea.keys():
        cmds += _static_edge(eb[key], theme, t, pid)
    for key in ea.keys() & eb.keys():
        cmds += _morph_edge(ea[key], eb[key], theme, t, pid)

    # Nodes.
    na, nb = ga["nodes"], gb["nodes"]
    for name in na.keys() - nb.keys():
        cmds += _static_node(na[name], theme, f"1.0 - {t}")
    for name in nb.keys() - na.keys():
        cmds += _static_node(nb[name], theme, t)
    for name in na.keys() & nb.keys():
        a2, b2 = na[name], nb[name]
        rad = _lerp(min(a2["nw"], a2["nh"]) * 0.28, min(b2["nw"], b2["nh"]) * 0.28, t)
        cmds += _node_cmds(
            _lerp(a2["l"], b2["l"], t), _lerp(a2["t"], b2["t"], t),
            _lerp(a2["r"], b2["r"], t), _lerp(a2["b"], b2["b"], t),
            _lerp(a2["cx"], b2["cx"], t), _lerp(a2["cy"], b2["cy"], t),
            rad, b2["label"], _fit_font(b2["label"], b2["nw"], b2["nh"]), theme, None)

    return _canvas(cmds, avail_w, avail_h, debug)

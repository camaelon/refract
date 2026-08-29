"""Charts (bar / line / pie) from inline ``label: value`` data, drawn on a canvas."""

from __future__ import annotations

import math

from .components import dbg

# A categorical palette (accent-ish blues/greens/oranges) reused across charts.
PALETTE = ["#FF4FC3F7", "#FF81C995", "#FFFFB74D", "#FFBA68C8", "#FFE57373",
           "#FF4DB6AC", "#FF9575CD", "#FFF06292"]


def _paint(ops: list) -> dict:
    return {"type": "paint", "ops": ops}


def _text(value, x, y, size, color):
    return {"type": "drawtextanchored", "text": str(value), "x": round(x, 2),
            "y": round(y, 2), "panX": 0.0, "panY": 0.0,
            "fontSize": float(size), "color": color}


def render_chart(block: dict, theme, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    data = block.get("data", [])
    ctype = block.get("chart", "bar")
    w, h = float(avail_w), float(avail_h)
    if not data:
        return [{"type": "text", "value": "[empty chart]", "fontSize": 32.0,
                 "color": theme.body_color}]
    cmds = (_pie(data, w, h, theme) if ctype == "pie" else
            _line(data, w, h, theme) if ctype == "line" else
            _bar(data, w, h, theme))
    return [{"type": "canvas",
             "modifiers": dbg([{"width": w}, {"height": h}], debug),
             "commands": cmds}]


def _bar(data, w, h, theme) -> list[dict]:
    pad = 60.0
    plot_h = h - 2 * pad
    plot_w = w - 2 * pad
    vmax = max(v for _, v in data) or 1.0
    n = len(data)
    slot = plot_w / n
    bw = slot * 0.6
    cmds = []
    for i, (label, v) in enumerate(data):
        bh = plot_h * (v / vmax)
        x = pad + i * slot + (slot - bw) / 2
        top = pad + (plot_h - bh)
        cmds.append(_paint([{"color": PALETTE[i % len(PALETTE)]}, {"style": "fill"}]))
        cmds.append({"type": "drawroundrect", "left": round(x, 2), "top": round(top, 2),
                     "right": round(x + bw, 2), "bottom": round(pad + plot_h, 2),
                     "rx": 8.0, "ry": 8.0})
        cx = x + bw / 2
        cmds.append(_paint([{"color": theme.body_color}, {"style": "fill"}, {"textSize": 26.0}]))
        cmds.append(_text(_fmt(v), cx, top - 16, 26.0, theme.body_color))
        cmds.append(_text(label, cx, pad + plot_h + 28, 26.0, theme.body_color))
    return cmds


def _line(data, w, h, theme) -> list[dict]:
    pad = 60.0
    plot_h = h - 2 * pad
    plot_w = w - 2 * pad
    vmax = max(v for _, v in data) or 1.0
    vmin = min(v for _, v in data)
    span = (vmax - vmin) or 1.0
    n = len(data)
    step = plot_w / max(1, n - 1)
    pts = []
    for i, (_, v) in enumerate(data):
        x = pad + i * step
        y = pad + plot_h * (1 - (v - vmin) / span)
        pts.append((round(x, 2), round(y, 2)))
    cmds = [_paint([{"color": theme.accent}, {"style": "stroke"}, {"strokeWidth": 4.0},
                    {"strokeCap": "round"}])]
    for a, b in zip(pts, pts[1:]):
        cmds.append({"type": "drawline", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]})
    cmds.append(_paint([{"color": theme.accent}, {"style": "fill"}]))
    for (x, y), (label, v) in zip(pts, data):
        cmds.append({"type": "drawcircle", "cx": x, "cy": y, "radius": 7.0})
    cmds.append(_paint([{"color": theme.body_color}, {"style": "fill"}, {"textSize": 24.0}]))
    for (x, _), (label, v) in zip(pts, data):
        cmds.append(_text(label, x, pad + plot_h + 28, 24.0, theme.body_color))
    return cmds


def _pie(data, w, h, theme) -> list[dict]:
    total = sum(v for _, v in data) or 1.0
    r = min(w, h) / 2 - 60
    cx, cy = w / 2, h / 2
    left, top, right, bottom = cx - r, cy - r, cx + r, cy + r
    cmds = []
    angle = -90.0
    for i, (label, v) in enumerate(data):
        sweep = 360.0 * (v / total)
        cmds.append(_paint([{"color": PALETTE[i % len(PALETTE)]}, {"style": "fill"}]))
        cmds.append({"type": "drawsector", "left": round(left, 2), "top": round(top, 2),
                     "right": round(right, 2), "bottom": round(bottom, 2),
                     "startAngle": round(angle, 2), "sweepAngle": round(sweep, 2)})
        # Label at the mid-angle, just outside the arc.
        mid = math.radians(angle + sweep / 2)
        lx = cx + (r + 40) * math.cos(mid)
        ly = cy + (r + 40) * math.sin(mid)
        cmds.append(_paint([{"color": theme.body_color}, {"style": "fill"}, {"textSize": 24.0}]))
        cmds.append(_text(f"{label} {_fmt(v)}", lx, ly, 24.0, theme.body_color))
        angle += sweep
    return cmds


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:g}"

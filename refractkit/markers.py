"""Small vector markers shared by bullet points and progress-bar section marks.

A marker is one of four shapes — ``circle``, ``square``, ``four`` (four dots on the
diagonals, a Japanese-crest look), ``diamond`` — drawn either **filled** or as an
**outline**. Everything is emitted as canvas draw commands (paint + draw ops) so the same
code serves both a bullet glyph and a progress mark. Path-based shapes (diamond) take a
unique ``uid`` because path ids are document-global.
"""
from __future__ import annotations

import math

from .components import dbg

SHAPES = ("circle", "square", "four", "diamond", "asanoha", "quad", "hline", "vline")
_ALIASES = {"four-dots": "four", "fourdots": "four", "yotsume": "four", "crest": "four",
            "dots": "four", "hemp": "asanoha", "hemp-leaf": "asanoha", "hempleaf": "asanoha",
            "leaf": "asanoha", "four-square": "quad", "foursquare": "quad",
            "square-dots": "quad", "line-h": "hline", "horizontal": "hline", "dash": "hline",
            "line-v": "vline", "vertical": "vline", "bar": "vline"}


def normalize_shape(shape: str | None) -> str:
    s = (shape or "circle").lower()
    s = _ALIASES.get(s, s)
    return s if s in SHAPES else "circle"


def _paint(color: str, filled: bool, stroke_w: float) -> dict:
    ops = [{"color": color}, {"style": "fill" if filled else "stroke"}]
    if not filled:
        ops.append({"strokeWidth": stroke_w})
    return {"type": "paint", "ops": ops}


def _poly(pts: list, uid: str) -> list:
    out = [{"type": "pathcreate", "id": uid, "x": round(pts[0][0], 2), "y": round(pts[0][1], 2)}]
    for x, y in pts[1:]:
        out.append({"type": "pathappendlineto", "path": uid, "x": round(x, 2), "y": round(y, 2)})
    out.append({"type": "pathappendclose", "path": uid})
    out.append({"type": "drawpath", "path": uid})
    return out


def marker_commands(shape: str, cx: float, cy: float, r: float, color: str,
                    filled: bool, uid: str = "m") -> list:
    """Canvas commands drawing a marker of ``shape`` centred at (cx, cy) with radius ``r``."""
    shape = normalize_shape(shape)
    sw = max(1.4, round(r * 0.42, 2))          # outline stroke width, scaled to size
    p = _paint(color, filled, sw)
    if shape == "square":
        s = round(r * 0.9, 2)                  # side ~ circle diameter, a touch smaller
        return [p, {"type": "drawrect", "left": round(cx - s, 2), "top": round(cy - s, 2),
                    "right": round(cx + s, 2), "bottom": round(cy + s, 2)}]
    if shape == "diamond":
        pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        return [p, *_poly(pts, uid)]
    if shape == "four":
        # Four dots on the axes (top / right / bottom / left) — a diamond arrangement,
        # i.e. the square cluster rotated 45°.
        d = round(r * 0.62, 2)                 # dot centre offset along each axis
        dr = round(r * 0.40, 2)                # dot radius
        cmds = [p]
        for ox, oy in ((0, -d), (d, 0), (0, d), (-d, 0)):
            cmds.append({"type": "drawcircle", "cx": round(cx + ox, 2),
                         "cy": round(cy + oy, 2), "radius": dr})
        return cmds
    if shape == "quad":
        # Four dots at the corners (axis-aligned square cluster — the un-rotated `four`).
        d = round(r * 0.52, 2)
        dr = round(r * 0.40, 2)
        cmds = [p]
        for ox, oy in ((-d, -d), (d, -d), (-d, d), (d, d)):
            cmds.append({"type": "drawcircle", "cx": round(cx + ox, 2),
                         "cy": round(cy + oy, 2), "radius": dr})
        return cmds
    if shape in ("hline", "vline"):
        # A single stroke — filled has no effect.
        lw = max(1.6, round(r * 0.36, 2))
        if shape == "hline":
            a, b = (cx - r, cy), (cx + r, cy)
        else:
            a, b = (cx, cy - r), (cx, cy + r)
        return [_paint(color, False, lw),
                {"type": "drawline", "x1": round(a[0], 2), "y1": round(a[1], 2),
                 "x2": round(b[0], 2), "y2": round(b[1], 2)}]
    if shape == "asanoha":
        # A hemp-leaf unit: a hexagon with three diameters through the centre (a six-spoke
        # star). It's a line motif, so always stroked — the `filled` flag has no effect.
        v = [(cx + r * math.cos(math.radians(-90 + k * 60)),
              cy + r * math.sin(math.radians(-90 + k * 60))) for k in range(6)]
        line = lambda a, b: {"type": "drawline", "x1": round(a[0], 2), "y1": round(a[1], 2),
                             "x2": round(b[0], 2), "y2": round(b[1], 2)}
        cmds = [_paint(color, False, max(1.0, round(r * 0.16, 2)))]
        cmds += [line(v[k], v[(k + 1) % 6]) for k in range(6)]   # hexagon outline
        cmds += [line(v[k], v[k + 3]) for k in range(3)]         # three diameters (6 spokes)
        return cmds
    # circle (default)
    return [p, {"type": "drawcircle", "cx": round(cx, 2), "cy": round(cy, 2),
                "radius": round(r, 2)}]


def marker_canvas(shape: str, w: float, h: float, r: float, color: str, filled: bool,
                  debug: bool, uid: str = "m", cx: float | None = None,
                  cy: float | None = None) -> dict:
    """A ``w×h`` canvas node drawing a single marker (centred unless cx/cy given)."""
    cx = w / 2 if cx is None else cx
    cy = h / 2 if cy is None else cy
    return {"type": "canvas",
            "modifiers": dbg([{"width": round(float(w), 2)}, {"height": round(float(h), 2)}], debug),
            "commands": marker_commands(shape, cx, cy, r, color, filled, uid)}

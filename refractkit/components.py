"""Low-level RemoteCompose component builders shared across renderers."""

from __future__ import annotations

DEBUG_BORDER = {"border": {"width": 1.0, "cornerRadius": 0.0, "color": "#FFFF0000", "shape": 0}}


def dbg(mods: list, debug: bool) -> list:
    """Append a 1px red debug border to a modifier list when debug is on."""
    return mods + [DEBUG_BORDER] if debug else mods


def zigzag_edge(x0: float, x1: float, base: float, amp: float, tooth: float,
                sign: int) -> list:
    """Points of a triangle-wave edge from x0 to x1 along y=``base``, teeth of height ``amp``
    displaced by ``sign``. An even tooth count keeps both ends on the base line (y=base) so the
    corners meet the straight side edges cleanly."""
    length = abs(x1 - x0)
    steps = max(2, int(round(length / (tooth / 2.0))))
    if steps % 2:
        steps += 1
    pts = []
    for k in range(steps + 1):
        x = x0 + (x1 - x0) * k / steps
        y = base if k % 2 == 0 else base + sign * amp
        pts.append((round(x, 2), round(y, 2)))
    return pts


def torn_fill_commands(pid: str, w: float, h: float, top: bool, bottom: bool,
                       amp: float, tooth: float, color: str, outward: bool = False) -> list:
    """Canvas commands that fill the rect (0,0,w,h) in ``color`` with its ``top``/``bottom``
    edges torn into a zigzag (straight where not torn). ``outward=True`` makes the teeth spill
    beyond the rect (drawn behind a clipped viewport — the scroll case); otherwise the torn band
    stays inside [0,h] for a self-contained panel. Left/right edges are always straight."""
    s = -1 if outward else 1     # inward: valleys bite into the panel; outward: teeth spill out
    pts: list = []
    pts += zigzag_edge(0.0, w, 0.0, amp, tooth, s) if top else [(0.0, 0.0), (w, 0.0)]
    pts += zigzag_edge(w, 0.0, h, amp, tooth, -s) if bottom else [(w, h), (0.0, h)]
    cmds = [{"type": "pathcreate", "id": pid, "x": pts[0][0], "y": pts[0][1]}]
    cmds += [{"type": "pathappendlineto", "path": pid, "x": x, "y": yy} for x, yy in pts[1:]]
    cmds.append({"type": "pathappendclose", "path": pid})
    m = amp + 2.0
    cmds += [
        {"type": "paint", "ops": [{"color": color}, {"style": "fill"}]},
        {"type": "save", "commands": [
            {"type": "clippath", "path": pid},
            {"type": "drawrect", "left": 0.0, "top": (-m if outward else 0.0),
             "right": w, "bottom": (h + m if outward else h)}]},
    ]
    return cmds


def text(value: str, size: float, color: str, debug: bool,
         extra: list | None = None, mono: bool = False,
         family: str | None = None, weight: float | None = None) -> dict:
    """A Text component. ``mono`` selects monospace; ``family`` a named system font;
    ``weight`` a font weight (400 = regular, omitted)."""
    comp = {"type": "text", "value": value, "fontSize": size, "color": color}
    fam = "monospace" if mono else family
    if fam:
        comp["fontFamily"] = fam
    if weight and float(weight) != 400.0:
        comp["fontWeight"] = float(weight)
    mods = dbg(list(extra or []), debug)
    if mods:
        comp["modifiers"] = mods
    return comp

"""Image blocks: read dimensions and render as a contained canvas bitmap draw.

(The C++ viewer doesn't paint the image *layout* component yet, but it does paint
canvas bitmap draws — so an image is a fixed-size canvas that draws the embedded
bitmap into a computed, aspect-preserving rect. json2rc embeds the file inline.)
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess

from .components import dbg


def ensure_static_image(path: str) -> str:
    """Convert a .webp image to a static .png (in a hidden .converted/ folder beside the file):
    json2rc cannot read WebP. PNG, JPEG and GIF pass through untouched — json2rc embeds their
    bytes verbatim, and an animated GIF keeps its frames, which the C++ viewer plays in place.
    Returns the converted .png path, or the original path."""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".webp":
        return path
    if not os.path.isfile(path):
        return path
    conv_dir = os.path.join(os.path.dirname(os.path.abspath(path)), ".converted")
    out_path = os.path.join(conv_dir, os.path.basename(path) + ".png")
    try:
        src_mtime = os.path.getmtime(path)
        if os.path.isfile(out_path) and os.path.getmtime(out_path) >= src_mtime:
            return out_path
        os.makedirs(conv_dir, exist_ok=True)
        if shutil.which("sips"):
            subprocess.run(["sips", "-s", "format", "png", path, "--out", out_path],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.isfile(out_path):
                return out_path
    except (OSError, subprocess.SubprocessError):
        pass
    return path


def image_size(path: str) -> tuple[int, int]:
    """Return (width, height) for a PNG/JPEG/GIF/WebP, or (1, 1) if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(30)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return w, h
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                chunk = head[12:16]
                if chunk == b"VP8 " and len(head) >= 30:
                    w, h = struct.unpack("<HH", head[26:30])
                    return w & 0x3FFF, h & 0x3FFF
                if chunk == b"VP8L" and len(head) >= 25:
                    bits = struct.unpack("<I", head[21:25])[0]
                    return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
                if chunk == b"VP8X" and len(head) >= 30:
                    w = int.from_bytes(head[24:27], "little") + 1
                    h = int.from_bytes(head[27:30], "little") + 1
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


def _rounded_rect_path(path: str, l: float, t: float, r: float, b: float,
                       rad: float) -> list[dict]:
    """Canvas commands building a rounded-rect path (or 8-segment circle when fully round)."""
    w, h = r - l, b - t
    if rad >= min(w, h) / 2.0 - 0.5:
        cx, cy = (l + r) / 2.0, (t + b) / 2.0
        rx, ry = w / 2.0, h / 2.0
        k = 0.41421356  # tan(pi / 8)
        s = 0.70710678  # sqrt(2) / 2
        pts = [
            (cx + rx * k, cy - ry, cx + rx * s, cy - ry * s),
            (cx + rx, cy - ry * k, cx + rx, cy),
            (cx + rx, cy + ry * k, cx + rx * s, cy + ry * s),
            (cx + rx * k, cy + ry, cx, cy + ry),
            (cx - rx * k, cy + ry, cx - rx * s, cy + ry * s),
            (cx - rx, cy + ry * k, cx - rx, cy),
            (cx - rx, cy - ry * k, cx - rx * s, cy - ry * s),
            (cx - rx * k, cy - ry, cx, cy - ry),
        ]
        cmds = [{"type": "pathcreate", "id": path, "x": round(cx, 2), "y": round(cy - ry, 2)}]
        for x1, y1, x2, y2 in pts:
            cmds.append({"type": "pathappendquadto", "path": path,
                         "x1": round(x1, 2), "y1": round(y1, 2),
                         "x2": round(x2, 2), "y2": round(y2, 2)})
        cmds.append({"type": "pathappendclose", "path": path})
        return cmds
    return [
        {"type": "pathcreate", "id": path, "x": l + rad, "y": t},
        {"type": "pathappendlineto", "path": path, "x": r - rad, "y": t},
        {"type": "pathappendquadto", "path": path, "x1": r, "y1": t, "x2": r, "y2": t + rad},
        {"type": "pathappendlineto", "path": path, "x": r, "y": b - rad},
        {"type": "pathappendquadto", "path": path, "x1": r, "y1": b, "x2": r - rad, "y2": b},
        {"type": "pathappendlineto", "path": path, "x": l + rad, "y": b},
        {"type": "pathappendquadto", "path": path, "x1": l, "y1": b, "x2": l, "y2": b - rad},
        {"type": "pathappendlineto", "path": path, "x": l, "y": t + rad},
        {"type": "pathappendquadto", "path": path, "x1": l, "y1": t, "x2": l + rad, "y2": t},
        {"type": "pathappendclose", "path": path},
    ]


ZOOM_DUR = 0.55      # seconds a zoom keyframe takes to settle — as rcskia/MediaZoom.h


def _zoom_vars(keys: list, prefix: str, clock: str = "animTime") -> tuple[list, dict]:
    """Expressions for a keyframed zoom on the slide's clock: the variables to declare and the
    names holding the view's centre (``cx``, ``cy``, fractions) and zoom (``z``).

    The same motion as rcskia/MediaZoom.h: before the first key the whole frame; at each key
    an ease (quart out, ZOOM_DUR) from wherever the view is to the key's centre and zoom, zoom
    in log space; the view clamped inside the frame. Each key's starting point is known when the
    slide is built (the keys' times are fixed), so the view is the first key's start plus, per
    key, its change times its ease — each ease stopping where the next key takes over."""
    import math
    ease = lambda u: 1.0 - (1.0 - min(max(u, 0.0), 1.0)) ** 4
    frm = to = (0.5, 0.5, 0.0)
    t0 = -1e9
    segs = []
    for t, x, y, z in keys:
        e = ease((t - t0) / ZOOM_DUR)
        frm = tuple(a + (b - a) * e for a, b in zip(frm, to))
        to = (x, y, math.log(max(z, 1.0)))
        segs.append((t, frm, to))
        t0 = t
    vs, names = [], {}
    V = lambda n, v: vs.append({"type": "variable", "name": n, "vtype": "float", "value": v})
    terms = {0: [], 1: [], 2: []}
    for i, (t, frm, to) in enumerate(segs):
        end = segs[i + 1][0] if i + 1 < len(segs) else None
        tt = "min(%s,%g)" % (clock, end) if end is not None else clock
        V(f"{prefix}U{i}", "clamp((%s-%g)*%g,1.0,0.0)" % (tt, t, 1.0 / ZOOM_DUR))
        V(f"{prefix}N{i}", f"1.0-{prefix}U{i}")
        V(f"{prefix}E{i}", f"1.0-{prefix}N{i}*{prefix}N{i}*{prefix}N{i}*{prefix}N{i}")
        for a in range(3):
            d = to[a] - frm[a]
            if abs(d) > 1e-6:
                terms[a].append("%g*%sE%d" % (d, prefix, i))
    base = (0.5, 0.5, 0.0)
    for a, nm in ((0, "X"), (1, "Y"), (2, "L")):
        prev = "%g" % base[a]
        ts = terms[a]
        for c in range(0, max(len(ts), 1), 3):
            chunk = ts[c:c + 3]
            name = f"{prefix}{nm}{c // 3}"
            V(name, prev + ("+" + "+".join(chunk) if chunk else "+0.0"))
            prev = name
        names[nm] = prev
    V(f"{prefix}Z", f"exp({names['L']})")
    V(f"{prefix}H", f"0.5/{prefix}Z")
    V(f"{prefix}CX", f"clamp({names['X']},1.0-{prefix}H,{prefix}H)")
    V(f"{prefix}CY", f"clamp({names['Y']},1.0-{prefix}H,{prefix}H)")
    return vs, {"cx": f"{prefix}CX", "cy": f"{prefix}CY", "z": f"{prefix}Z", "h": f"{prefix}H"}


def render_image(block: dict, theme, debug: bool, avail_w: float, avail_h: float,
                 counter: list, align: str = "center") -> list[dict]:
    """A fixed-size canvas that draws the image contained within (avail_w, avail_h),
    optionally clipped to a rounded rect (theme.image_corner_radius)."""
    opts = block.get("opts") or {}
    img_path = ensure_static_image(block["path"])
    iw, ih = image_size(img_path)

    if "width" in opts and "height" in opts:
        dw, dh = float(opts["width"]), float(opts["height"])
        cw = float(avail_w) if opts.get("fill_width") else dw
        ch = dh
    elif "width" in opts:
        dw = float(opts["width"])
        dh = round(dw * ih / iw, 2) if iw else dw
        cw = float(avail_w) if opts.get("fill_width") else dw
        ch = dh
    elif "height" in opts:
        dh = float(opts["height"])
        dw = round(dh * iw / ih, 2) if ih else dh
        cw = float(avail_w) if opts.get("fill_width") else dw
        ch = dh
    else:
        cw, ch = float(avail_w), float(avail_h)
        scale = min(cw / iw, ch / ih)
        dw, dh = iw * scale, ih * scale

    opt_align = opts.get("align", opts.get("h_align", align))
    if opt_align in ("start", "left"):
        left = 0.0
    elif opt_align in ("end", "right"):
        left = round(cw - dw, 2)
    else:
        left = round((cw - dw) / 2.0, 2)

    top = round((ch - dh) / 2.0, 2)
    right, bottom = round(left + dw, 2), round(top + dh, 2)
    counter[0] += 1
    var = f"__img{counter[0]}"

    draw = {"type": "drawbitmap", "image": "$" + var,
            "left": left, "top": top, "right": right, "bottom": bottom}
    commands = [{"type": "addbitmap", "image": img_path, "varName": var}]
    # Zoom keyframes (``zooms``, or a static ``zoom``/``focus``): the bitmap drawn larger and
    # shifted so the view's window fills the image's own box, clipped to it, on the slide's clock.
    zvars: list = []
    if block.get("zooms"):
        zvars, zn = _zoom_vars(block["zooms"], f"__z{counter[0]}_")
        L = f"{left}-({zn['cx']}-{zn['h']})*{dw:.2f}*{zn['z']}"
        T = f"{top}-({zn['cy']}-{zn['h']})*{dh:.2f}*{zn['z']}"
        zvars += [{"type": "variable", "name": f"__z{counter[0]}_L", "vtype": "float", "value": L},
                  {"type": "variable", "name": f"__z{counter[0]}_T", "vtype": "float", "value": T}]
        zl, zt = f"__z{counter[0]}_L", f"__z{counter[0]}_T"
        draw = {"type": "save", "commands": [
            {"type": "cliprect", "left": left, "top": top, "right": right, "bottom": bottom},
            {"type": "drawbitmap", "image": "$" + var, "left": zl, "top": zt,
             "right": f"{zl}+{dw:.2f}*{zn['z']}", "bottom": f"{zt}+{dh:.2f}*{zn['z']}"}]}
    raw_rad = opts.get("radius", opts.get("corner_radius", opts.get("clip", theme.image_corner_radius)))
    if str(raw_rad).lower() in ("circle", "ellipse", "round"):
        rad = min(dw / 2.0, dh / 2.0)
    else:
        try:
            rad = min(float(raw_rad), dw / 2.0, dh / 2.0)
        except (TypeError, ValueError):
            rad = 0.0
    if rad > 0.5:
        clip = f"__imgclip{counter[0]}"
        commands += _rounded_rect_path(clip, left, top, right, bottom, round(rad, 2))
        commands.append({"type": "save", "commands": [
            {"type": "clippath", "path": clip}, draw]})
    else:
        commands.append(draw)
    canvas = {
        "type": "canvas",
        "modifiers": dbg([{"width": cw}, {"height": ch}], debug),
        "commands": commands,
    }
    if zvars:
        return [{"type": "box", "modifiers": dbg([{"width": cw}, {"height": ch}], debug),
                 "children": zvars + [canvas]}]
    return [canvas]

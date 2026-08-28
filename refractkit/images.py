"""Image blocks: read dimensions and render as a contained canvas bitmap draw.

(The C++ viewer doesn't paint the image *layout* component yet, but it does paint
canvas bitmap draws — so an image is a fixed-size canvas that draws the embedded
bitmap into a computed, aspect-preserving rect. json2rc embeds the file inline.)
"""

from __future__ import annotations

import struct

from .components import dbg


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


def _rounded_rect_path(path: str, l: float, t: float, r: float, b: float,
                       rad: float) -> list[dict]:
    """Canvas commands building a rounded-rect path (quad corners)."""
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


def render_image(block: dict, theme, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    """A fixed-size canvas that draws the image contained within (avail_w, avail_h),
    optionally clipped to a rounded rect (theme.image_corner_radius)."""
    iw, ih = image_size(block["path"])
    cw, ch = float(avail_w), float(avail_h)
    scale = min(cw / iw, ch / ih)
    dw, dh = iw * scale, ih * scale
    left = round((cw - dw) / 2.0, 2)
    top = round((ch - dh) / 2.0, 2)
    right, bottom = round(left + dw, 2), round(top + dh, 2)
    counter[0] += 1
    var = f"__img{counter[0]}"

    draw = {"type": "drawbitmap", "image": "$" + var,
            "left": left, "top": top, "right": right, "bottom": bottom}
    commands = [{"type": "addbitmap", "image": block["path"], "varName": var}]
    rad = min(float(theme.image_corner_radius), dw / 2.0, dh / 2.0)
    if rad > 0.5:
        clip = f"__imgclip{counter[0]}"
        commands += _rounded_rect_path(clip, left, top, right, bottom, round(rad, 2))
        commands.append({"type": "save", "commands": [
            {"type": "clippath", "path": clip}, draw]})
    else:
        commands.append(draw)
    return [{
        "type": "canvas",
        "modifiers": dbg([{"width": cw}, {"height": ch}], debug),
        "commands": commands,
    }]

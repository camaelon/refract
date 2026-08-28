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


def render_image(block: dict, debug: bool, avail_w: float, avail_h: float,
                 counter: list) -> list[dict]:
    """A fixed-size canvas that draws the image contained within (avail_w, avail_h)."""
    iw, ih = image_size(block["path"])
    cw = float(avail_w)
    ch = float(avail_h)
    scale = min(cw / iw, ch / ih)
    dw, dh = iw * scale, ih * scale
    left = round((cw - dw) / 2.0, 2)
    top = round((ch - dh) / 2.0, 2)
    counter[0] += 1
    var = f"__img{counter[0]}"
    return [{
        "type": "canvas",
        "modifiers": dbg([{"width": cw}, {"height": ch}], debug),
        "commands": [
            {"type": "addbitmap", "image": block["path"], "varName": var},
            {"type": "drawbitmap", "image": "$" + var,
             "left": left, "top": top,
             "right": round(left + dw, 2), "bottom": round(top + dh, 2)},
        ],
    }]

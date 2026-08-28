import os
import struct
import tempfile
import unittest

from refractkit import images
from refractkit.theme import build_theme


def _png(path, w, h):
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h))


class ImageSize(unittest.TestCase):
    def test_png(self):
        p = os.path.join(tempfile.mkdtemp(), "a.png")
        _png(p, 320, 240)
        self.assertEqual(images.image_size(p), (320, 240))

    def test_unknown(self):
        p = os.path.join(tempfile.mkdtemp(), "x.bin")
        with open(p, "wb") as f:
            f.write(b"not an image")
        self.assertEqual(images.image_size(p), (1, 1))


class RenderImage(unittest.TestCase):
    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "sq.png")
        _png(self.p, 100, 100)   # square
        self.theme = build_theme({})

    def test_canvas_with_bitmap(self):
        out = images.render_image({"path": self.p}, self.theme, False, 800, 400, [0])
        cv = out[0]
        self.assertEqual(cv["type"], "canvas")
        types = [c["type"] for c in cv["commands"]]
        self.assertIn("addbitmap", types)
        self.assertIn("drawbitmap", types)

    def test_contained_centered(self):
        # square image into 800x400 -> fits height 400, centered horizontally
        out = images.render_image({"path": self.p}, self.theme, False, 800, 400, [0])
        draw = [c for c in out[0]["commands"] if c["type"] == "drawbitmap"][0]
        self.assertAlmostEqual(draw["bottom"] - draw["top"], 400, delta=1)
        self.assertAlmostEqual(draw["right"] - draw["left"], 400, delta=1)
        self.assertAlmostEqual(draw["left"], (800 - 400) / 2, delta=1)

    def test_rounded_clip_commands(self):
        theme = build_theme({"image": {"corner_radius": 20}})
        out = images.render_image({"path": self.p}, theme, False, 800, 400, [0])
        types = [c["type"] for c in out[0]["commands"]]
        self.assertIn("pathcreate", types)
        self.assertIn("save", types)   # drawbitmap nested under save+clippath

    def test_rounded_rect_path_closed(self):
        cmds = images._rounded_rect_path("p", 0, 0, 100, 50, 10)
        self.assertEqual(cmds[0]["type"], "pathcreate")
        self.assertEqual(cmds[-1]["type"], "pathappendclose")
        self.assertIn("pathappendquadto", [c["type"] for c in cmds])


if __name__ == "__main__":
    unittest.main()

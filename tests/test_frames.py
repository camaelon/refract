"""Device frames: ``[frames.<name>]`` in the theme, ``frame=<name>`` on an include."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from refractkit import render
from refractkit.deck import _apply_include_opts
from refractkit.theme import Theme

FRAME = {"image": "/nonexistent/frame.png", "bounds": [100.0, 0.0, 500.0, 800.0],
         "screen": [120.0, 20.0, 480.0, 780.0], "radius": 40.0, "fit": "fill",
         "screen_color": "#FF000000"}


def find(node, pred):
    if isinstance(node, dict):
        if pred(node):
            return node
        for v in node.values():
            r = find(v, pred)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = find(v, pred)
            if r:
                return r
    return None


class Frames(unittest.TestCase):
    def test_option_names_the_frame(self):
        b = _apply_include_opts({"kind": "video", "path": "a.mp4"}, {"frame": "Android"})
        self.assertEqual(b["frame"], "android")
        b = _apply_include_opts({"kind": "video", "path": "a.mp4"}, {"frame": "none"})
        self.assertNotIn("frame", b)

    def test_geometry_scales_screen_into_device_box(self):
        theme = Theme()
        theme.frames = {"android": FRAME}
        block = {"kind": "video", "path": "/x/clip.mp4", "frame": "android"}
        out = render.render_video(block, theme, False, 1000.0, 400.0)
        # The device is 400x800 (1:2): at 400 tall it is 200 wide, so k = 0.5.
        device = find(out, lambda n: n.get("type") == "box" and {"width": 200.0} in n.get("modifiers", []))
        self.assertIsNotNone(device)
        pad = find(device, lambda n: any(isinstance(m, dict) and "padding" in m for m in n.get("modifiers", [])))
        self.assertEqual(pad["modifiers"][0]["padding"], [10.0, 10.0, 0.0, 0.0])
        screen = pad["children"][0]
        self.assertIn({"width": 180.0}, screen["modifiers"])
        self.assertIn({"height": 380.0}, screen["modifiers"])
        self.assertIn({"clip": 20.0}, screen["modifiers"])
        video = find(screen, lambda n: n.get("type") == "custom")
        self.assertIn("fit=fill", video["config"])
        art = find(device, lambda n: n.get("type") == "canvas")
        draw = find(art, lambda n: n.get("type") == "drawbitmap")
        self.assertEqual(draw["left"], -50.0)     # bounds.left * k: the device meets the box


if __name__ == "__main__":
    unittest.main()

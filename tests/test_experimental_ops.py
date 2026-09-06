"""EXPERIMENTAL operations end to end: JSON -> json2rc -> .rc -> rc2image (the rcX C++ player).

  xcompact path resources   render pixel-identical to the standard encoding, in fewer bytes
  xBlur paint op            softens the edge of a fill and leaves its interior alone
  xDrawPathStrip            paints a ribbon whose thickness follows the diameters

Needs the rebuilt json2rc (json2rc/build/install) and the rcX rc2image; skipped when absent.
See json2rc/EXPERIMENTAL.md."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
J2RC = os.path.join(HERE, "..", "json2rc", "build", "install", "json2rc", "bin", "json2rc")
RC2IMAGE = os.environ.get("RC2IMAGE", os.path.expanduser(
    "~/Documents/GitHub/remotecompose-experiments/players/cpp/build/tools/rc2image/rc2image"))

OPS = [{"type": "moveTo", "x": 20, "y": 30},
       {"type": "cubicTo", "x1": 60, "y1": 5, "x2": 110, "y2": 55, "x3": 150, "y3": 30},
       {"type": "lineTo", "x": 160, "y": 90},
       {"type": "quadTo", "x1": 90, "y1": 120, "x2": 30, "y2": 95},
       {"type": "close"}]


def doc(paths, cmds):
    return {"header": {"width": 180, "height": 130},
            "root": {"global": [{"resources": {"paths": paths}},
                                {"type": "canvas", "modifiers": [{"size": [180, 130]}], "commands": cmds}]}}


@unittest.skipUnless(os.path.exists(J2RC) and os.path.exists(RC2IMAGE), "json2rc / rc2image not built")
class ExperimentalOps(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        import numpy as np  # noqa: F401  (PIL + numpy are test-time dependencies)
        from PIL import Image  # noqa: F401

    def compile(self, d, tag):
        import numpy as np
        from PIL import Image
        js = os.path.join(self.dir, tag + ".json"); rc = os.path.join(self.dir, tag + ".rc"); png = os.path.join(self.dir, tag + ".png")
        json.dump(d, open(js, "w"))
        r = subprocess.run([J2RC, js, rc], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)
        subprocess.run([RC2IMAGE, rc, png, "180", "130"], capture_output=True, check=True)
        return os.path.getsize(rc), np.asarray(Image.open(png).convert("RGB"), float)

    def test_compact_path_is_smaller_and_identical(self):
        import numpy as np
        fill = [{"paint": {"ops": [{"style": "fill"}, {"color": "#3060C0"}]}}, {"drawPath": "@paths.p"}]
        n0, a = self.compile(doc([{"p": OPS}], fill), "std")
        n1, b = self.compile(doc([{"p": {"value": OPS, "encoding": "xcompact", "quantum": 0.0625}}], fill), "compact")
        self.assertLess(n1, n0 - 40, f"compact {n1} B should be well under standard {n0} B")
        self.assertLess(np.sqrt(((a - b) ** 2).mean()), 0.5, "compact and standard paths render the same")

    def test_blur_softens_edges_only(self):
        n0, a = self.compile(doc([{"p": OPS}], [{"paint": {"ops": [{"style": "fill"}, {"color": "#3060C0"}]}}, {"drawPath": "@paths.p"}]), "crisp")
        n1, b = self.compile(doc([{"p": OPS}], [{"paint": {"ops": [{"style": "fill"}, {"color": "#3060C0"}, {"xBlur": 3.0}]}}, {"drawPath": "@paths.p"}]), "blur")
        self.assertGreater(abs(a - b).max(), 40, "the blur must change edge pixels")
        self.assertLess(abs(a[60, 90] - b[60, 90]).max(), 3, "the interior keeps its colour")

    def test_compact_gradient_is_smaller_and_identical(self):
        import numpy as np
        cols = ["#F4FF62", "#F5FF6B", "#F6F888", "#F9F0B2", "#FEFEFF", "#F4CC60", "#BD7528", "#7A1E00"]; st = [0, .2, .4, .6, .8, .9, .96, 1.0]
        def grad(x): return [{"paint": {"ops": [{"style": "fill"}, {"radialGradient": {"centerX": 90, "centerY": 65, "radius": 70, "colors": cols, "stops": st, **({"xcompact": True} if x else {})}}]}}, {"drawPath": "@paths.p"},
                             {"paint": {"ops": [{"style": "fill"}, {"linearGradient": {"x1": 0, "y1": 0, "x2": 180, "y2": 130, "colors": ["#80FF0000", "#000000FF"], "stops": [0, 1], **({"xcompact": True} if x else {})}}]}}, {"drawPath": "@paths.p"}]
        n0, a = self.compile(doc([{"p": OPS}], grad(False)), "grad"); n1, b = self.compile(doc([{"p": OPS}], grad(True)), "gradx")
        self.assertLess(n1, n0 - 40, f"compact gradients {n1} B should be well under {n0} B")
        self.assertLess(np.sqrt(((a - b) ** 2).mean()), 1.0, "compact and standard gradients render the same")

    def test_path_strip_width_follows_diameters(self):
        import numpy as np
        line = [{"type": "moveTo", "x": 15, "y": 65}, {"type": "lineTo", "x": 165, "y": 65}]
        n, im = self.compile(doc([{"l": line}], [{"paint": {"ops": [{"style": "fill"}, {"color": "#C03020"}]}}, {"xDrawPathStrip": {"path": "@paths.l", "diameters": [2, 14]}}]), "strip")
        ink = im.sum(2) < 600
        self.assertGreater(ink.sum(), 300, "the strip paints something")
        self.assertLess(int(ink[:, 25].sum()), int(ink[:, 155].sum()) - 6, "the ribbon is thicker at the wide end")


if __name__ == "__main__":
    unittest.main()

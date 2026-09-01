import unittest

from refractkit import markers


def _draw_ops(cmds):
    return [c["type"] for c in cmds if c.get("type") != "paint"]


def _paint_style(cmds):
    p = next(c for c in cmds if c["type"] == "paint")
    return next(o["style"] for o in p["ops"] if "style" in o)


class Markers(unittest.TestCase):
    def test_shapes_use_expected_primitives(self):
        self.assertEqual(_draw_ops(markers.marker_commands("circle", 10, 10, 5, "#F00", True)),
                         ["drawcircle"])
        self.assertEqual(_draw_ops(markers.marker_commands("square", 10, 10, 5, "#F00", True)),
                         ["drawrect"])
        # four dots → four circles
        self.assertEqual(_draw_ops(markers.marker_commands("four", 10, 10, 5, "#F00", True)),
                         ["drawcircle"] * 4)
        # diamond → a closed path
        ops = _draw_ops(markers.marker_commands("diamond", 10, 10, 5, "#F00", True))
        self.assertIn("drawpath", ops)
        self.assertIn("pathcreate", ops)
        # asanoha → a line motif: hexagon (6 edges) + three diameters = 9 lines
        ops = _draw_ops(markers.marker_commands("asanoha", 20, 20, 10, "#F00", True))
        self.assertEqual(ops, ["drawline"] * 9)

    def test_asanoha_is_always_stroked(self):
        # It's a line motif — filled=True still strokes.
        self.assertEqual(_paint_style(markers.marker_commands("asanoha", 20, 20, 10, "#F00", True)),
                         "stroke")

    def test_quad_and_lines(self):
        # quad = four corner dots (un-rotated four)
        self.assertEqual(_draw_ops(markers.marker_commands("quad", 10, 10, 5, "#F00", True)),
                         ["drawcircle"] * 4)
        # hline / vline = a single stroked line
        for sh in ("hline", "vline"):
            cmds = markers.marker_commands(sh, 10, 10, 5, "#F00", True)
            self.assertEqual(_draw_ops(cmds), ["drawline"])
            self.assertEqual(_paint_style(cmds), "stroke")
        h = markers.marker_commands("hline", 10, 10, 5, "#F00", True)[1]
        self.assertEqual((h["y1"], h["y2"]), (10, 10))     # horizontal
        v = markers.marker_commands("vline", 10, 10, 5, "#F00", True)[1]
        self.assertEqual((v["x1"], v["x2"]), (10, 10))     # vertical

    def test_more_aliases(self):
        self.assertEqual(markers.normalize_shape("four-square"), "quad")
        self.assertEqual(markers.normalize_shape("horizontal"), "hline")
        self.assertEqual(markers.normalize_shape("vertical"), "vline")

    def test_filled_vs_outline_paint_style(self):
        self.assertEqual(_paint_style(markers.marker_commands("circle", 10, 10, 5, "#F00", True)),
                         "fill")
        self.assertEqual(_paint_style(markers.marker_commands("circle", 10, 10, 5, "#F00", False)),
                         "stroke")

    def test_outline_has_stroke_width(self):
        cmds = markers.marker_commands("square", 10, 10, 5, "#F00", False)
        p = next(c for c in cmds if c["type"] == "paint")
        self.assertTrue(any("strokeWidth" in o for o in p["ops"]))

    def test_aliases_and_unknown_fall_back(self):
        self.assertEqual(markers.normalize_shape("yotsume"), "four")
        self.assertEqual(markers.normalize_shape("four-dots"), "four")
        self.assertEqual(markers.normalize_shape("hemp-leaf"), "asanoha")
        self.assertEqual(markers.normalize_shape("bogus"), "circle")
        self.assertEqual(markers.normalize_shape(None), "circle")

    def test_diamond_uid_flows_into_path_id(self):
        cmds = markers.marker_commands("diamond", 10, 10, 5, "#F00", True, uid="pm3")
        pc = next(c for c in cmds if c["type"] == "pathcreate")
        self.assertEqual(pc["id"], "pm3")


if __name__ == "__main__":
    unittest.main()

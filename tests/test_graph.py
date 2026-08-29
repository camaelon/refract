import shutil
import unittest

from refractkit import graph
from refractkit.theme import build_theme

HAS_DOT = shutil.which("dot") is not None
DOT = "digraph G { rankdir=LR; A -> B; B -> C }"


class PureHelpers(unittest.TestCase):
    def test_lerp_equal_is_number(self):
        self.assertEqual(graph._lerp(5.0, 5.0, "$t"), 5.0)

    def test_lerp_different_is_expr(self):
        expr = graph._lerp(0.0, 10.0, "$t")
        self.assertIsInstance(expr, str)
        self.assertIn("$t", expr)

    def test_sample_spline(self):
        pts = [(0, 0), (0, 10), (10, 10), (10, 0)]   # one cubic
        out = graph._sample_spline(pts, 4)
        self.assertEqual(out[0], (0, 0))
        self.assertEqual(len(out), 5)                # start + 4 samples

    def test_resample_count_and_endpoints(self):
        poly = [(0, 0), (10, 0)]
        out = graph._resample(poly, 5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0], (0, 0))
        self.assertEqual(out[-1], (10, 0))
        self.assertAlmostEqual(out[2][0], 5.0, delta=0.01)


@unittest.skipUnless(HAS_DOT, "graphviz `dot` not installed")
class WithGraphviz(unittest.TestCase):
    def setUp(self):
        self.theme = build_theme({})

    def test_run_dot(self):
        g = graph.run_dot(DOT, "dot")
        self.assertIsNotNone(g)
        self.assertIn("objects", g)

    def test_geometry_nodes_and_edges(self):
        geo = graph.graph_geometry({"dot": DOT, "engine": "dot"}, 800, 600)
        self.assertEqual(set(geo["nodes"]), {"A", "B", "C"})
        self.assertIn(("A", "B"), geo["edges"])
        self.assertIn(("B", "C"), geo["edges"])

    def test_render_graph_structure(self):
        out = graph.render_graph({"dot": DOT, "engine": "dot"}, self.theme, False, 800, 600, [0])
        self.assertEqual(out[0]["type"], "canvas")
        types = {c["type"] for c in out[0]["commands"]}
        self.assertIn("drawroundrect", types)
        self.assertIn("drawtextanchored", types)

    def test_morph_lerps_matched_nodes(self):
        a = {"dot": "digraph{ rankdir=LR; A->B }", "engine": "dot"}
        b = {"dot": "digraph{ rankdir=LR; A->B; B->C }", "engine": "dot"}
        out = graph.render_graph_morph(a, b, self.theme, False, 800, 600, "$t")
        cmds = out[0]["commands"]
        # A moves between layouts -> at least one rounded rect uses an expr coordinate
        has_expr = any(c["type"] == "drawroundrect" and isinstance(c.get("left"), str)
                       for c in cmds)
        self.assertTrue(has_expr)

    def test_morph_fallback_when_no_prev(self):
        out = graph.render_graph_morph(None, {"dot": DOT, "engine": "dot"},
                                       self.theme, False, 800, 600, "$t")
        self.assertEqual(out[0]["type"], "canvas")


class Styling(unittest.TestCase):
    def test_norm_color(self):
        self.assertEqual(graph._norm_color("#ff5555"), "#FFFF5555")
        self.assertIsNone(graph._norm_color("#000000"))   # default black -> theme
        self.assertIsNone(graph._norm_color(None))

    def test_parse_style(self):
        dash, wid = graph._parse_style("dashed", 1.0, None, None)
        self.assertTrue(dash and len(dash) == 2)
        dash, wid = graph._parse_style("setlinewidth(3)", 1.0, None, None)
        self.assertEqual(wid, 3.0)


@unittest.skipUnless(HAS_DOT, "graphviz `dot` not installed")
class ClustersAndStyles(unittest.TestCase):
    DOT = ('digraph G { rankdir=LR; subgraph cluster_0 { label="Grp"; A; B } '
           'A -> B [style=dashed]; A -> C [color="#ff5555"]; }')

    def test_cluster_extracted(self):
        geo = graph.graph_geometry({"dot": self.DOT, "engine": "dot"}, 800, 600)
        self.assertEqual(len(geo["clusters"]), 1)
        self.assertEqual(geo["clusters"][0]["label"], "Grp")

    def test_edge_dash_and_color(self):
        geo = graph.graph_geometry({"dot": self.DOT, "engine": "dot"}, 800, 600)
        self.assertTrue(geo["edges"][("A", "B")]["dash"])
        self.assertEqual(geo["edges"][("A", "C")]["color"], "#FFFF5555")


if __name__ == "__main__":
    unittest.main()

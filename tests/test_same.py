import unittest

from refractkit import render
from refractkit.samematch import diff_slides
from refractkit.theme import build_theme

THEME = build_theme({})


class Diff(unittest.TestCase):
    def test_appearing_bullet(self):
        prev = [{"kind": "bullets", "items": [{"level": 0, "text": "a"}]}]
        cur = [{"kind": "bullets", "items": [{"level": 0, "text": "a"},
                                             {"level": 0, "text": "b"}]}]
        d = diff_slides(prev, cur)
        self.assertIn((0, "b"), d["bullets_new"])
        self.assertNotIn((0, "a"), d["bullets_new"])

    def test_graph_changed(self):
        prev = [{"kind": "graph", "dot": "digraph{A->B}"}]
        cur = [{"kind": "graph", "dot": "digraph{A->B->C}"}]
        self.assertTrue(diff_slides(prev, cur)["graph_changed"])

    def test_graph_unchanged(self):
        g = [{"kind": "graph", "dot": "digraph{A->B}"}]
        self.assertFalse(diff_slides(g, list(g))["graph_changed"])

    def test_new_block(self):
        prev = [{"kind": "text", "text": "x"}]
        cur = [{"kind": "text", "text": "x"}, {"kind": "image", "path": "/p.png"}]
        d = diff_slides(prev, cur)
        self.assertIn(("image", "/p.png"), d["blocks_new"])


class BuildSameDoc(unittest.TestCase):
    def test_progress_vars_and_structure(self):
        prev = ({"title": "A"}, [{"kind": "bullets", "items": [{"level": 0, "text": "a"}]}])
        cur = ({"title": "A", "meta": {"type": "same"}},
               [{"kind": "bullets", "items": [{"level": 0, "text": "a"},
                                              {"level": 0, "text": "b"}]}])
        doc = render.build_same_doc(prev, cur, THEME, 1600, 900, 1, False, total=2)
        names = {n.get("name") for n in doc["root"] if isinstance(n, dict) and n.get("type") == "variable"}
        self.assertEqual(names, {"__sp", "__st"})
        import json
        s = json.dumps(doc)
        self.assertIn("graphicsLayer", s)   # appearing bullet fades in


if __name__ == "__main__":
    unittest.main()

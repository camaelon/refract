import unittest

from refractkit import render
from refractkit.theme import build_theme


def _find(node, pred):
    """Depth-first search for the first node matching pred."""
    if isinstance(node, dict):
        if pred(node):
            return node
        for v in node.values():
            r = _find(v, pred)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find(v, pred)
            if r is not None:
                return r
    return None


def _texts(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n["value"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


class Chrome(unittest.TestCase):
    def test_none_by_default(self):
        theme = build_theme({})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False, total=3)
        # no chrome -> root is the plain column, not a wrapping box overlay
        self.assertEqual(doc["root"]["type"], "column")

    def test_page_number(self):
        theme = build_theme({"chrome": {"page": True}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 1, False, total=5)
        self.assertIn("2 / 5", _texts(doc["root"]))

    def test_footer(self):
        theme = build_theme({"chrome": {"footer": "MyConf"}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False, total=3)
        self.assertIn("MyConf", _texts(doc["root"]))

    def test_progress_fraction(self):
        theme = build_theme({"chrome": {"progress": True}})
        doc = render.build_doc({"title": "T"}, [], theme, 1000, 900, 1, False, total=4)
        # filled width = width * (index+1)/total = 1000 * 2/4 = 500
        bar = _find(doc["root"], lambda n: any(
            isinstance(m, dict) and m.get("width") == 500.0 for m in n.get("modifiers", [])))
        self.assertIsNotNone(bar)

    def test_bottom_anchored(self):
        theme = build_theme({"chrome": {"page": True}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False, total=3)
        overlay = _find(doc["root"], lambda n: n.get("verticalAlignment") == "bottom")
        self.assertIsNotNone(overlay)


if __name__ == "__main__":
    unittest.main()

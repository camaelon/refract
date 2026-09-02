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
        # The connecting line is split at the progress point: fx = 1000 * 2/4 = 500. A line
        # segment (drawrect) should end (or start) exactly there.
        edges = []
        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "canvas":
                    for c in n.get("commands", []):
                        if isinstance(c, dict) and c.get("type") == "drawrect":
                            edges.extend([c.get("left"), c.get("right")])
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(doc["root"])
        self.assertIn(500.0, edges)

    def test_bottom_anchored(self):
        theme = build_theme({"chrome": {"page": True}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False, total=3)
        overlay = _find(doc["root"], lambda n: n.get("verticalAlignment") == "bottom")
        self.assertIsNotNone(overlay)

    def test_title_slide_has_no_chrome(self):
        # The title slide is a clean cover: no footer / page / progress overlay.
        theme = build_theme({"chrome": {"footer": "Conf", "page": True, "progress": True}})
        doc = render.build_doc({"title": "T", "meta": {"type": "title"}}, [],
                               theme, 1600, 900, 0, False, total=3)
        self.assertNotIn("Conf", _texts(doc["root"]))
        self.assertNotIn("1 / 3", _texts(doc["root"]))

    def test_author_tag_shown_in_accent(self):
        # A slide attributed to an author shows the author name in the accent colour,
        # even without other chrome enabled.
        from dataclasses import replace
        theme = replace(build_theme({}), slide_author="Nico", accent="#FF5CC8FF")
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False, total=3)
        self.assertIn("Nico", _texts(doc["root"]))
        tag = _find(doc["root"], lambda n: n.get("value") == "Nico")
        self.assertEqual(tag["color"], "#FF5CC8FF")


if __name__ == "__main__":
    unittest.main()

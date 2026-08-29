import json
import os
import tempfile
import unittest

from refractkit import render
from refractkit.theme import build_theme

THEME = build_theme({})
SPEC = render.SLIDE_TYPES["content"]


def _json_doc(root):
    p = os.path.join(tempfile.mkdtemp(), "d.json")
    with open(p, "w") as f:
        json.dump({"header": {}, "root": root}, f)
    return p


class SlideType(unittest.TestCase):
    def test_types(self):
        self.assertEqual(render.slide_type({"meta": {"type": "title"}}), "title")
        self.assertEqual(render.slide_type({"meta": {"type": "section"}}), "section")
        self.assertEqual(render.slide_type({}), "content")
        self.assertEqual(render.slide_type({"meta": {"type": "bogus"}}), "content")


class Helpers(unittest.TestCase):
    def test_split_panes(self):
        blocks = [{"kind": "text"}, {"kind": "pane_break"}, {"kind": "image"}]
        panes = render.split_panes(blocks)
        self.assertEqual(len(panes), 2)
        self.assertEqual(panes[0][0]["kind"], "text")
        self.assertEqual(panes[1][0]["kind"], "image")

    def test_graph_block(self):
        self.assertIsNone(render.graph_block([{"kind": "text"}]))
        g = {"kind": "graph"}
        self.assertIs(render.graph_block([{"kind": "text"}, g]), g)


class RenderBlock(unittest.TestCase):
    def rb(self, block):
        return render.render_block(block, 40.0, THEME, False, 800, 400, [0])

    def test_text(self):
        out = self.rb({"kind": "text", "text": "hello"})
        self.assertEqual(out[0]["type"], "text")
        self.assertEqual(out[0]["value"], "hello")

    def test_bullets_one_per_item(self):
        out = self.rb({"kind": "bullets", "items": [
            {"level": 0, "text": "a"}, {"level": 1, "text": "b"}]})
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["value"].startswith("•"))
        self.assertTrue(out[1]["value"].startswith("    "))  # sub-indent

    def test_json_include_splices(self):
        p = _json_doc({"type": "text", "value": "X"})
        out = self.rb({"kind": "json_include", "path": p})
        self.assertEqual(out, [{"type": "text", "value": "X"}])

    def test_rc_include_with_json_splices(self):
        p = _json_doc({"type": "box"})
        out = self.rb({"kind": "rc_include", "name": "w", "json": p})
        self.assertEqual(out, [{"type": "box"}])

    def test_rc_include_without_json_placeholder(self):
        out = self.rb({"kind": "rc_include", "name": "w", "json": None})
        self.assertEqual(out[0]["type"], "text")
        self.assertIn("w", out[0]["value"])

    def test_missing_placeholder(self):
        out = self.rb({"kind": "missing", "name": "gone"})
        self.assertIn("gone", out[0]["value"])


class SlideRoot(unittest.TestCase):
    def build(self, slide, blocks):
        return render.build_slide_root(slide, blocks, THEME, 1600, 900, 0, False, [0])

    def test_title_first_for_content(self):
        root = self.build({"title": "T"}, [{"kind": "text", "text": "b"}])
        self.assertEqual(root["children"][0]["value"], "T")
        # a title gap spacer sits between the title and the content
        self.assertEqual(root["children"][1]["type"], "box")
        self.assertEqual(root["children"][2]["value"], "b")

    def test_title_gap_configurable(self):
        from refractkit.theme import build_theme
        theme = build_theme({"slide": {"title_gap": 99}})
        root = render.build_slide_root({"title": "T"}, [], theme, 1600, 900, 0, False, [0])
        gap = next(m["height"] for m in root["children"][1]["modifiers"] if "height" in m)
        self.assertEqual(gap, 99.0)

    def test_image_above_title_for_centered(self):
        d = tempfile.mkdtemp()
        import struct
        with open(os.path.join(d, "i.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 50, 50))
        slide = {"title": "Hi", "meta": {"type": "title"}}
        blocks = [{"kind": "image", "path": os.path.join(d, "i.png")}]
        root = self.build(slide, blocks)
        # first child is the image canvas, title text comes after
        self.assertEqual(root["children"][0]["type"], "canvas")
        self.assertTrue(any(c.get("value") == "Hi" for c in root["children"]))

    def test_panes_widths_from_ratio(self):
        slide = {"title": None, "meta": {"type": "content", "ratio": [1, 3]}}
        blocks = [{"kind": "text", "text": "l"}, {"kind": "pane_break"},
                  {"kind": "text", "text": "r"}]
        root = self.build(slide, blocks)
        row = [c for c in root["children"] if c["type"] == "row"][0]
        widths = [next(m["width"] for m in col["modifiers"] if isinstance(m, dict) and "width" in m)
                  for col in row["children"]]
        self.assertLess(widths[0], widths[1])   # 1 : 3


class Framing(unittest.TestCase):
    def test_solid_background_when_no_shader(self):
        root = render.frame_slide([], SPEC, THEME, "content", 1600, 900, False)
        self.assertEqual(root["type"], "column")
        self.assertTrue(any(isinstance(m, dict) and "background" in m for m in root["modifiers"]))

    def test_shader_wraps_in_box(self):
        theme = build_theme({"shader": {"source": "half4 main(){return half4(0);}"}})
        root = render.frame_slide([], SPEC, theme, "content", 1600, 900, False)
        self.assertEqual(root["type"], "box")
        self.assertEqual(root["children"][0]["type"], "canvas")   # shader behind


class Docs(unittest.TestCase):
    def test_build_doc(self):
        doc = render.build_doc({"title": "T"}, [], THEME, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["width"], 1600)
        self.assertEqual(doc["root"]["type"], "column")

    def test_profiles_set_with_shader(self):
        theme = build_theme({"shader": {"source": "half4 main(){return half4(0);}"}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["profiles"], 512)

    def test_transition_doc_statelayout(self):
        prev = ({"title": "A"}, [])
        cur = ({"title": "B"}, [])
        doc = render.build_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        self.assertIsInstance(doc["root"], list)
        sl = [n for n in doc["root"] if isinstance(n, dict) and n.get("type") == "stateLayout"][0]
        self.assertEqual(len(sl["children"]), 2)

    def test_graph_transition_two_vars(self):
        prev = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B}"}])
        cur = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B->C}"}])
        doc = render.build_graph_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        vars_ = [n for n in doc["root"] if isinstance(n, dict) and n.get("type") == "variable"]
        self.assertEqual({v["name"] for v in vars_}, {"__gp", "__gt"})


if __name__ == "__main__":
    unittest.main()

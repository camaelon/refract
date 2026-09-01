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


def _texts_all(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("value"))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _all_paddings(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            for m in n.get("modifiers", []):
                if isinstance(m, dict) and "padding" in m and isinstance(m["padding"], (int, float)):
                    out.append(float(m["padding"]))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _all_padding_arrays(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            for m in n.get("modifiers", []):
                if isinstance(m, dict) and isinstance(m.get("padding"), list):
                    out.append(list(m["padding"]))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _custom_configs(node, prefix):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "custom" and str(n.get("config", "")).startswith(prefix):
                out.append(n["config"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _web_configs(node):
    return _custom_configs(node, "web:")


def _find_uniform(doc, name):
    """Return the value bound to a shader uniform `name` anywhere in the doc."""
    found = []
    def walk(n):
        if isinstance(n, dict):
            u = n.get("uniforms")
            if isinstance(u, dict) and name in u:
                found.append(u[name])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(doc)
    return found[0] if found else None


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

    def test_embedded_video_custom_component(self):
        out = self.rb({"kind": "video", "path": "clips/demo.mp4", "src": "demo.mp4"})
        self.assertEqual(out[0]["type"], "custom")
        self.assertEqual(out[0]["config"], "video:demo.mp4")
        # sized 16:9 within the available box
        self.assertTrue(any(isinstance(m, dict) and "height" in m
                            for m in out[0]["modifiers"]))

    def test_embedded_video_src_falls_back_to_basename(self):
        # Without an explicit copied `src`, the config uses the path's file name.
        out = self.rb({"kind": "video", "path": "clips/demo.mp4"})
        self.assertEqual(out[0]["config"], "video:demo.mp4")

    def test_weblink_custom_component(self):
        # A web link is a native custom component the viewer embeds as a live WKWebView.
        out = self.rb({"kind": "weblink", "url": "https://demo.dev", "label": "Live"})
        self.assertEqual(out[0]["type"], "custom")
        self.assertEqual(out[0]["config"], "web:https://demo.dev")

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

    def test_max_reserves_chrome_but_content_does_not(self):
        from refractkit.theme import build_theme
        theme = build_theme({"chrome": {"progress": True}})
        # max's small margin is smaller than the chrome band → it reserves space…
        self.assertGreater(render._chrome_reserve(theme, "max", 32.0), 0.0)
        # …but a content slide's large margin already clears the chrome → no reserve.
        self.assertEqual(render._chrome_reserve(theme, "content", 80.0), 0.0)
        # …and with no chrome enabled, nothing is reserved.
        self.assertEqual(render._chrome_reserve(build_theme({}), "max", 32.0), 0.0)

    def test_max_type_small_margin_and_title(self):
        # `max` uses a small margin and a smaller title, and still shows chrome.
        from refractkit.theme import build_theme
        theme = build_theme({"chrome": {"page": True}})
        # `max` has tight top/left/right margins but keeps a normal bottom for the chrome.
        ml, mt, mr, mb = render._pad_sides(render.SLIDE_TYPES["max"]["padding"])
        cl, ct, cr, cb = render._pad_sides(render.SLIDE_TYPES["content"]["padding"])
        self.assertLess(mt, ct)
        self.assertLess(ml, cl)
        self.assertLess(mr, cr)
        self.assertGreater(mb, mt)          # bottom margin bigger than the top
        self.assertLess(theme.title_size("max"), theme.title_size("content"))
        doc = render.build_doc({"title": "T", "meta": {"type": "max"}},
                               [{"kind": "text", "text": "x"}], theme, 1600, 900, 0,
                               False, total=3)
        # chrome present (unlike title), and the outer padding is the per-side max margin
        self.assertIn("1 / 3", _texts_all(doc["root"]))
        self.assertIn([ml, mt, mr, mb], _all_padding_arrays(doc["root"]))

    def test_title_shader_backdrop_unless_type_has_full_shader(self):
        from dataclasses import replace
        theme = replace(THEME, title_shader="half4 main(){return half4(0);}")
        # a slide whose type has no full-slide shader (content) → title wrapped in a box
        # with a shader canvas behind it
        root = render.build_slide_root({"title": "T", "meta": {"type": "content"}},
                                       [], theme, 1600, 900, 0, False, [0])
        head = root["children"][0]
        self.assertEqual(head["type"], "box")
        self.assertTrue(any(c.get("type") == "canvas" for c in head["children"]))
        # but a type with its own full-slide shader (here section) keeps a plain title.
        # (frame_slide wraps a shader slide in a box [canvas, column].)
        theme2 = replace(theme, shaders={"section": "half4 main(){return half4(0);}"})
        root2 = render.build_slide_root({"title": "T", "meta": {"type": "section"}},
                                        [], theme2, 1600, 900, 0, False, [0])
        col2 = root2["children"][-1] if root2["type"] == "box" else root2
        self.assertEqual(col2["children"][0].get("value"), "T")   # plain text, not a box

    def test_centered_slide_text_is_centered(self):
        # On title/section slides the text below the title is centre-aligned.
        root = render.build_slide_root({"title": "T", "meta": {"type": "title"}},
                                       [{"kind": "text", "text": "byline"}],
                                       THEME, 1600, 900, 0, False, [0])
        txt = next(c for c in root["children"] if c.get("value") == "byline")
        self.assertEqual(txt["textAlign"], "center")

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


def _texts_with_color(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append((n.get("value"), n.get("color")))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


class Outline(unittest.TestCase):
    def test_outline_block_numbers_use_primary(self):
        theme = build_theme({"theme": {"primary": "#FF00AAFF"}})
        out = render.render_outline(
            {"kind": "outline", "items": [{"num": 1, "title": "Intro"},
                                          {"num": 2, "title": "Deep Dive"}]}, theme, False)
        pairs = _texts_with_color(out)
        # the numbers are in the primary colour, the titles in the body colour
        self.assertIn(("1.", "#FF00AAFF"), pairs)
        self.assertIn(("2.", "#FF00AAFF"), pairs)
        self.assertIn(("Intro", theme.body_color), pairs)

    def test_section_number_colored_primary(self):
        theme = build_theme({"theme": {"primary": "#FF00AAFF"}})
        root = render.build_slide_root(
            {"title": "Intro", "section_number": 1, "meta": {"type": "section"}},
            [], theme, 1600, 900, 0, False, [0])
        pairs = _texts_with_color(root)
        self.assertIn(("1.", "#FF00AAFF"), pairs)          # number tinted
        self.assertIn((" Intro", theme.title_color), pairs)  # title in normal colour

    def test_primary_defaults_to_accent(self):
        # A deck that never sets [theme] primary falls back to the accent colour.
        theme = build_theme({"theme": {"accent": "#FFABCDEF"}})
        self.assertEqual(theme.primary, "#FFABCDEF")


class Docs(unittest.TestCase):
    def test_build_doc(self):
        doc = render.build_doc({"title": "T"}, [], THEME, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["width"], 1600)
        self.assertEqual(doc["root"]["type"], "column")

    def test_profiles_set_with_shader(self):
        theme = build_theme({"shader": {"source": "half4 main(){return half4(0);}"}})
        doc = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["profiles"], 512)

    def test_profiles_set_with_flow(self):
        # Inline-styled text emits a wrapping Flow (op 240), which needs the
        # ANDROIDX|EXPERIMENTAL profile (513) to convert.
        doc = render.build_doc({"title": "T"}, [{"kind": "text", "text": "a **b**"}],
                               THEME, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["profiles"], 513)

    def test_profiles_set_with_custom_video(self):
        # An embedded video is a Custom component (op 93) → ANDROIDX|EXPERIMENTAL (513).
        doc = render.build_doc({"title": "T"},
                               [{"kind": "video", "path": "d.mp4", "src": "d.mp4"}],
                               THEME, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["profiles"], 513)

    def test_transition_doc_statelayout(self):
        prev = ({"title": "A"}, [])
        cur = ({"title": "B"}, [])
        doc = render.build_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        self.assertIsInstance(doc["root"], list)
        sl = [n for n in doc["root"] if isinstance(n, dict) and n.get("type") == "stateLayout"][0]
        self.assertEqual(len(sl["children"]), 2)

    def test_transition_overlay_only_in_transition_docs(self):
        theme = build_theme({"shader": {"transition": {"source": "half4 main(){return half4(0);}"}}})
        # A static slide has no transition overlay…
        static = render.build_doc({"title": "T"}, [], theme, 1600, 900, 0, False)
        self.assertNotIn("iProgress", json.dumps(static))
        # …but a push transition does, bound to its progress variable.
        push = render.build_push_doc(({"title": "A"}, []), ({"title": "B"}, []),
                                     theme, 1600, 900, 1, False, axis="y")
        ov = _find_uniform(push, "iProgress")
        self.assertEqual(ov, "$__pp")

    def test_push_duration_configurable(self):
        prev, cur = ({"title": "A"}, []), ({"title": "B"}, [])
        doc = render.build_push_doc(prev, cur, THEME, 1600, 900, 1, False,
                                    axis="y", duration=0.9)
        pp = next(n for n in doc["root"]
                  if isinstance(n, dict) and n.get("name") == "__pp")
        self.assertIn("/ 0.9", pp["value"])

    def test_push_drops_previous_webview(self):
        # The outgoing slide's webview is stripped from the transition; the incoming
        # slide keeps its own.
        prev = ({"title": "A"}, [{"kind": "weblink", "url": "https://a.dev"}])
        cur = ({"title": "B"}, [{"kind": "weblink", "url": "https://b.dev"}])
        doc = render.build_push_doc(prev, cur, THEME, 1600, 900, 1, False)
        webs = _web_configs(doc)
        self.assertEqual(webs, ["web:https://b.dev"])   # only the incoming page

    def test_push_drops_previous_video(self):
        # Like the webview: the outgoing slide's video is stripped so the transition
        # doesn't re-instantiate the player; the incoming slide keeps its own.
        prev = ({"title": "A"}, [{"kind": "video", "path": "a.mp4", "src": "a.mp4"}])
        cur = ({"title": "B"}, [{"kind": "video", "path": "b.mp4", "src": "b.mp4"}])
        doc = render.build_push_doc(prev, cur, THEME, 1600, 900, 1, False)
        vids = _custom_configs(doc, "video:")
        self.assertEqual(vids, ["video:b.mp4"])         # only the incoming clip

    def test_graph_transition_two_vars(self):
        prev = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B}"}])
        cur = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B->C}"}])
        doc = render.build_graph_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        vars_ = [n for n in doc["root"] if isinstance(n, dict) and n.get("type") == "variable"]
        self.assertEqual({v["name"] for v in vars_}, {"__gp", "__gt"})


if __name__ == "__main__":
    unittest.main()

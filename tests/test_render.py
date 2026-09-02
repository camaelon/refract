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
        # each bullet is a Row: [marker canvas, gap, text]; sub-levels add a leading indent
        self.assertEqual(out[0]["type"], "row")
        self.assertEqual(out[0]["children"][0]["type"], "canvas")   # drawn shape marker
        self.assertIn("a", _texts_all(out[0]))
        # the level-1 bullet has one extra leading child (the indent spacer)
        self.assertGreater(len(out[1]["children"]), len(out[0]["children"]))

    def test_sub_bullets_override_font_and_colour(self):
        from dataclasses import replace
        theme = replace(THEME, body_color="#FFEEEEEE", body_weight=400.0,
                        bullet_sub_color="#FF888888", bullet_sub_weight=300.0,
                        bullet_sub_font="Sub Font")
        out = render.render_block({"kind": "bullets", "items": [
            {"level": 0, "text": "top"}, {"level": 1, "text": "child"}]},
            40.0, theme, False, 800, 400, [0])
        # top level keeps the body colour; sub level uses the override
        top_txt = next(c for c in out[0]["children"] if c.get("type") == "text")
        sub_txt = next(c for c in out[1]["children"] if c.get("type") == "text")
        self.assertEqual(top_txt["color"], "#FFEEEEEE")
        self.assertEqual(sub_txt["color"], "#FF888888")
        self.assertEqual(sub_txt.get("fontFamily"), "Sub Font")
        self.assertEqual(sub_txt.get("fontWeight"), 300.0)

    def test_bullet_marker_defaults_to_primary_color(self):
        from dataclasses import replace
        theme = replace(THEME, primary="#FF0055AA", body_color="#FFEEEEEE")
        out = render.render_block({"kind": "bullets", "items": [{"level": 0, "text": "x"}]},
                                  40.0, theme, False, 800, 400, [0])
        canvas = out[0]["children"][0]
        paint = next(c for c in canvas["commands"] if c["type"] == "paint")
        col = next(o["color"] for o in paint["ops"] if "color" in o)
        self.assertEqual(col, "#FF0055AA")                    # marker uses primary, not body
        txt = next(c for c in out[0]["children"] if c.get("type") == "text")
        self.assertEqual(txt["color"], "#FFEEEEEE")           # text still body colour

    def test_bullet_marker_color_override(self):
        from dataclasses import replace
        theme = replace(THEME, primary="#FF0055AA", bullet_color="#FFFF00FF")
        out = render.render_block({"kind": "bullets", "items": [{"level": 0, "text": "x"}]},
                                  40.0, theme, False, 800, 400, [0])
        paint = next(c for c in out[0]["children"][0]["commands"] if c["type"] == "paint")
        col = next(o["color"] for o in paint["ops"] if "color" in o)
        self.assertEqual(col, "#FFFF00FF")

    def test_sub_bullets_can_use_a_different_shape(self):
        from dataclasses import replace
        theme = replace(THEME, bullet_shape="circle", bullet_sub_shape="hline")
        out = render.render_block({"kind": "bullets", "items": [
            {"level": 0, "text": "top"}, {"level": 1, "text": "child"}]},
            40.0, theme, False, 800, 400, [0])
        top_canvas = out[0]["children"][0]
        sub_canvas = next(c for c in out[1]["children"] if c.get("type") == "canvas")
        top_ops = [c["type"] for c in top_canvas["commands"] if c.get("type") != "paint"]
        sub_ops = [c["type"] for c in sub_canvas["commands"] if c.get("type") != "paint"]
        self.assertEqual(top_ops, ["drawcircle"])
        self.assertEqual(sub_ops, ["drawline"])

    def test_stagger_reveal_wraps_content(self):
        from dataclasses import replace
        theme = replace(THEME, content_reveal="stagger", reveal_stagger=0.15, reveal_duration=0.3)
        root = render.build_slide_root(
            {"title": "T", "meta": {"type": "content"}},
            [{"kind": "bullets", "items": [{"level": 0, "text": "a"}, {"level": 0, "text": "b"}]}],
            theme, 1600, 900, 0, False, [0])
        s = json.dumps(root)
        self.assertIn("animTime", s)                              # entrance driven by animTime
        # two bullets → two distinct start offsets (0.0 and 0.15)
        self.assertIn("animTime - 0.0)", s)
        self.assertIn("animTime - 0.15)", s)

    def test_immediate_reveal_has_no_animation(self):
        root = render.build_slide_root(
            {"title": "T", "meta": {"type": "content"}},
            [{"kind": "bullets", "items": [{"level": 0, "text": "a"}]}],
            THEME, 1600, 900, 0, False, [0])          # THEME default = immediate
        self.assertNotIn("animTime", json.dumps(root))

    def test_outgoing_slide_not_staggered(self):
        # animate=False (the outgoing slide of a transition) suppresses the reveal.
        from dataclasses import replace
        theme = replace(THEME, content_reveal="stagger")
        root = render.build_slide_root(
            {"title": "T", "meta": {"type": "content"}},
            [{"kind": "bullets", "items": [{"level": 0, "text": "a"}]}],
            theme, 1600, 900, 0, False, [0], animate=False)
        self.assertNotIn("animTime", json.dumps(root))

    def test_embedded_video_custom_component(self):
        out = self.rb({"kind": "video", "path": "clips/demo.mp4", "src": "demo.mp4"})
        self.assertEqual(out[0]["type"], "custom")
        self.assertEqual(out[0]["config"], "video:demo.mp4")
        # box fills the available height (rb passes avail_h=400); the host aspect-fits the clip
        h = next(m["height"] for m in out[0]["modifiers"] if isinstance(m, dict) and "height" in m)
        self.assertEqual(h, 400.0)

    def test_embedded_video_src_falls_back_to_basename(self):
        # Without an explicit copied `src`, the config uses the path's file name.
        out = self.rb({"kind": "video", "path": "clips/demo.mp4"})
        self.assertEqual(out[0]["config"], "video:demo.mp4")

    def test_video_box_fills_height_not_capped_to_16_9(self):
        # A tall content area (avail_h > avail_w*9/16) must still fill the height so a
        # portrait clip isn't shrunk inside a short 16:9 landscape box.
        out = render.render_block({"kind": "video", "path": "p.mp4", "src": "p.mp4"},
                                  40.0, THEME, False, 800, 700, [0])   # 700 > 800*9/16=450
        h = next(m["height"] for m in out[0]["modifiers"] if isinstance(m, dict) and "height" in m)
        self.assertEqual(h, 700.0)

    def test_rc_embed_uses_media_src(self):
        # refract copies embed assets to out/media/ and references them as media/<name>.
        out = render.render_block({"kind": "rc_include", "name": "w", "path": "/x/widget.rc",
                                   "src": "media/widget.rc", "json": None},
                                  40.0, THEME, False, 800, 400, [0])
        self.assertEqual(out[0]["config"], "rc:media/widget.rc")

    def test_embed_title_draws_caption_below(self):
        # A `title` caption wraps the embed in a column: the custom box, then a centred text.
        out = render.render_block({"kind": "rc_include", "name": "w", "path": "/x/widget.rc",
                                   "src": "media/widget.rc", "json": None,
                                   "caption": "My Widget"}, 40.0, THEME, False, 800, 400, [0])
        self.assertEqual(out[0]["type"], "column")
        kids = out[0]["children"]
        self.assertEqual(kids[0]["type"], "custom")            # embed first
        self.assertEqual(kids[-1]["type"], "text")             # caption below
        self.assertEqual(kids[-1]["value"], "My Widget")
        self.assertEqual(kids[-1].get("textAlign"), "center")
        # the embed box shrank to make room for the caption
        box_h = next(m["height"] for m in kids[0]["modifiers"] if isinstance(m, dict) and "height" in m)
        self.assertLess(box_h, 400.0)

    def test_embed_without_title_has_no_caption(self):
        out = render.render_block({"kind": "rc_include", "name": "w", "path": "/x/widget.rc",
                                   "src": "media/widget.rc", "json": None},
                                  40.0, THEME, False, 800, 400, [0])
        self.assertEqual(out[0]["type"], "custom")             # no column wrapper

    def test_weblink_custom_component(self):
        # A web link is a native custom component the viewer embeds as a live WKWebView.
        out = self.rb({"kind": "weblink", "url": "https://demo.dev", "label": "Live"})
        self.assertEqual(out[0]["type"], "custom")
        self.assertEqual(out[0]["config"], "web:https://demo.dev")

    def test_json_include_splices(self):
        p = _json_doc({"type": "text", "value": "X"})
        out = self.rb({"kind": "json_include", "path": p})
        # spliced content is wrapped in a clip frame so its draw ops can't spill out
        self.assertEqual(out[0]["type"], "box")
        self.assertIn({"clip": 0.0}, out[0]["modifiers"])
        self.assertEqual(out[0]["children"], [{"type": "text", "value": "X"}])

    def test_rc_include_with_json_splices(self):
        p = _json_doc({"type": "box"})
        out = self.rb({"kind": "rc_include", "name": "w", "json": p})
        self.assertEqual(out[0]["children"], [{"type": "box"}])   # inside the clip frame
        self.assertIn({"clip": 0.0}, out[0]["modifiers"])

    def test_rc_include_without_json_embeds_as_custom(self):
        # No .json sibling → embed the prebuilt .rc live as a custom component.
        out = self.rb({"kind": "rc_include", "name": "w", "path": "/x/widget.rc", "json": None})
        self.assertEqual(out[0]["type"], "custom")
        self.assertEqual(out[0]["config"], "rc:widget.rc")

    def test_rc_embed_encodes_fit(self):
        from dataclasses import replace
        theme = replace(THEME, embed_fit="fill")
        out = render.render_block({"kind": "rc_include", "name": "w", "path": "/x/widget.rc",
                                   "src": "widget.rc", "json": None},
                                  40.0, theme, False, 800, 400, [0])
        self.assertEqual(out[0]["config"], "rc:widget.rc#fit=fill")

    def test_video_encodes_crop(self):
        out = self.rb({"kind": "video", "src": "v.mp4", "path": "v.mp4",
                       "crop": [0.28, 0.0, 0.72, 1.0]})
        self.assertEqual(out[0]["config"], "video:v.mp4#crop=0.28,0.0,0.72,1.0")

    def test_rc_embed_encodes_fit_and_crop(self):
        from dataclasses import replace
        theme = replace(THEME, embed_fit="fill")
        out = render.render_block({"kind": "rc_include", "name": "w", "path": "/x/w.rc",
                                   "src": "media/w.rc", "json": None, "fit": "native",
                                   "crop": [0.1, 0.1, 0.9, 0.9]},
                                  40.0, theme, False, 800, 400, [0])
        # per-include fit override wins over the theme default; crop follows
        self.assertEqual(out[0]["config"], "rc:media/w.rc#fit=native&crop=0.1,0.1,0.9,0.9")

    def test_missing_placeholder(self):
        out = self.rb({"kind": "missing", "name": "gone"})
        self.assertIn("gone", out[0]["value"])


def _find_type(node, t):
    """First node of type ``t`` anywhere in the tree, or None."""
    if isinstance(node, dict):
        if node.get("type") == t:
            return node
        for v in node.values():
            r = _find_type(v, t)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_type(v, t)
            if r is not None:
                return r
    return None


class SplitLayout(unittest.TestCase):
    def _root(self, ratio=None):
        slide = {"title": "T", "meta": {"type": "split", "ratio": ratio}}
        blocks = [{"kind": "bullets", "items": [{"level": 0, "text": "left"}]},
                  {"kind": "pane_break"},
                  {"kind": "text", "text": "right"}]
        return render.build_slide_root(slide, blocks, THEME, 1600, 900, 0, False, [0])

    def test_row_first_two_columns(self):
        row = _find_type(self._root(), "row")
        cols = [c for c in row["children"] if c.get("type") == "column"]
        self.assertEqual(len(cols), 2)                       # left + right columns
        left, right = cols
        # the title lives INSIDE the left column (constrained to its width), not full-width
        self.assertIn("T", _texts_all(left))
        self.assertNotIn("T", _texts_all(right))
        # the right column runs full height
        self.assertIn("fillMaxHeight", right["modifiers"])
        # the right column holds the right-pane content
        self.assertIn("right", _texts_all(right))

    def test_ratio_sets_column_widths(self):
        row = _find_type(self._root(ratio=[3, 1]), "row")
        cols = [c for c in row["children"] if c.get("type") == "column"]
        lw = next(m["width"] for m in cols[0]["modifiers"] if isinstance(m, dict) and "width" in m)
        rw = next(m["width"] for m in cols[1]["modifiers"] if isinstance(m, dict) and "width" in m)
        self.assertAlmostEqual(lw / rw, 3.0, places=1)       # 3:1 widths

    def test_split_single_column_uses_tall_right(self):
        # A split slide with no `+++` still uses the split layout: the lone content goes in
        # the full-height right column and the left column holds just the title.
        slide = {"title": "T", "meta": {"type": "split"}}
        root = render.build_slide_root(slide, [{"kind": "text", "text": "x"}],
                                       THEME, 1600, 900, 0, False, [0])
        row = _find_type(root, "row")
        self.assertIsNotNone(row)
        cols = [c for c in row["children"] if c.get("type") == "column"]
        self.assertEqual(len(cols), 2)
        left, right = cols
        # title on the left, content on the right full-height column
        self.assertIn("T", _texts_all(left))
        self.assertIn("fillMaxHeight", right["modifiers"])
        self.assertIn("x", _texts_all(right))
        self.assertNotIn("x", _texts_all(left))

    def test_split_title_only_falls_back_to_content(self):
        # A split slide with no content at all (title only) has nothing for the right
        # column, so it degrades to a normal content layout (no two-column row).
        slide = {"title": "T", "meta": {"type": "split"}}
        root = render.build_slide_root(slide, [], THEME, 1600, 900, 0, False, [0])
        row = _find_type(root, "row")
        self.assertTrue(row is None or
                        len([c for c in row["children"] if c.get("type") == "column"]) < 2)


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


def _mark_colors(node):
    """Paint colours of the shapes drawn in the progress-mark canvas (one paint per mark)."""
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "canvas":
                for c in n.get("commands", []):
                    if isinstance(c, dict) and c.get("type") == "paint":
                        col = next((o["color"] for o in c.get("ops", [])
                                    if isinstance(o, dict) and "color" in o), None)
                        if col:
                            out.append(col)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


class ProgressChrome(unittest.TestCase):
    def _theme(self, **kw):
        from dataclasses import replace
        base = dict(chrome_progress=True, accent="#FFACC0FF", primary="#FF111111",
                    chrome_sections=[{"start": 2, "color": "#FF00FF00"},
                                     {"start": 6, "color": "#FFFF0000"}])
        base.update(kw)
        return replace(THEME, **base)

    def test_section_marks_circles_colored_per_section(self):
        theme = self._theme(chrome_progress_marks=True, chrome_progress_color="section")
        ov = render._chrome_overlay(theme, 8, 10, 1600, 900, False)
        self.assertEqual(_mark_colors(ov), ["#FF00FF00", "#FFFF0000"])  # one circle per section

    def test_marks_use_current_accent_in_current_mode(self):
        theme = self._theme(chrome_progress_marks=True, chrome_progress_color="current")
        ov = render._chrome_overlay(theme, 8, 10, 1600, 900, False)
        self.assertEqual(_mark_colors(ov), ["#FFACC0FF", "#FFACC0FF"])  # both current accent

    def test_no_circles_when_marks_off(self):
        theme = self._theme(chrome_progress_marks=False, chrome_progress_color="section")
        ov = render._chrome_overlay(theme, 8, 10, 1600, 900, False)
        self.assertEqual(_mark_colors(ov), [])

    def test_section_mode_fill_uses_section_colors(self):
        theme = self._theme(chrome_progress_color="section")
        ov = render._chrome_overlay(theme, 9, 10, 1600, 900, False)  # last slide → fully filled
        bgs = []
        def walk(n):
            if isinstance(n, dict):
                for m in n.get("modifiers", []) if isinstance(n.get("modifiers"), list) else []:
                    if isinstance(m, dict) and "background" in m:
                        bgs.append(m["background"])
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(ov)
        # both section colours appear in the segmented fill
        self.assertIn("#FF00FF00", bgs)
        self.assertIn("#FFFF0000", bgs)

    def test_current_mode_single_accent_fill(self):
        theme = self._theme(chrome_progress_color="current")
        ov = render._chrome_overlay(theme, 9, 10, 1600, 900, False)
        bgs = []
        def walk(n):
            if isinstance(n, dict):
                for m in n.get("modifiers", []) if isinstance(n.get("modifiers"), list) else []:
                    if isinstance(m, dict) and "background" in m:
                        bgs.append(m["background"])
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(ov)
        # the section colours are NOT used for the fill in current mode
        self.assertNotIn("#FF00FF00", bgs)
        self.assertIn("#FFACC0FF", bgs)   # current accent fill


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

    def test_transition_strips_previous_rc_embed(self):
        # A custom component (op 93) is painted by its native host every frame regardless of
        # the active StateLayout branch, so an embed baked into the outgoing (previous) state
        # would leak through and linger. It must be stripped from the previous slide; the
        # incoming slide keeps its own.
        prev = ({"title": "A"}, [{"kind": "rc_include", "name": "p", "path": "/x/p.rc",
                                  "src": "media/p.rc", "json": None}])
        cur = ({"title": "B"}, [{"kind": "rc_include", "name": "c", "path": "/x/c.rc",
                                 "src": "media/c.rc", "json": None}])
        doc = render.build_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        embeds = _custom_configs(doc, "rc:")
        self.assertEqual(embeds, ["rc:media/c.rc"])     # only the incoming embed

    def test_graph_transition_two_vars(self):
        prev = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B}"}])
        cur = ({"title": "G"}, [{"kind": "graph", "engine": "dot", "dot": "digraph{A->B->C}"}])
        doc = render.build_graph_transition_doc(prev, cur, THEME, 1600, 900, 1, False)
        vars_ = [n for n in doc["root"] if isinstance(n, dict) and n.get("type") == "variable"]
        self.assertEqual({v["name"] for v in vars_}, {"__gp", "__gt"})


class Scroll(unittest.TestCase):
    def _long(self):
        return [{"kind": "text", "text": "a long wrapping paragraph of body text here."}
                for _ in range(40)]

    def _find_clip_box(self, node):
        # A scroll viewport is a box with a fixed height + clip whose child column is offset.
        if isinstance(node, dict):
            if node.get("type") == "box":
                mods = node.get("modifiers", [])
                has_clip = any(isinstance(m, dict) and "clip" in m for m in mods)
                has_h = any(isinstance(m, dict) and "height" in m for m in mods)
                if has_clip and has_h:
                    for c in node.get("children", []):
                        offs = [m for m in c.get("modifiers", []) if isinstance(m, dict) and "offset" in m]
                        if offs:
                            return node, offs[0]["offset"]["y"]
            for v in node.values():
                r = self._find_clip_box(v)
                if r:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = self._find_clip_box(v)
                if r:
                    return r
        return None

    def test_scroll_spec_static_and_animated(self):
        self.assertEqual(render.scroll_spec(0, 0, 560)["y"], 0.0)          # no move → static
        y = render.scroll_spec(100, 500, 560)["y"]
        self.assertIsInstance(y, str)
        self.assertIn(render.SAME_VAR, y)                                  # animates on $__st

    def test_build_scroll_doc_clips_and_offsets(self):
        slide = {"title": "T", "meta": {"type": "content"}}
        doc = render.build_scroll_doc(slide, self._long(), THEME, 1600, 900, 2, False, 5,
                                      100.0, 500.0, 560.0)
        found = self._find_clip_box(doc["root"])
        self.assertIsNotNone(found, "expected a clipped scroll viewport")
        _, y = found
        self.assertIn(render.SAME_VAR, y)                                  # scroll animates
        names = {n["name"] for n in doc["root"] if isinstance(n, dict) and n.get("type") == "variable"}
        self.assertEqual(names, {"__sp", "__st"})

    def test_scroll_page_suppresses_autosize(self):
        # A scroll page renders full-size (no shrink) even when content overflows.
        slide = {"title": "T", "meta": {"type": "content"}}
        root = render.build_slide_root(slide, self._long(), THEME, 1600, 900, 0, False, [0],
                                       scroll={"viewport": 560.0, "y": 0.0})
        base = THEME.body_size("content")
        sizes = []
        def collect(n):
            if isinstance(n, dict):
                if n.get("type") == "text" and "fontSize" in n:
                    sizes.append(n["fontSize"])
                for v in n.values():
                    collect(v)
            elif isinstance(n, list):
                for v in n:
                    collect(v)
        collect(root)
        self.assertNotIn(True, [s < base for s in sizes])                  # nothing shrunk

    def test_same_doc_accepts_scroll(self):
        prev = ({"title": "T", "meta": {"type": "same"}}, self._long())
        cur = ({"title": "T", "meta": {"type": "same"}}, self._long())
        doc = render.build_same_doc(prev, cur, THEME, 1600, 900, 1, False,
                                    scroll=render.scroll_spec(0, 560, 560))
        self.assertIsNotNone(self._find_clip_box(doc["root"]))


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest

from refractkit import deck, markdown as md, render
from refractkit.theme import build_theme

THEME = build_theme({})
SPEC = render.SLIDE_TYPES["content"]


class Tables(unittest.TestCase):
    def test_parsed_without_separator_row(self):
        s = md.parse_slide("# T\n| a | b |\n|---|---|\n| 1 | 2 |")
        tbl = [b for b in s["blocks"] if b["kind"] == "table"][0]
        self.assertEqual(tbl["rows"], [["a", "b"], ["1", "2"]])

    def test_render_header_and_body(self):
        out = render.render_table([["H1", "H2"], ["a", "b"]], THEME, False)
        col = out[0]
        self.assertEqual(len(col["children"]), 2)          # 2 rows
        header_cells = col["children"][0]["children"]
        self.assertEqual(header_cells[0]["color"], THEME.accent)

    def test_ragged_rows_padded(self):
        out = render.render_table([["a", "b", "c"], ["x"]], THEME, False)
        self.assertEqual(len(out[0]["children"][1]["children"]), 3)


class Subtitle(unittest.TestCase):
    def test_parsed_after_title(self):
        s = md.parse_slide("# Title\n*the subtitle*")
        self.assertEqual(s["blocks"][0], {"kind": "subtitle", "text": "the subtitle"})

    def test_italic_not_subtitle_without_title(self):
        s = md.parse_slide("*just italic text*")
        self.assertEqual(s["blocks"][0]["kind"], "text")

    def test_render_uses_accent(self):
        out = render.render_block({"kind": "subtitle", "text": "x"}, 40.0, THEME, False, 800, 400, [0])
        self.assertEqual(out[0]["color"], THEME.accent)


class CodeFileInclude(unittest.TestCase):
    def test_kt_resolves_to_code(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "includes"))
        with open(os.path.join(d, "includes", "a.kt"), "w") as f:
            f.write("val x = 1\n")
        b = deck.resolve_include("a.kt", os.path.join(d, "includes"))
        self.assertEqual(b["kind"], "code")
        self.assertEqual(b["lang"], "kotlin")
        self.assertEqual(b["text"], "val x = 1")

    def test_extensionless_probe_finds_kt(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "test2.kt"), "w") as f:
            f.write("fun main() {}")
        b = deck.resolve_include("test2", d)
        self.assertEqual(b["kind"], "code")


class Video(unittest.TestCase):
    def test_mp4_resolves_to_video(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "clip.mp4"), "wb").close()
        b = deck.resolve_include("clip.mp4", d)
        self.assertEqual(b["kind"], "video")
        self.assertTrue(b["path"].endswith("clip.mp4"))


class Accent(unittest.TestCase):
    def test_speaker_theme_override(self):
        from dataclasses import replace
        t = replace(THEME, accent="#FF00FF00")
        out = render.render_block({"kind": "subtitle", "text": "s"}, 40.0, t, False, 800, 400, [0])
        self.assertEqual(out[0]["color"], "#FF00FF00")


class ShaderProfiles(unittest.TestCase):
    def test_shader_include_sets_profiles(self):
        # a spliced doc containing a shader must bump the header to profiles 512
        doc = render.build_doc(
            {"title": "S"},
            [{"kind": "json_include", "path": _shader_json()}],
            THEME, 1600, 900, 0, False)
        self.assertEqual(doc["header"]["profiles"], 512)

    def test_no_shader_no_profiles(self):
        doc = render.build_doc({"title": "S"}, [{"kind": "text", "text": "hi"}],
                               THEME, 1600, 900, 0, False)
        self.assertNotIn("profiles", doc["header"])


def _shader_json():
    import json
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    with open(p, "w") as f:
        json.dump({"root": {"type": "canvas", "commands": [
            {"type": "paint", "ops": [{"shader": {"agsl": "x"}}]}]}}, f)
    return p


class GraphSlideGuard(unittest.TestCase):
    def test_pure_graph_slide(self):
        self.assertTrue(render.is_graph_slide([{"kind": "graph"}]))

    def test_graph_with_bullets_is_not(self):
        blocks = [{"kind": "bullets"}, {"kind": "pane_break"}, {"kind": "graph"}]
        self.assertFalse(render.is_graph_slide(blocks))

    def test_no_graph_is_not(self):
        self.assertFalse(render.is_graph_slide([{"kind": "text"}]))


if __name__ == "__main__":
    unittest.main()

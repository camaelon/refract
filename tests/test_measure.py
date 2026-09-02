import unittest

from refractkit import measure, render
from refractkit.theme import build_theme

THEME = build_theme({})


class WrapAndHeight(unittest.TestCase):
    def test_short_line_is_one_visual_line(self):
        self.assertEqual(measure._wrap_lines("hello world", 40, 2000), 1)

    def test_long_line_wraps(self):
        s = "word " * 60
        self.assertGreater(measure._wrap_lines(s, 40, 800), 1)

    def test_narrower_width_wraps_more(self):
        s = "word " * 60
        wide = measure._wrap_lines(s, 40, 1200)
        narrow = measure._wrap_lines(s, 40, 400)
        self.assertGreater(narrow, wide)

    def test_empty_line_still_occupies_a_line(self):
        self.assertEqual(measure._wrap_lines("", 40, 800), 1)

    def test_bullet_height_grows_with_items(self):
        one = measure.content_height(
            [{"kind": "bullets", "items": [{"level": 0, "text": "a"}]}], 40, THEME, 1200)
        many = measure.content_height(
            [{"kind": "bullets", "items": [{"level": 0, "text": "a"}] * 8}], 40, THEME, 1200)
        self.assertGreater(many, one)

    def test_media_blocks_do_not_drive_autosize(self):
        # Non-text blocks contribute no measured height (they size to fit themselves).
        self.assertEqual(measure.block_height(
            {"kind": "video", "src": "v.mp4"}, 40, THEME, 1200), 0.0)

    def test_outline_block_measured_and_scales(self):
        block = {"kind": "outline", "items": [{"num": i, "title": f"S{i}"} for i in range(8)]}
        h = measure.block_height(block, 40, THEME, 1200)
        self.assertGreater(h, 0.0)                              # outline drives autosize now
        self.assertLess(measure.block_height(block, 20, THEME, 1200), h)   # scales with size

    def test_long_outline_autosizes(self):
        block = {"kind": "outline", "items": [{"num": i, "title": f"Section {i}"}
                                              for i in range(1, 13)]}
        self.assertLess(measure.fit_body_size([block], 40, THEME, 1400, 500), 40)

    def test_outline_renders_flat_for_stagger(self):
        # One node per section (not wrapped in a column) so the reveal staggers each item.
        rows = render.render_outline({"items": [{"num": 1, "title": "A"},
                                                {"num": 2, "title": "B"},
                                                {"num": 3, "title": "C"}]}, THEME, False)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["type"] == "row" for r in rows))


class FitBodySize(unittest.TestCase):
    def test_fits_returns_base_size(self):
        blocks = [{"kind": "text", "text": "one short line"}]
        self.assertEqual(measure.fit_body_size(blocks, 40, THEME, 1200, 800), 40)

    def test_overflow_shrinks(self):
        blocks = [{"kind": "text", "text": "\n".join(["a long wrapping line " * 4] * 30)}]
        size = measure.fit_body_size(blocks, 40, THEME, 1000, 400)
        self.assertLess(size, 40)

    def test_never_below_min_scale(self):
        blocks = [{"kind": "text", "text": "\n".join(["x " * 40] * 400)}]
        size = measure.fit_body_size(blocks, 40, THEME, 1000, 200, min_scale=0.5)
        self.assertGreaterEqual(size, 40 * 0.5)


class AutosizeInRender(unittest.TestCase):
    def _sizes(self, node, out):
        if isinstance(node, dict):
            if node.get("type") == "text" and "fontSize" in node:
                out.append(node["fontSize"])
            for v in node.values():
                self._sizes(v, out)
        elif isinstance(node, list):
            for v in node:
                self._sizes(v, out)
        return out

    def test_overflowing_content_shrinks_body(self):
        slide = {"title": "T", "meta": {"type": "content"}}
        long = "\n".join(["This is a fairly long paragraph line that wraps a few times."] * 40)
        root = render.build_slide_root(slide, [{"kind": "text", "text": long}],
                                       THEME, 1600, 900, 0, False, [0])
        base = THEME.body_size("content")
        body_sizes = [s for s in self._sizes(root, []) if s < base]
        self.assertTrue(body_sizes, "expected some text shrunk below the base body size")

    def test_autosize_off_keeps_base_size(self):
        theme = build_theme({"layout": {"autosize": False}})
        slide = {"title": "T", "meta": {"type": "content"}}
        long = "\n".join(["This is a fairly long paragraph line that wraps a few times."] * 40)
        root = render.build_slide_root(slide, [{"kind": "text", "text": long}],
                                       theme, 1600, 900, 0, False, [0])
        base = theme.body_size("content")
        self.assertNotIn(True, [s < base for s in self._sizes(root, [])])


if __name__ == "__main__":
    unittest.main()

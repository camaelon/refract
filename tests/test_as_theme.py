import os
import tempfile
import unittest

from refractkit import as_theme, deck, markdown, render
from refractkit.theme import build_theme


class TestAsTheme(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.deck_dir = self.temp_dir.name
        self.theme_dir = os.path.join(self.deck_dir, "theme")
        self.include_dir = os.path.join(self.theme_dir, "include")
        os.makedirs(self.include_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_meta_as(self):
        m1 = markdown.parse_meta("as : section_dark")
        self.assertEqual(m1["type"], "as")
        self.assertEqual(m1["params"], "section_dark")

        m2 = markdown.parse_meta("as section_dark")
        self.assertEqual(m2["type"], "as")
        self.assertEqual(m2["params"], "section_dark")

        m3 = markdown.parse_meta("as: speaker_split [392:491] pad_top=10")
        self.assertEqual(m3["type"], "as")
        self.assertEqual(m3["params"], "speaker_split")
        self.assertEqual(m3["ratio"], [392, 491])
        self.assertEqual(m3["overrides"], {"pad_top": "10"})

    def test_load_and_resolve_as_slide(self):
        toml_path = os.path.join(self.theme_dir, "section_dark.toml")
        with open(toml_path, "w") as f:
            f.write("""
type = "section"
bg = "#202124"
title_size = 207
title_weight = 600
pad_top = -44
""")

        slide = {
            "meta": markdown.parse_meta("as: section_dark pad_top=-50"),
            "title": "Section Title",
            "blocks": [],
            "base_dir": self.deck_dir,
        }
        as_theme.resolve_as_slide(slide, self.deck_dir)

        self.assertEqual(slide["meta"]["type"], "section")
        self.assertEqual(slide["meta"]["as_theme"], "section_dark")
        self.assertEqual(slide["meta"]["overrides"]["bg"], "#202124")
        self.assertEqual(slide["meta"]["overrides"]["title_size"], "207")
        self.assertEqual(slide["meta"]["overrides"]["title_weight"], "600")
        # Per-slide override wins:
        self.assertEqual(slide["meta"]["overrides"]["pad_top"], "-50")
        self.assertEqual(render.slide_type(slide), "section")

    def test_sectioned_toml_format(self):
        toml_path = os.path.join(self.theme_dir, "complex.toml")
        with open(toml_path, "w") as f:
            f.write("""
[layout]
type = "split"
pane_gap = 78
padding = [319.34, 93.73, 231.26, 0.0]

[theme]
bg = "#FFFFFF"
bg_doc = "bg_pill.json"

[font]
title = 44
title_weight = 700
body = 24.4

[heading.3]
size = 31.1
weight = 500
color = "#FF5F6368"
gap = 47
""")

        slide = {
            "meta": markdown.parse_meta("as: complex"),
            "title": "Speaker",
            "blocks": [],
            "base_dir": self.deck_dir,
        }
        as_theme.resolve_as_slide(slide, self.deck_dir)

        self.assertEqual(slide["meta"]["type"], "split")
        ov = slide["meta"]["overrides"]
        self.assertEqual(ov["pane_gap"], "78")
        self.assertEqual(ov["pad_left"], "319.34")
        self.assertEqual(ov["pad_top"], "93.73")
        self.assertEqual(ov["title_size"], "44")
        self.assertEqual(ov["body_size"], "24.4")
        self.assertEqual(ov["h3_size"], "31.1")
        self.assertEqual(ov["h3_color"], "#FF5F6368")
        self.assertEqual(ov["h3_gap"], "47")

    def test_theme_include_asset_resolution(self):
        asset_file = os.path.join(self.include_dir, "theme_badge.png")
        with open(asset_file, "wb") as f:
            f.write(b"fake png")

        slide = {
            "meta": markdown.parse_meta("content"),
            "title": "Test",
            "blocks": [{"kind": "include", "name": "theme_badge.png"}],
            "base_dir": self.deck_dir,
        }
        resolved = deck.resolve_blocks(slide)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["kind"], "image")
        self.assertEqual(resolved[0]["path"], os.path.abspath(asset_file))


if __name__ == "__main__":
    unittest.main()

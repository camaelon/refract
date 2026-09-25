"""A sub-deck slide that names a template its own folder does not carry gets the root deck's."""
import os
import tempfile
import unittest

from refractkit import deck
from refractkit.theme import _resolve_asset_path


class TestSubdeckThemeFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "theme", "include"))
        os.makedirs(os.path.join(self.root, "includes", "sub", "theme"))
        with open(os.path.join(self.root, "theme", "statement.toml"), "w") as f:
            f.write('type = "content"\nbg_doc = "bg_plate.json"\n\n[theme]\naccent = "#FF123456"\n')
        with open(os.path.join(self.root, "theme", "include", "bg_plate.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.root, "includes", "sub", "theme", "local.toml"), "w") as f:
            f.write('type = "content"\n\n[theme]\naccent = "#FFABCDEF"\n')
        with open(os.path.join(self.root, "slides.md"), "w") as f:
            f.write("# Root\n\n---\n:: include : sub\n")
        with open(os.path.join(self.root, "includes", "sub", "slides.md"), "w") as f:
            f.write(":: as: statement\n# From the root theme\n\n---\n:: as: local\n# From my own theme\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_falls_back_to_root_deck(self):
        slides = deck.load_deck(self.root, set())
        self.assertEqual(len(slides), 3)
        sub_dir = os.path.join(self.root, "includes", "sub")
        # the sub-deck slide resolved `statement` although includes/sub/theme has no such file
        s = slides[1]
        self.assertEqual(s["meta"].get("as_theme"), "statement")
        self.assertEqual(s["meta"]["overrides"].get("accent"), "#FF123456")
        self.assertEqual(os.path.abspath(s["root_dir"]), os.path.abspath(self.root))
        self.assertEqual(os.path.abspath(s["base_dir"]), os.path.abspath(sub_dir))
        # its own template still wins when it has one
        self.assertEqual(slides[2]["meta"].get("as_theme"), "local")
        self.assertEqual(slides[2]["meta"]["overrides"].get("accent"), "#FFABCDEF")

    def test_bg_doc_resolves_in_root_theme_include(self):
        sub_dir = os.path.join(self.root, "includes", "sub")
        p = _resolve_asset_path("bg_plate.json", sub_dir, [self.root])
        self.assertEqual(p, os.path.abspath(os.path.join(self.root, "theme", "include", "bg_plate.json")))
        # without the fallback the sub-deck's own (missing) path is what comes back
        self.assertEqual(_resolve_asset_path("bg_plate.json", sub_dir),
                         os.path.abspath(os.path.join(sub_dir, "bg_plate.json")))


    def test_content_include_falls_back_to_root_includes(self):
        # a picture only the root deck has, a document both have (the sub-deck's must win)
        with open(os.path.join(self.root, "includes", "shared.png"), "wb") as f:
            f.write(b"\x89PNG root")
        with open(os.path.join(self.root, "includes", "card.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(self.root, "includes", "sub", "includes"))
        with open(os.path.join(self.root, "includes", "sub", "includes", "card.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.root, "includes", "sub", "slides.md"), "w") as f:
            f.write("# Pictures\n\n<shared>\n\n<card.json>\n")
        slides = deck.load_deck(self.root, set())
        blocks = deck.resolve_blocks(slides[1])
        kinds = [(b["kind"], b.get("path")) for b in blocks if b["kind"] != "text"]
        self.assertEqual(kinds[0][0], "image")
        self.assertEqual(kinds[0][1], os.path.abspath(os.path.join(self.root, "includes", "shared.png")))
        self.assertEqual(kinds[1][0], "json_include")
        self.assertEqual(kinds[1][1],
                         os.path.abspath(os.path.join(self.root, "includes", "sub", "includes", "card.json")))
        # the root deck's own slide never looks inside a sub-deck
        with open(os.path.join(self.root, "slides.md"), "w") as f:
            f.write("# Root\n\n<card.json>\n")
        root_blocks = deck.resolve_blocks(deck.load_deck(self.root, set())[0])
        self.assertEqual([b["path"] for b in root_blocks if b["kind"] == "json_include"],
                         [os.path.abspath(os.path.join(self.root, "includes", "card.json"))])


if __name__ == "__main__":
    unittest.main()

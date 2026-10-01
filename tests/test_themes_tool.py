"""The deck's theme presets, as the editor's theme panel asks for them."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "themes", os.path.join(HERE, "..", "player", "tools", "themes.py"))
themes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(themes)


class Presets(unittest.TestCase):
    def setUp(self):
        self.deck = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.deck, "theme"))
        os.makedirs(os.path.join(self.deck, "themes"))
        self.write("theme/hero.toml", """
type = "content"
bg = "#FF000000"
title_color = "#FFFFFFFF"
title_size = 111.11
""")
        self.write("theme/quote.toml", 'type = "section"\nbg = "#FFEEEEEE"\n')
        # A deck can keep them in either folder; the same name in both is one preset.
        self.write("themes/hero.toml", 'type = "title"\n')
        self.write("themes/only_here.toml", 'type = "content"\n')

    def write(self, path, text):
        with open(os.path.join(self.deck, path), "w") as f:
            f.write(text)

    def test_every_name_a_slide_could_ask_for(self):
        files = themes.preset_files(self.deck)
        names = [os.path.splitext(os.path.basename(p))[0] for p in files]
        self.assertEqual(names, ["hero", "only_here", "quote"], "in order, without repeats")
        self.assertTrue(files[0].endswith("theme/hero.toml"), "theme/ wins over themes/")

    def test_what_a_swatch_is_drawn_from(self):
        listed = themes.themes_of(self.deck)
        self.assertTrue(listed["ok"])
        hero = next(t for t in listed["themes"] if t["name"] == "hero")
        self.assertEqual(hero["file"], "theme/hero.toml")
        self.assertEqual(hero["type"], "content")
        self.assertEqual(hero["bg"], "#FF000000")
        self.assertEqual(hero["title_color"], "#FFFFFFFF")
        self.assertEqual(hero["title_size"], 111.11)
        self.assertEqual(hero["slides"], [], "nothing is built, so nothing uses it")

    def test_a_preset_that_sets_little_still_says_what_it_looks_like(self):
        # `quote` sets a background and nothing else: the rest is the deck's, which is what a
        # slide would actually be drawn in.
        quote = next(t for t in themes.themes_of(self.deck)["themes"] if t["name"] == "quote")
        self.assertEqual(quote["bg"], "#FFEEEEEE")
        self.assertTrue(quote["title_color"].startswith("#"), "the deck's title colour")
        self.assertGreater(quote["title_size"], 0, "and its title size")

    def test_which_slides_are_on_each(self):
        out = os.path.join(self.deck, "out")
        os.makedirs(out)
        with open(os.path.join(out, "deck.json"), "w") as f:
            json.dump({"version": 1, "deck": "d", "deck_dir": self.deck, "slides": [
                {"index": 0, "file": "01.rc", "theme": "hero"},
                {"index": 1, "file": "02.rc"},
                {"index": 2, "file": "03.rc", "theme": "hero"},
            ]}, f)
        used = themes.usage(out)
        self.assertEqual(used, {"hero": [1, 3]}, "1-based, as a deck is counted")
        listed = themes.themes_of(self.deck, out)
        self.assertEqual(next(t for t in listed["themes"] if t["name"] == "hero")["slides"], [1, 3])
        self.assertEqual(next(t for t in listed["themes"] if t["name"] == "quote")["slides"], [])

    def test_no_manifest_no_usage(self):
        self.assertEqual(themes.usage(os.path.join(self.deck, "nothing")), {})


if __name__ == "__main__":
    unittest.main()

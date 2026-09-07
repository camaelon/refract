import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

from refractkit import assets


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(REPO, "player", "tools", "assets.py")


def _png(path, w=8, h=8):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Kinds(unittest.TestCase):
    def test_a_file_is_named_by_its_extension(self):
        for name, kind in [("a.png", "image"), ("a.JPG", "image"), ("a.mp4", "video"),
                           ("a.rc", "document"), ("a.py", "code"), ("a.sksl", "shader"),
                           ("slides.md", "deck"), ("notes.txt", "other")]:
            with self.subTest(name=name):
                self.assertEqual(assets.kind_of(name), kind)


class Scan(unittest.TestCase):
    """A deck with one image on a slide and one nobody kept using."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        _write(os.path.join(self.deck, "slides.md"),
               "# One\n\n<kept.png>\n\n---\n\n# Two\n\nno picture here\n")
        _png(os.path.join(self.deck, "includes", "kept.png"))
        _png(os.path.join(self.deck, "includes", "orphan.png"))

    def find(self, name, found=None):
        found = assets.scan(self.deck) if found is None else found
        return next(a for a in found if a["name"] == name)

    def test_everything_under_includes_is_listed(self):
        self.assertEqual(sorted(a["name"] for a in assets.scan(self.deck)),
                         ["kept.png", "orphan.png"])

    def test_a_used_asset_names_the_slide_that_uses_it(self):
        kept = self.find("kept.png")
        self.assertTrue(kept["used"])
        self.assertEqual(kept["slides"], [1])
        self.assertEqual(kept["path"], os.path.join("includes", "kept.png"))
        self.assertEqual(kept["kind"], "image")

    def test_an_asset_nothing_points_at_is_unused(self):
        orphan = self.find("orphan.png")
        self.assertFalse(orphan["used"])
        self.assertEqual(orphan["slides"], [])

    def test_the_same_image_on_two_slides_lists_both(self):
        _write(os.path.join(self.deck, "slides.md"),
               "# One\n\n<kept.png>\n\n---\n\n# Two\n\n<kept.png>\n")
        self.assertEqual(self.find("kept.png")["slides"], [1, 2])

    def test_a_missing_file_a_slide_names_is_not_an_asset(self):
        # The slide is wrong, but there is nothing in includes/ to have an opinion about.
        _write(os.path.join(self.deck, "slides.md"), "# One\n\n<gone.png>\n")
        self.assertNotIn("gone.png", [a["name"] for a in assets.scan(self.deck)])

    def test_a_deck_with_no_includes_scans_to_nothing(self):
        self.assertEqual(assets.scan(tempfile.mkdtemp()), [])

    def test_dotfiles_are_skipped(self):
        _png(os.path.join(self.deck, "includes", ".DS_Store"))
        self.assertNotIn(".DS_Store", [a["name"] for a in assets.scan(self.deck)])

    def test_size_is_reported(self):
        self.assertEqual(self.find("kept.png")["size"],
                         os.path.getsize(os.path.join(self.deck, "includes", "kept.png")))


class SubDecks(unittest.TestCase):
    """An `:: include` pulls in a sub-deck; its own images count as that sub-deck's."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        _write(os.path.join(self.deck, "slides.md"),
               "# Top\n\n---\n\n:: include : part\n")
        _write(os.path.join(self.deck, "includes", "part", "slides.md"),
               "# Inner\n\n<inner.png>\n")
        _png(os.path.join(self.deck, "includes", "part", "includes", "inner.png"))
        _png(os.path.join(self.deck, "includes", "part", "includes", "spare.png"))

    def test_a_sub_decks_image_is_used(self):
        found = {a["name"]: a for a in assets.scan(self.deck)}
        self.assertTrue(found["inner.png"]["used"])
        self.assertFalse(found["spare.png"]["used"])

    def test_the_included_markdown_is_itself_an_asset_and_is_used(self):
        found = {a["name"]: a for a in assets.scan(self.deck)}
        self.assertEqual(found["slides.md"]["kind"], "deck")
        self.assertTrue(found["slides.md"]["used"])


class Shaders(unittest.TestCase):
    def test_a_shader_settings_toml_names_is_used_by_the_deck_not_a_slide(self):
        deck = tempfile.mkdtemp()
        _write(os.path.join(deck, "slides.md"), "# One\n")  # nothing on a slide
        _write(os.path.join(deck, "settings.toml"),
               '[shader]\nfile = "includes/bg.sksl"\n')
        _write(os.path.join(deck, "includes", "bg.sksl"), "half4 main(float2 p) { return 0; }")
        entry = next(a for a in assets.scan(deck) if a["name"] == "bg.sksl")
        self.assertTrue(entry["used"])
        # Slide 0 is the deck itself: nothing on a slide points at it.
        self.assertEqual(entry["slides"], [0])


class ThroughTheTool(unittest.TestCase):
    """What refractplayer's asset window actually calls."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.out = os.path.join(self.deck, "out")
        os.makedirs(self.out)
        _write(os.path.join(self.deck, "slides.md"), "# One\n\n<kept.png>\n")
        _png(os.path.join(self.deck, "includes", "kept.png"))
        _png(os.path.join(self.deck, "includes", "orphan.png"))
        with open(os.path.join(self.out, "deck.json"), "w") as f:
            json.dump({"deck": os.path.basename(self.deck), "source": self.deck,
                       "slides": []}, f)

    def run_tool(self, *args):
        p = subprocess.run([sys.executable, ASSETS, self.out, *args],
                           capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    def test_list(self):
        rc, doc = self.run_tool("--list")
        self.assertEqual(rc, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["unused"], 1)
        self.assertEqual(sorted(a["name"] for a in doc["assets"]),
                         ["kept.png", "orphan.png"])

    def test_remove_moves_it_to_the_trash_rather_than_deleting_it(self):
        rc, doc = self.run_tool("--remove", os.path.join("includes", "orphan.png"))
        self.assertEqual(rc, 0)
        self.assertTrue(doc["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.deck, "includes", "orphan.png")))
        self.assertTrue(os.path.exists(os.path.join(self.out, ".trash", "includes",
                                                    "orphan.png")))

    def test_removing_something_in_use_is_refused(self):
        rc, doc = self.run_tool("--remove", os.path.join("includes", "kept.png"))
        self.assertEqual(rc, 1)
        self.assertFalse(doc["ok"])
        self.assertIn("slide 1", doc["error"])
        self.assertTrue(os.path.exists(os.path.join(self.deck, "includes", "kept.png")))

    def test_force_removes_something_in_use(self):
        rc, doc = self.run_tool("--remove", os.path.join("includes", "kept.png"), "--force")
        self.assertEqual(rc, 0)
        self.assertTrue(doc["used"])
        self.assertFalse(os.path.exists(os.path.join(self.deck, "includes", "kept.png")))

    def test_a_second_file_of_the_same_name_does_not_lose_the_first(self):
        target = os.path.join("includes", "orphan.png")
        self.run_tool("--remove", target)
        _png(os.path.join(self.deck, "includes", "orphan.png"), w=16)
        rc, doc = self.run_tool("--remove", target)
        self.assertEqual(rc, 0)
        trash = os.path.join(self.out, ".trash", "includes")
        self.assertEqual(sorted(os.listdir(trash)), ["orphan-2.png", "orphan.png"])

    def test_removing_something_that_is_not_there(self):
        rc, doc = self.run_tool("--remove", "includes/nope.png")
        self.assertEqual(rc, 1)
        self.assertIn("no includes/nope.png", doc["error"])

    def test_a_directory_that_is_not_a_deck(self):
        p = subprocess.run([sys.executable, ASSETS, tempfile.mkdtemp(), "--list"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest

from refractkit import history


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "player", "tools", "history.py")
REORDER = os.path.join(REPO, "player", "tools", "reorder.py")
SLIDE = os.path.join(REPO, "player", "tools", "slide.py")


class Ring(unittest.TestCase):
    """The stack itself, with no deck behind it."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.out = os.path.join(self.deck, "out")
        os.makedirs(self.out)
        self.md = os.path.join(self.deck, "slides.md")
        self.write("one")

    def write(self, text):
        with open(self.md, "w") as f:
            f.write(text)

    def read(self):
        with open(self.md) as f:
            return f.read()

    def edit(self, after, description="an edit"):
        before = self.read()
        history.record(self.out, "slides.md", before, after, description)
        self.write(after)

    def test_nothing_to_undo_at_the_start(self):
        self.assertIsNone(history.undo(self.out, self.deck))
        self.assertIsNone(history.redo(self.out, self.deck))
        self.assertEqual(history.describe(self.out)["undo"], None)

    def test_undo_and_redo_one_edit(self):
        self.edit("two", "the edit")
        self.assertEqual(history.describe(self.out)["undo"], "the edit")

        self.assertEqual(history.undo(self.out, self.deck)["description"], "the edit")
        self.assertEqual(self.read(), "one")
        self.assertEqual(history.describe(self.out)["redo"], "the edit")

        self.assertEqual(history.redo(self.out, self.deck)["description"], "the edit")
        self.assertEqual(self.read(), "two")

    def test_a_stack_of_edits_unwinds_in_order(self):
        for text in ("two", "three", "four"):
            self.edit(text, f"to {text}")
        for want in ("three", "two", "one"):
            history.undo(self.out, self.deck)
            self.assertEqual(self.read(), want)
        self.assertIsNone(history.undo(self.out, self.deck))
        for want in ("two", "three", "four"):
            history.redo(self.out, self.deck)
            self.assertEqual(self.read(), want)
        self.assertIsNone(history.redo(self.out, self.deck))

    def test_a_new_edit_drops_the_redone_future(self):
        self.edit("two")
        self.edit("three")
        history.undo(self.out, self.deck)
        self.assertEqual(self.read(), "two")
        self.edit("elsewhere")
        # "three" never happened now.
        self.assertIsNone(history.redo(self.out, self.deck))
        self.assertEqual(self.read(), "elsewhere")
        history.undo(self.out, self.deck)
        self.assertEqual(self.read(), "two")

    def test_an_edit_that_changes_nothing_is_not_recorded(self):
        self.edit("one")
        self.assertEqual(history.describe(self.out)["depth"], 0)

    def test_a_file_changed_outside_the_player_is_not_clobbered(self):
        # The case this exists for: slides.md edited in a terminal while the player was open.
        # Undo would otherwise replace that work with its own idea of the past.
        self.edit("two")
        self.write("edited by hand")
        with self.assertRaises(history.Conflict):
            history.undo(self.out, self.deck)
        self.assertEqual(self.read(), "edited by hand")
        # And the history is intact: the edit is still there to undo once the file is back.
        self.write("two")
        self.assertIsNotNone(history.undo(self.out, self.deck))

    def test_the_ring_is_bounded(self):
        for i in range(history.MAX_ENTRIES + 10):
            self.edit(f"text {i}")
        doc = history.load(self.out)
        self.assertEqual(len(doc["entries"]), history.MAX_ENTRIES)
        self.assertEqual(doc["cursor"], history.MAX_ENTRIES)
        # The oldest are the ones dropped, so the recent past still unwinds.
        for _ in range(history.MAX_ENTRIES):
            self.assertIsNotNone(history.undo(self.out, self.deck))
        self.assertIsNone(history.undo(self.out, self.deck))

    def test_a_corrupt_history_costs_undo_and_nothing_else(self):
        self.edit("two")
        with open(history.path_for(self.out), "w") as f:
            f.write("{not json")
        self.assertEqual(history.describe(self.out)["depth"], 0)
        self.assertIsNone(history.undo(self.out, self.deck))
        self.assertEqual(self.read(), "two")

    def test_a_history_from_another_version_is_ignored(self):
        self.edit("two")
        doc = history.load(self.out)
        doc["version"] = history.VERSION + 1
        history.save(self.out, doc)
        self.assertEqual(history.describe(self.out)["depth"], 0)

    def test_edits_to_different_files_unwind_independently(self):
        # An included sub-deck is a second file, and its edits are in the same stack.
        sub = os.path.join(self.deck, "includes", "intro")
        os.makedirs(sub)
        sub_md = os.path.join(sub, "slides.md")
        with open(sub_md, "w") as f:
            f.write("sub one")
        history.record(self.out, "includes/intro/slides.md", "sub one", "sub two", "sub edit")
        with open(sub_md, "w") as f:
            f.write("sub two")
        self.edit("two", "parent edit")

        history.undo(self.out, self.deck)
        self.assertEqual(self.read(), "one")
        history.undo(self.out, self.deck)
        with open(sub_md) as f:
            self.assertEqual(f.read(), "sub one")


class Tool(unittest.TestCase):
    """Undo over a real deck, through the tools that make the edits."""

    SLIDES = "# One\n\n---\n\n# Two\n\n---\n\n# Three\n"

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write(self.SLIDES)
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest(f"refract could not build the deck: {p.stderr.strip()[-200:]}")
        self.out = os.path.join(self.deck, "out")

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, tool, self.out, *args],
                              capture_output=True, text=True)

    def titles(self):
        with open(os.path.join(self.out, "deck.json")) as f:
            return [s["title"] for s in json.load(f)["slides"]]

    def test_a_reorder_can_be_undone(self):
        self.run_tool(REORDER, "--move", "0", "--to", "2")
        self.assertEqual(self.titles(), ["Two", "Three", "One"])

        p = self.run_tool(TOOL, "--undo", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"] and result["changed"] and result["rebuilt"])
        self.assertIn("move slide 1", result["description"])
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_a_delete_can_be_undone(self):
        # The one that matters most: there is nothing else to get the slide back from.
        self.run_tool(SLIDE, "--slide", "1", "--delete", "--json")
        self.assertEqual(self.titles(), ["One", "Three"])
        self.run_tool(TOOL, "--undo", "--json")
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_an_edit_can_be_undone(self):
        path = os.path.join(self.deck, "new.md")
        with open(path, "w") as f:
            f.write("# Renamed\n")
        self.run_tool(SLIDE, "--slide", "1", "--write", path, "--json")
        self.assertEqual(self.titles(), ["One", "Renamed", "Three"])
        self.run_tool(TOOL, "--undo", "--json")
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_several_edits_unwind_in_order(self):
        self.run_tool(SLIDE, "--slide", "0", "--new", "--json")
        self.run_tool(REORDER, "--move", "0", "--to", "3")
        self.run_tool(SLIDE, "--slide", "0", "--delete", "--json")
        for _ in range(3):
            p = self.run_tool(TOOL, "--undo", "--json")
            self.assertTrue(json.loads(p.stdout)["ok"], p.stdout)
        self.assertEqual(self.titles(), ["One", "Two", "Three"])
        with open(self.md) as f:
            self.assertEqual(f.read(), self.SLIDES)

    def test_list_says_what_would_happen(self):
        p = self.run_tool(TOOL, "--list")
        self.assertEqual(json.loads(p.stdout)["undo"], None)
        self.run_tool(REORDER, "--move", "0", "--to", "1")
        p = self.run_tool(TOOL, "--list")
        listing = json.loads(p.stdout)
        self.assertIn("move slide 1", listing["undo"])
        self.assertEqual(listing["depth"], 1)

    def test_nothing_to_undo_is_not_an_error(self):
        p = self.run_tool(TOOL, "--undo", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertIn("nothing to undo", result["description"])

    def test_a_hand_edited_file_refuses_rather_than_clobbering(self):
        self.run_tool(REORDER, "--move", "0", "--to", "2")
        with open(self.md, "a") as f:
            f.write("\n---\n\n# Added by hand\n")
        p = self.run_tool(TOOL, "--undo", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("changed outside", json.loads(p.stdout)["error"])
        with open(self.md) as f:
            self.assertIn("Added by hand", f.read())

    def test_one_mode_at_a_time(self):
        p = self.run_tool(TOOL, "--undo", "--redo")
        self.assertEqual(p.returncode, 2)
        self.assertIn("exactly one", p.stderr)

    def test_a_directory_that_is_not_a_deck(self):
        p = subprocess.run([sys.executable, TOOL, tempfile.mkdtemp(), "--list"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("no deck.json", json.loads(p.stdout)["error"])


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest

from refractkit import chunks
from refractkit import markdown as md


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "player", "tools", "slide.py")


class ReadChunk(unittest.TestCase):
    DECK = "# One\n\n---\n\n:: content\n# Two\nbody\n\n---\n\n# Three\n"

    def test_reads_a_block_without_its_padding(self):
        # The blank lines around a block are the file's spacing, not the slide's — an editor
        # that opened with them would accumulate a pair on every save.
        self.assertEqual(chunks.read_chunk(self.DECK, 1), ":: content\n# Two\nbody")

    def test_reads_the_first_and_last(self):
        self.assertEqual(chunks.read_chunk(self.DECK, 0), "# One")
        self.assertEqual(chunks.read_chunk(self.DECK, 2), "# Three")

    def test_a_block_with_no_separators(self):
        self.assertEqual(chunks.read_chunk("# Only\nbody\n", 0), "# Only\nbody")

    def test_an_empty_block(self):
        self.assertEqual(chunks.read_chunk("# A\n---\n---\n# B\n", 1), "")

    def test_out_of_range(self):
        for index in (-1, 3, 99):
            with self.subTest(index=index):
                with self.assertRaises(IndexError):
                    chunks.read_chunk(self.DECK, index)

    def test_keeps_internal_blank_lines(self):
        text = "# A\n---\nfirst\n\n\nlast\n---\n# C\n"
        self.assertEqual(chunks.read_chunk(text, 1), "first\n\n\nlast")


class ReplaceChunk(unittest.TestCase):
    DECK = "# One\n\n---\n\n:: content\n# Two\nbody\n\n---\n\n# Three\n"

    def test_replaces_only_that_block(self):
        out = chunks.replace_chunk(self.DECK, 1, "# Second\nnew body")
        self.assertEqual(out, "# One\n\n---\n\n# Second\nnew body\n\n---\n\n# Three\n")

    def test_writing_back_what_was_read_changes_nothing(self):
        # The property the editor rests on: opening a slide and saving it untouched must
        # leave the file byte for byte as it was, or every visit shows up in the diff.
        for i in range(chunks.count_chunks(self.DECK)):
            with self.subTest(block=i):
                same = chunks.replace_chunk(self.DECK, i, chunks.read_chunk(self.DECK, i))
                self.assertEqual(same, self.DECK)

    def test_holds_for_awkward_spacing(self):
        for text in ("a\n---\nb",
                     "a\n---\nb\n",
                     "\n---\na\n",
                     "a\n\n\n---\n\n\nb\n",
                     "---\n---\n",
                     "a\n  ---  \nb\n",
                     "# One\n\n```\n---\n```\n---\n# Two\n"):
            for i in range(chunks.count_chunks(text)):
                with self.subTest(text=text, block=i):
                    self.assertEqual(
                        chunks.replace_chunk(text, i, chunks.read_chunk(text, i)), text)

    def test_a_multi_line_replacement(self):
        out = chunks.replace_chunk("a\n---\nb\n", 1, "one\ntwo\nthree")
        self.assertEqual(out, "a\n---\none\ntwo\nthree\n")
        self.assertEqual([s.get("title") for s in md.parse_markdown(out)], [None, None])

    def test_emptying_a_block(self):
        out = chunks.replace_chunk("# A\n---\n# B\n---\n# C\n", 1, "")
        self.assertEqual(out, "# A\n---\n---\n# C\n")
        # An empty block produces no slide, so the deck is two slides now.
        self.assertEqual([s["title"] for s in md.parse_markdown(out)], ["A", "C"])

    def test_the_replacement_is_trimmed(self):
        # An editor hands back whatever is in its buffer, trailing newline and all.
        a = chunks.replace_chunk("x\n---\ny\n", 1, "new")
        b = chunks.replace_chunk("x\n---\ny\n", 1, "\n\nnew\n\n")
        self.assertEqual(a, b)

    def test_separators_are_untouched(self):
        out = chunks.replace_chunk("a\n  ---  \nb\n", 0, "z")
        self.assertIn("  ---  ", out)

    def test_out_of_range(self):
        for index in (-1, 3, 99):
            with self.subTest(index=index):
                with self.assertRaises(IndexError):
                    chunks.replace_chunk(self.DECK, index, "x")

    def test_the_edit_lands_on_the_slide_the_parser_sees(self):
        # The point of the whole exercise: block N as this module counts it is slide N as
        # refract's parser counts it.
        text = "# One\n---\n\n---\n# Three\n---\n# Four\n"
        slides = md.parse_markdown(text)
        target = slides[2]                        # "Four", from block 3
        out = chunks.replace_chunk(text, target["src_index"], "# Edited")
        self.assertEqual([s["title"] for s in md.parse_markdown(out)],
                         ["One", "Three", "Edited"])


class Tool(unittest.TestCase):
    """The CLI the editor shells out to."""

    SLIDES = (":: title\n# Hello\n"
              "---\n"
              ":: content steps\n# Bullets\n\n- one\n- two\n- three\n"
              "---\n"
              "# Last\n")

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

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL, self.out, *args],
                              capture_output=True, text=True)

    def read(self, slide):
        p = self.run_tool("--slide", str(slide), "--read")
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def write(self, slide, text, *extra):
        path = os.path.join(self.deck, "new.md")
        with open(path, "w") as f:
            f.write(text)
        return self.run_tool("--slide", str(slide), "--write", path, "--json", *extra)

    def titles(self):
        with open(os.path.join(self.out, "deck.json")) as f:
            return [s["title"] for s in json.load(f)["slides"]]

    def test_reads_a_slide(self):
        result = self.read(0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["file"], "slides.md")
        self.assertEqual(result["block"], 0)
        self.assertEqual(result["text"], ":: title\n# Hello")
        self.assertEqual(result["slides"], 1)

    def test_an_expanded_slide_says_how_many_share_its_block(self):
        # `steps` turns three bullets into three slides from one block; editing any of them
        # edits all three, and the editor has to be able to say so.
        result = self.read(1)
        self.assertEqual(result["slides"], 3)
        self.assertEqual(result["block"], 1)
        self.assertEqual(self.read(2)["block"], 1)
        self.assertEqual(self.read(3)["block"], 1)

    def test_writes_and_rebuilds(self):
        p = self.write(4, "# Renamed\n")
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"] and result["changed"] and result["rebuilt"])
        self.assertEqual(self.titles()[-1], "Renamed")

    def test_a_write_that_changes_nothing_is_reported_as_such(self):
        p = self.write(0, self.read(0)["text"])
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertFalse(result["changed"])
        self.assertFalse(result["rebuilt"])
        with open(self.md) as f:
            self.assertEqual(f.read(), self.SLIDES)

    def test_editing_an_expanded_slide_edits_the_block(self):
        p = self.write(2, ":: content steps\n# Bullets\n\n- one\n- two\n")
        self.assertEqual(p.returncode, 0, p.stderr)
        # Three steps became two, so the deck is a slide shorter.
        self.assertEqual(self.titles(), ["Hello", "Bullets", "Bullets", "Last"])

    def test_no_rebuild_leaves_the_deck_stale(self):
        before = self.titles()
        p = self.write(4, "# Renamed\n", "--no-rebuild")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)["rebuilt"])
        self.assertEqual(self.titles(), before)

    def test_the_build_options_are_replayed(self):
        subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck,
                        "--transitions"], capture_output=True, text=True)
        self.write(4, "# Renamed\n")
        with open(os.path.join(self.out, "deck.json")) as f:
            self.assertTrue(json.load(f)["build"]["transitions"],
                            "saving a slide dropped --transitions")

    def test_an_out_of_range_slide(self):
        p = self.run_tool("--slide", "99", "--read")
        self.assertEqual(p.returncode, 1)
        self.assertIn("out of range", json.loads(p.stdout)["error"])

    def test_a_directory_that_is_not_a_deck(self):
        p = subprocess.run([sys.executable, TOOL, tempfile.mkdtemp(), "--slide", "0", "--read"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("no deck.json", json.loads(p.stdout)["error"])

    def test_read_and_write_are_exclusive(self):
        p = self.run_tool("--slide", "0")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--read", p.stderr)

    def test_writing_leaves_no_temp_file(self):
        self.write(4, "# Renamed\n")
        self.assertEqual([f for f in os.listdir(self.deck) if f.endswith(".tmp")], [])

    def test_a_deck_without_provenance_cannot_be_edited(self):
        path = os.path.join(self.out, "deck.json")
        with open(path) as f:
            doc = json.load(f)
        for slide in doc["slides"]:
            slide.pop("src_index", None)
        with open(path, "w") as f:
            json.dump(doc, f)
        p = self.run_tool("--slide", "0", "--read")
        self.assertEqual(p.returncode, 1)
        self.assertIn("src_index", json.loads(p.stdout)["error"])

    def test_a_round_trip_through_the_tool_is_byte_identical(self):
        for slide in range(len(self.titles())):
            with self.subTest(slide=slide):
                self.write(slide, self.read(slide)["text"], "--no-rebuild")
        with open(self.md) as f:
            self.assertEqual(f.read(), self.SLIDES)


if __name__ == "__main__":
    unittest.main()

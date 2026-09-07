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


class InsertAndDeleteChunk(unittest.TestCase):
    """Adding and removing whole blocks — a slide's worth of markdown at a time."""

    PADDED = "# A\n\n---\n\n# B\n\n---\n\n# C\n"
    TIGHT = "# A\n---\n# B\n---\n# C\n"

    def titles(self, text):
        return [s.get("title") for s in md.parse_markdown(text)]

    def test_insert_in_the_middle(self):
        out = chunks.insert_chunk(self.PADDED, 1, "# New")
        self.assertEqual(self.titles(out), ["A", "New", "B", "C"])

    def test_insert_at_each_end(self):
        self.assertEqual(self.titles(chunks.insert_chunk(self.PADDED, 0, "# New")),
                         ["New", "A", "B", "C"])
        self.assertEqual(self.titles(chunks.insert_chunk(self.PADDED, 3, "# New")),
                         ["A", "B", "C", "New"])

    def test_the_deck_s_own_spacing_is_kept(self):
        # A deck written with a blank line either side of every `---` keeps them, and one
        # written tight stays tight: adding a slide should read as a slide in the diff, not
        # as a reformat.
        for i in range(4):
            with self.subTest(at=i):
                padded = chunks.insert_chunk(self.PADDED, i, "# New")
                self.assertNotIn("---\n# ", padded)
                self.assertNotIn("\n\n\n", padded)
                tight = chunks.insert_chunk(self.TIGHT, i, "# New")
                self.assertNotIn("\n\n", tight)

    def test_a_file_never_starts_or_ends_blank(self):
        for text in (self.PADDED, self.TIGHT):
            for i in range(4):
                out = chunks.insert_chunk(text, i, "# New")
                self.assertFalse(out.startswith("\n"), out)
                self.assertFalse(out.endswith("\n\n"), out)

    def test_insert_then_delete_restores_the_file(self):
        for text in (self.PADDED, self.TIGHT):
            for i in range(chunks.count_chunks(text) + 1):
                with self.subTest(text=text, at=i):
                    grown = chunks.insert_chunk(text, i, "# New")
                    self.assertEqual(chunks.delete_chunk(grown, i), text)

    def test_an_empty_new_block_produces_no_slide(self):
        out = chunks.insert_chunk(self.PADDED, 1, "")
        self.assertEqual(chunks.count_chunks(out), 4)
        self.assertEqual(self.titles(out), ["A", "B", "C"])

    def test_delete(self):
        self.assertEqual(self.titles(chunks.delete_chunk(self.PADDED, 0)), ["B", "C"])
        self.assertEqual(self.titles(chunks.delete_chunk(self.PADDED, 1)), ["A", "C"])
        self.assertEqual(self.titles(chunks.delete_chunk(self.PADDED, 2)), ["A", "B"])

    def test_the_last_slide_cannot_be_deleted(self):
        # A deck of no slides is not a deck, and there would be nothing left to put one back
        # into: the file would have no blocks to address.
        with self.assertRaises(ValueError):
            chunks.delete_chunk("# Only\n", 0)

    def test_out_of_range(self):
        for i in (-1, 4, 99):
            with self.subTest(at=i):
                with self.assertRaises(IndexError):
                    chunks.insert_chunk(self.PADDED, i, "x")
        for i in (-1, 3, 99):
            with self.subTest(at=i):
                with self.assertRaises(IndexError):
                    chunks.delete_chunk(self.PADDED, i)

    def test_the_neighbouring_blocks_are_untouched(self):
        out = chunks.insert_chunk(self.PADDED, 1, "# New")
        for i, want in ((0, "# A"), (2, "# B"), (3, "# C")):
            self.assertEqual(chunks.read_chunk(out, i), want)


class SplitMergeDuplicate(unittest.TestCase):
    """Breaking a slide in two, joining two back, and copying one."""

    DECK = "# A\n\n---\n\n# B\nline one\nline two\n\n---\n\n# C\n"

    def titles(self, text):
        return [s.get("title") for s in md.parse_markdown(text)]

    def test_split(self):
        out = chunks.split_chunk(self.DECK, 1, 1)
        self.assertEqual(chunks.count_chunks(out), 4)
        self.assertEqual(chunks.read_chunk(out, 1), "# B")
        self.assertEqual(chunks.read_chunk(out, 2), "line one\nline two")
        self.assertEqual(self.titles(out), ["A", "B", None, "C"])

    def test_split_anywhere_in_the_middle(self):
        out = chunks.split_chunk(self.DECK, 1, 2)
        self.assertEqual(chunks.read_chunk(out, 1), "# B\nline one")
        self.assertEqual(chunks.read_chunk(out, 2), "line two")

    def test_split_at_an_end_is_refused(self):
        # Splitting before the first line or after the last would make a slide out of
        # nothing, which is what `N` is for.
        for line in (0, 3, 99, -1):
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    chunks.split_chunk(self.DECK, 1, line)

    def test_split_leaves_the_neighbours_alone(self):
        out = chunks.split_chunk(self.DECK, 1, 1)
        self.assertEqual(chunks.read_chunk(out, 0), "# A")
        self.assertEqual(chunks.read_chunk(out, 3), "# C")

    def test_merge(self):
        out = chunks.merge_chunk(self.DECK, 1)
        self.assertEqual(chunks.count_chunks(out), 2)
        self.assertEqual(chunks.read_chunk(out, 1), "# B\nline one\nline two\n\nC")
        self.assertEqual(self.titles(out), ["A", "B"])

    def test_the_second_heading_is_demoted(self):
        # A slide has one title. The second half's heading becomes body text — which is also
        # what keeps the result buildable, since a `#` line in body breaks json2rc.
        out = chunks.merge_chunk("# A\nbody\n---\n# B\nmore\n", 0)
        self.assertEqual(chunks.read_chunk(out, 0), "# A\nbody\n\nB\nmore")
        self.assertEqual(self.titles(out), ["A"])

    def test_a_heading_is_demoted_even_with_no_title_above_it(self):
        # A title has to be a slide's first line, so once this half is body its heading could
        # never be a title again — and left as `#` it would break the build.
        out = chunks.merge_chunk("no title\n---\n# B\nmore\n", 0)
        self.assertEqual(chunks.read_chunk(out, 0), "no title\n\nB\nmore")

    def test_merge_puts_a_blank_line_where_the_separator_was(self):
        # Two paragraphs that were two slides are still two paragraphs; run together they
        # would be one.
        out = chunks.merge_chunk("first para\n---\nsecond para\n", 0)
        self.assertEqual(chunks.read_chunk(out, 0), "first para\n\nsecond para")

    def test_merge_at_the_end_is_refused(self):
        with self.assertRaises(ValueError):
            chunks.merge_chunk(self.DECK, 2)
        with self.assertRaises(IndexError):
            chunks.merge_chunk(self.DECK, 9)

    def test_split_then_merge_puts_the_slides_back(self):
        # Byte-for-byte only up to the blank line merge leaves behind, which it cannot know
        # was not there before — so the check is that the deck is the same deck.
        out = chunks.merge_chunk(chunks.split_chunk(self.DECK, 1, 1), 1)
        self.assertEqual(chunks.count_chunks(out), chunks.count_chunks(self.DECK))
        self.assertEqual(self.titles(out), self.titles(self.DECK))
        self.assertEqual(chunks.read_chunk(out, 1).split(),
                         chunks.read_chunk(self.DECK, 1).split())

    def test_duplicate(self):
        out = chunks.duplicate_chunk(self.DECK, 1)
        self.assertEqual(chunks.count_chunks(out), 4)
        self.assertEqual(chunks.read_chunk(out, 1), chunks.read_chunk(out, 2))
        self.assertEqual(self.titles(out), ["A", "B", "B", "C"])

    def test_duplicate_the_last_slide(self):
        out = chunks.duplicate_chunk(self.DECK, 2)
        self.assertEqual(self.titles(out), ["A", "B", "C", "C"])

    def test_duplicate_then_delete_restores_the_file(self):
        for i in range(3):
            with self.subTest(block=i):
                self.assertEqual(
                    chunks.delete_chunk(chunks.duplicate_chunk(self.DECK, i), i + 1),
                    self.DECK)

    def test_a_tight_deck_stays_tight(self):
        tight = "# A\n---\n# B\nbody\n---\n# C\n"
        for out in (chunks.split_chunk(tight, 1, 1), chunks.duplicate_chunk(tight, 1)):
            self.assertNotIn("\n\n\n", out)
            self.assertFalse(out.startswith("\n"))
            self.assertFalse(out.endswith("\n\n"))

    def test_out_of_range(self):
        for i in (-1, 3, 99):
            with self.subTest(block=i):
                with self.assertRaises(IndexError):
                    chunks.split_chunk(self.DECK, i, 1)
                with self.assertRaises(IndexError):
                    chunks.duplicate_chunk(self.DECK, i)


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

    def test_new_slide_after_and_before(self):
        p = self.run_tool("--slide", "0", "--new", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["ok"])
        self.assertEqual(self.titles()[:2], ["Hello", "New slide"])

        p = self.run_tool("--slide", "0", "--new", "--before", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.titles()[0], "New slide")

    def test_delete_a_slide(self):
        p = self.run_tool("--slide", "4", "--delete", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"] and result["rebuilt"])
        self.assertEqual(result["removed"], 1)
        self.assertNotIn("Last", self.titles())

    def test_deleting_an_expanded_slide_removes_all_of_its_steps(self):
        # One block, three slides. Removing the block removes all three, and says how many
        # so the view can warn before it happens rather than after.
        p = self.run_tool("--slide", "2", "--delete", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["removed"], 3)
        self.assertEqual(self.titles(), ["Hello", "Last"])

    def test_the_last_slide_cannot_be_deleted(self):
        for _ in range(2):
            self.run_tool("--slide", "0", "--delete", "--json")
        self.assertEqual(len(self.titles()), 1)
        p = self.run_tool("--slide", "0", "--delete", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("at least one", json.loads(p.stdout)["error"])

    def test_only_one_mode_at_a_time(self):
        p = self.run_tool("--slide", "0", "--new", "--delete")
        self.assertEqual(p.returncode, 2)
        self.assertIn("exactly one", p.stderr)

    def test_a_round_trip_through_the_tool_is_byte_identical(self):
        for slide in range(len(self.titles())):
            with self.subTest(slide=slide):
                self.write(slide, self.read(slide)["text"], "--no-rebuild")
        with open(self.md) as f:
            self.assertEqual(f.read(), self.SLIDES)


class WholeFile(unittest.TestCase):
    """Editing a whole file rather than one slide's block — `slides.md`, and `settings.toml`,
    which was the last thing that still needed a terminal."""

    SLIDES = "# One\n\n---\n\n# Two\n"

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write(self.SLIDES)
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest("refract could not build the deck")
        self.out = os.path.join(self.deck, "out")

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL, self.out, *args],
                              capture_output=True, text=True)

    def write_via_tool(self, name, text, *extra):
        path = os.path.join(self.deck, "new.txt")
        with open(path, "w") as f:
            f.write(text)
        return self.run_tool("--file", name, "--write", path, "--json", *extra)

    def test_reads_a_file(self):
        p = self.run_tool("--file", "slides.md", "--read")
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"] and result["exists"])
        self.assertEqual(result["text"], self.SLIDES)

    def test_a_file_that_is_not_there_reads_as_empty(self):
        # A deck with no settings.toml is an ordinary deck: the editor opens an empty one.
        result = json.loads(self.run_tool("--file", "settings.toml", "--read").stdout)
        self.assertTrue(result["ok"])
        self.assertFalse(result["exists"])
        self.assertEqual(result["text"], "")

    def test_writing_settings_creates_it_and_rebuilds_every_slide(self):
        p = self.write_via_tool("settings.toml", '[theme]\nbackground = "#FF102030"\n')
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"] and result["changed"] and result["rebuilt"])
        self.assertTrue(os.path.isfile(os.path.join(self.deck, "settings.toml")))
        # The theme is in every document, so the incremental build touches all of them.
        self.assertEqual(sorted(result["outputs"]), ["01_one.rc", "02_two.rc"])

    def test_editing_the_whole_deck(self):
        self.write_via_tool("slides.md", "# Only\n")
        with open(os.path.join(self.out, "deck.json")) as f:
            self.assertEqual([s["title"] for s in json.load(f)["slides"]], ["Only"])

    def test_an_unchanged_write_is_reported_as_such(self):
        result = json.loads(self.write_via_tool("slides.md", self.SLIDES).stdout)
        self.assertFalse(result["changed"])
        self.assertFalse(result["rebuilt"])

    def test_a_whole_file_edit_can_be_undone(self):
        self.write_via_tool("slides.md", "# Only\n")
        subprocess.run([sys.executable, os.path.join(REPO, "player", "tools", "history.py"),
                        self.out, "--undo", "--json"], capture_output=True, text=True)
        with open(self.md) as f:
            self.assertEqual(f.read(), self.SLIDES)

    def test_a_path_outside_the_deck_is_refused(self):
        # This is reached from a window; a path that could climb out is not a thing to offer.
        for bad in ("../escape.md", "../../etc/passwd"):
            with self.subTest(path=bad):
                p = self.run_tool("--file", bad, "--read")
                self.assertEqual(p.returncode, 1)
                self.assertIn("outside the deck", json.loads(p.stdout)["error"])

    def test_a_file_and_a_slide_are_exclusive(self):
        p = self.run_tool("--file", "slides.md", "--slide", "0", "--read")
        self.assertEqual(p.returncode, 2)
        self.assertIn("exactly one", p.stderr)

    def test_the_block_operations_need_a_slide(self):
        p = self.run_tool("--file", "slides.md", "--delete")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--slide", p.stderr)


if __name__ == "__main__":
    unittest.main()

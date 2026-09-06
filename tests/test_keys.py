import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

from refractkit import chunks, keys, reorder


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REORDER = os.path.join(REPO, "player", "tools", "reorder.py")
SLIDE = os.path.join(REPO, "player", "tools", "slide.py")
WEB = os.path.join(REPO, "player", "tools", "web.py")


class Permutation(unittest.TestCase):
    """Where each block went — the thing everything keyed by position has to follow."""

    def test_an_unmoved_deck_is_the_identity(self):
        self.assertEqual(chunks.permutation([0, 1, 2]), {0: 0, 1: 1, 2: 2})

    def test_move(self):
        # [A B C] with A moved to the end is [B C A]: A is now 2, B is 0, C is 1.
        self.assertEqual(chunks.permutation(chunks.move_order(3, 0, 2)), {1: 0, 2: 1, 0: 2})
        self.assertEqual(chunks.permutation(chunks.move_order(3, 2, 0)), {2: 0, 0: 1, 1: 2})

    def test_move_a_range(self):
        self.assertEqual(chunks.permutation(chunks.move_range_order(4, 0, 1, 2)),
                         {2: 0, 3: 1, 0: 2, 1: 3})

    def test_insert_shifts_what_follows_and_the_new_block_has_no_past(self):
        moved = chunks.permutation(chunks.insert_order(3, 1))
        self.assertEqual(moved, {0: 0, 1: 2, 2: 3})
        # Nothing lands on position 1: that is the new block, and no old one was there.
        self.assertNotIn(1, moved.values())

    def test_delete_drops_the_block_and_closes_the_gap(self):
        moved = chunks.permutation(chunks.delete_order(3, 1))
        self.assertEqual(moved, {0: 0, 2: 1})
        self.assertNotIn(1, moved)   # the deleted block has nowhere to go

    def test_the_permutation_matches_what_the_edit_actually_did(self):
        """The property that matters: block `old` before the edit is block `new` after it.

        These are two implementations of the same list manipulation — one on the text, one on
        the indices — and nothing but this keeps them agreeing.
        """
        four = "# A\n---\n# B\n---\n# C\n---\n# D\n"
        three = "# A\n---\n# B\nbody\n---\n# C\n"
        # (what it is called, source, edited source, the order it should have produced, and
        # any block whose *text* the edit changed rather than merely moved).
        cases = [
            ("move to the end", four, reorder.move_chunk(four, 0, 3),
             chunks.move_order(4, 0, 3), None),
            ("move to the front", four, reorder.move_chunk(four, 3, 0),
             chunks.move_order(4, 3, 0), None),
            ("move one along", four, reorder.move_chunk(four, 1, 2),
             chunks.move_order(4, 1, 2), None),
            ("move a pair", four, reorder.move_chunks(four, 0, 1, 2),
             chunks.move_range_order(4, 0, 1, 2), None),
            ("move a pair back", four, reorder.move_chunks(four, 2, 3, 0),
             chunks.move_range_order(4, 2, 3, 0), None),
            ("insert", four, chunks.insert_chunk(four, 2, "# New"),
             chunks.insert_order(4, 2), None),
            ("delete", four, chunks.delete_chunk(four, 1),
             chunks.delete_order(4, 1), None),
            ("duplicate", four, chunks.duplicate_chunk(four, 1),
             chunks.insert_order(4, 2), None),
            ("split", three, chunks.split_chunk(three, 1, 1),
             chunks.insert_order(3, 2), 1),
            ("merge", four, chunks.merge_chunk(four, 1),
             chunks.delete_order(4, 2), 1),
        ]
        for name, source, edited, order, grew in cases:
            with self.subTest(edit=name):
                before = chunks.chunk_texts(source)
                after = chunks.chunk_texts(edited)
                for old, new in chunks.permutation(order).items():
                    # A split leaves half of its block behind and a merge absorbs the next
                    # one into it; that block's text changes, its position does not.
                    if old == grew:
                        continue
                    self.assertEqual(after[new].strip(), before[old].strip(),
                                     f"{name}: block {old} should now be block {new}")


class Keys(unittest.TestCase):
    def test_parse_and_make(self):
        self.assertEqual(keys.parse("slides.md#3.0"), ("slides.md", 3, 0))
        self.assertEqual(keys.parse("includes/a/slides.md#12.2"),
                         ("includes/a/slides.md", 12, 2))
        self.assertEqual(keys.make("slides.md", 3, 1), "slides.md#3.1")
        for bad in ("", "slides.md", "slides.md#x.0", "slides.md#1"):
            with self.subTest(key=bad):
                self.assertIsNone(keys.parse(bad))

    def test_remap_follows_the_block(self):
        moved = chunks.permutation(chunks.move_order(3, 0, 2))
        self.assertEqual(keys.remap("slides.md#0.0", "slides.md", moved), "slides.md#2.0")
        self.assertEqual(keys.remap("slides.md#1.1", "slides.md", moved), "slides.md#0.1")

    def test_the_step_is_carried_across(self):
        # The several slides one block produced all move together, keeping their order.
        moved = chunks.permutation(chunks.move_order(3, 0, 2))
        for step in range(4):
            self.assertEqual(keys.remap(f"slides.md#0.{step}", "slides.md", moved),
                             f"slides.md#2.{step}")

    def test_another_file_is_left_alone(self):
        # An edit to one deck's markdown says nothing about a sub-deck's blocks.
        moved = chunks.permutation(chunks.move_order(3, 0, 2))
        self.assertEqual(keys.remap("includes/a/slides.md#0.0", "slides.md", moved),
                         "includes/a/slides.md#0.0")

    def test_a_deleted_block_has_no_key(self):
        moved = chunks.permutation(chunks.delete_order(3, 1))
        self.assertIsNone(keys.remap("slides.md#1.0", "slides.md", moved))

    def test_remap_mapping_drops_what_is_gone(self):
        moved = chunks.permutation(chunks.delete_order(3, 0))
        out = keys.remap_mapping({"slides.md#0.0": "01", "slides.md#1.0": "02",
                                  "slides.md#2.0": "03"}, "slides.md", moved)
        self.assertEqual(out, {"slides.md#0.0": "02", "slides.md#1.0": "03"})

    def test_something_that_is_not_a_key_is_passed_through(self):
        self.assertEqual(keys.remap("whatever", "slides.md", {}), "whatever")


class Follow(unittest.TestCase):
    """Moving the keys in the two files that use them."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.out = os.path.join(self.deck, "out")
        os.makedirs(os.path.join(self.deck, "voice"))
        os.makedirs(self.out)
        with open(keys.voice_index_path(self.deck), "w") as f:
            json.dump({"version": 1, "slides": {"slides.md#0.0": "01", "slides.md#1.0": "02",
                                                "slides.md#2.0": "03"}}, f)
        with open(keys.timing_path(self.out), "w") as f:
            json.dump({"deck": "d", "total": 30, "slides": [
                {"key": "slides.md#0.0", "file": "01_a.rc", "start": 0, "duration": 10},
                {"key": "slides.md#1.0", "file": "02_b.rc", "start": 10, "duration": 10},
                {"key": "slides.md#2.0", "file": "03_c.rc", "start": 20, "duration": 10}]}, f)

    def index(self):
        with open(keys.voice_index_path(self.deck)) as f:
            return json.load(f)["slides"]

    def trace(self):
        with open(keys.timing_path(self.out)) as f:
            return {e["key"]: e["file"] for e in json.load(f)["slides"]}

    def test_a_move_takes_both_with_it(self):
        moved = chunks.permutation(chunks.move_order(3, 0, 2))
        keys.follow(self.deck, self.out, "slides.md", moved)
        self.assertEqual(self.index(), {"slides.md#2.0": "01", "slides.md#0.0": "02",
                                        "slides.md#1.0": "03"})
        # Each entry still names the slide it timed, under that slide's new key.
        self.assertEqual(self.trace()["slides.md#2.0"], "01_a.rc")

    def test_a_delete_drops_the_entries_for_the_block_that_went(self):
        moved = chunks.permutation(chunks.delete_order(3, 0))
        keys.follow(self.deck, self.out, "slides.md", moved)
        self.assertEqual(self.index(), {"slides.md#0.0": "02", "slides.md#1.0": "03"})
        self.assertEqual(len(self.trace()), 2)

    def test_a_deck_with_no_recording_is_not_an_error(self):
        bare = tempfile.mkdtemp()
        os.makedirs(os.path.join(bare, "out"))
        self.assertEqual(keys.follow(bare, os.path.join(bare, "out"), "slides.md", {}), [])

    def test_a_trace_without_keys_is_left_alone(self):
        # Written before keys existed: it goes on being matched by filename.
        with open(keys.timing_path(self.out), "w") as f:
            json.dump({"slides": [{"file": "01_a.rc", "start": 0, "duration": 5}]}, f)
        keys.follow(self.deck, self.out, "slides.md",
                    chunks.permutation(chunks.move_order(3, 0, 2)))
        with open(keys.timing_path(self.out)) as f:
            self.assertEqual(json.load(f)["slides"][0]["file"], "01_a.rc")


def _wav(path, samples=400):
    data = b"\x00\x00" * samples
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
                + b"data" + struct.pack("<I", len(data)) + data)


class ThroughTheTools(unittest.TestCase):
    """A deck with narration, edited the way the player edits it.

    The thing this is here for: a slide's narration and its timings must still be its own
    after the blocks have been renumbered around them.
    """

    SLIDES = "# One\n\n---\n\n# Two\n\n---\n\n# Three\n"

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        with open(os.path.join(self.deck, "slides.md"), "w") as f:
            f.write(self.SLIDES)
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest(f"refract could not build the deck: {p.stderr.strip()[-200:]}")
        self.out = os.path.join(self.deck, "out")

        voice = os.path.join(self.deck, "voice")
        os.makedirs(voice, exist_ok=True)
        index = {}
        for rec in self.manifest()["slides"]:
            stem = rec["file"][:2]
            _wav(os.path.join(voice, stem + ".wav"))
            index[f"{rec['src']}#{rec['src_index']}.0"] = stem
        with open(os.path.join(voice, "index.json"), "w") as f:
            json.dump({"version": 1, "slides": index}, f)

    def manifest(self):
        with open(os.path.join(self.out, "deck.json")) as f:
            return json.load(f)

    def pairing(self):
        """Slide title -> the wav stem the player would play for it."""
        with open(os.path.join(self.deck, "voice", "index.json")) as f:
            index = json.load(f)["slides"]
        return {rec["title"]: index.get(f"{rec['src']}#{rec['src_index']}.0")
                for rec in self.manifest()["slides"]}

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, tool, self.out, *args],
                              capture_output=True, text=True)

    def test_a_reorder_keeps_every_slide_with_its_own_narration(self):
        before = self.pairing()
        self.assertEqual(before, {"One": "01", "Two": "02", "Three": "03"})
        self.run_tool(REORDER, "--move", "0", "--to", "2")
        self.assertEqual([r["title"] for r in self.manifest()["slides"]],
                         ["Two", "Three", "One"])
        self.assertEqual(self.pairing(), before)

    def test_adding_a_slide_does_not_shift_the_narration_onto_it(self):
        self.run_tool(SLIDE, "--slide", "0", "--new", "--json")
        pairing = self.pairing()
        self.assertIsNone(pairing["New slide"])
        for title in ("One", "Two", "Three"):
            self.assertEqual(pairing[title], {"One": "01", "Two": "02", "Three": "03"}[title])

    def test_deleting_a_slide_takes_its_narration_out_of_the_index(self):
        self.run_tool(SLIDE, "--slide", "0", "--delete", "--json")
        self.assertEqual(self.pairing(), {"Two": "02", "Three": "03"})

    def test_undo_puts_the_narration_back_too(self):
        # The markdown and the index moved as one edit, so they come back as one.
        self.run_tool(REORDER, "--move", "0", "--to", "2")
        self.run_tool(os.path.join(REPO, "player", "tools", "history.py"), "--undo", "--json")
        self.assertEqual([r["title"] for r in self.manifest()["slides"]],
                         ["One", "Two", "Three"])
        self.assertEqual(self.pairing(), {"One": "01", "Two": "02", "Three": "03"})

    def test_the_web_export_pairs_the_audio_the_player_plays(self):
        self.run_tool(REORDER, "--move", "0", "--to", "2")
        web = os.path.join(self.deck, "web")
        p = subprocess.run([sys.executable, WEB, self.out, web, "--keep-wav"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-300:])
        with open(os.path.join(web, "deck.js")) as f:
            page = f.read()
        # "Two" is now the first slide; its narration is still 02.wav, not the 01.wav that
        # the old filename-based mapping would have reached for.
        title_to_audio = dict(zip(
            [r["title"] for r in self.manifest()["slides"]],
            [line.split('"')[3] for line in page.splitlines() if '"audio"' in line]))
        self.assertEqual(title_to_audio["Two"], "audio/02.wav")
        self.assertEqual(title_to_audio["One"], "audio/01.wav")


if __name__ == "__main__":
    unittest.main()

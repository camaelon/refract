import json
import os
import subprocess
import sys
import tempfile
import unittest

from refractkit import markdown as md
from refractkit import reorder


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "player", "tools", "reorder.py")


# A spread of shapes the splitter has to survive: separators with odd spacing, empty chunks,
# no trailing newline, CRLF, a `---` inside a fence, and the ordinary case.
FIXTURES = [
    "a\n---\nb\n",
    "a\n\n---\n\nb\n",
    "one\n---\ntwo\n---\nthree\n",
    "---\n---\n",
    "a\n---\n---\nb\n",
    "\n---\na\n",
    "a\n  ---  \nb\n",
    "a\n---\nb",
    "a\n\n\n---\n\n\nb",
    "no separators at all\n",
    "",
    "a\r\n---\r\nb\r\n",
    "# One\n\n```\nfront:\n---\nback\n```\n---\n# Two\n",
]


class SplitJoin(unittest.TestCase):
    def test_round_trip_is_exact(self):
        for text in FIXTURES:
            with self.subTest(text=text):
                chunks, seps = reorder.split_chunks(text)
                self.assertEqual(reorder.join_chunks(chunks, seps), text)

    def test_one_more_chunk_than_separator(self):
        for text in FIXTURES:
            with self.subTest(text=text):
                chunks, seps = reorder.split_chunks(text)
                self.assertEqual(len(chunks), len(seps) + 1)

    def test_empty_chunk_is_an_empty_line_list(self):
        chunks, seps = reorder.split_chunks("---\n---\n")
        self.assertEqual(chunks, [[], [], [""]])
        self.assertEqual(seps, ["---", "---"])

    def test_separator_spacing_is_kept_verbatim(self):
        _, seps = reorder.split_chunks("a\n  ---  \nb\n")
        self.assertEqual(seps, ["  ---  "])

    def test_chunk_texts(self):
        self.assertEqual(reorder.chunk_texts("a\n---\nb\n"), ["a", "b\n"])


class AgreesWithTheParser(unittest.TestCase):
    """Chunk numbering has to match `parse_markdown`, or a move edits the wrong block."""

    def test_same_chunk_count_as_the_slide_separator_regex(self):
        for text in FIXTURES:
            with self.subTest(text=text):
                self.assertEqual(reorder.count_chunks(text),
                                 len(md.SLIDE_SEP.split(text)))

    def test_src_index_addresses_the_right_chunk(self):
        text = "# One\n---\n\n---\n# Three\n---\n# Four\n"
        slides = md.parse_markdown(text)
        chunks = reorder.chunk_texts(text)
        # The blank chunk produced no slide, so the slides are 0, 2, 3 — not 0, 1, 2.
        self.assertEqual([s["src_index"] for s in slides], [0, 2, 3])
        for s in slides:
            self.assertIn(s["title"], chunks[s["src_index"]])

    def test_a_separator_inside_a_fence_is_a_boundary_for_both(self):
        # refract's parser splits on `---` even inside a code fence. That is arguably a bug,
        # but the reorder splitter must reproduce it exactly rather than be smarter.
        text = "# One\n\n```\n---\n```\n---\n# Two\n"
        self.assertEqual(reorder.count_chunks(text), 3)
        self.assertEqual([s["src_index"] for s in md.parse_markdown(text)], [0, 1, 2])


class MoveChunk(unittest.TestCase):
    THREE = "# One\nfirst\n---\n# Two\nsecond\n---\n# Three\nthird\n"

    def titles(self, text):
        return [s.get("title") for s in md.parse_markdown(text)]

    def test_move_first_to_last(self):
        out = reorder.move_chunk(self.THREE, 0, 2)
        self.assertEqual(self.titles(out), ["Two", "Three", "One"])

    def test_move_last_to_first(self):
        out = reorder.move_chunk(self.THREE, 2, 0)
        self.assertEqual(self.titles(out), ["Three", "One", "Two"])

    def test_move_forward_one(self):
        out = reorder.move_chunk(self.THREE, 0, 1)
        self.assertEqual(self.titles(out), ["Two", "One", "Three"])

    def test_move_backward_one(self):
        out = reorder.move_chunk(self.THREE, 2, 1)
        self.assertEqual(self.titles(out), ["One", "Three", "Two"])

    def test_no_op_returns_the_text_unchanged(self):
        for i in range(3):
            self.assertEqual(reorder.move_chunk(self.THREE, i, i), self.THREE)

    def test_move_and_move_back_restores_the_file(self):
        for src in range(3):
            for dst in range(3):
                with self.subTest(src=src, dst=dst):
                    there = reorder.move_chunk(self.THREE, src, dst)
                    back = reorder.move_chunk(there, dst, src)
                    self.assertEqual(back, self.THREE)

    def test_separator_count_is_preserved(self):
        out = reorder.move_chunk(self.THREE, 0, 2)
        self.assertEqual(out.count("\n---"), self.THREE.count("\n---"))

    def test_out_of_range_raises(self):
        for src, dst in ((3, 0), (0, 3), (-1, 0), (0, -1), (99, 99)):
            with self.subTest(src=src, dst=dst):
                with self.assertRaises(IndexError):
                    reorder.move_chunk(self.THREE, src, dst)

    def test_single_chunk_deck(self):
        text = "# Only\n"
        self.assertEqual(reorder.move_chunk(text, 0, 0), text)
        with self.assertRaises(IndexError):
            reorder.move_chunk(text, 0, 1)

    def test_trailing_newline_is_kept(self):
        out = reorder.move_chunk("a\n---\nb", 1, 0)
        self.assertEqual(reorder.chunk_texts(out)[0], "b")
        out2 = reorder.move_chunk(self.THREE, 2, 0)
        self.assertTrue(out2.endswith("\n"))

    def test_crlf_file_still_splits_and_moves(self):
        text = "# One\r\n---\r\n# Two\r\n"
        self.assertEqual(reorder.count_chunks(text), 2)
        out = reorder.move_chunk(text, 1, 0)
        self.assertTrue(out.startswith("# Two\r"))
        self.assertIn("\r\n---\r\n", out)


class MovePreservesContent(unittest.TestCase):
    """Whatever is in a chunk travels with it — notes, meta lines, stacks, panes, fences."""

    DECK = (
        ":: title\n# Hello\n*subtitle*\n"
        "---\n"
        ":: content : Alice\n# Bullets\n- one\n  - nested\n- two\n"
        "???\nSpeaker note for the bullets.\n"
        "---\n"
        ":: split [2:3]\n# Panes\nleft text\n+++\nright text\n"
        "---\n"
        "# Stacked\ntop\n===\nbottom\n"
        "---\n"
        "# Code\n\n```python\nx = 1\n---\ny = 2\n```\n"
    )

    def test_notes_survive_a_move(self):
        # The bullets chunk (index 1) carries a ??? note; move it to the front.
        out = reorder.move_chunk(self.DECK, 1, 0)
        slides = md.parse_markdown(out)
        self.assertEqual(slides[0]["title"], "Bullets")
        self.assertEqual(slides[0]["notes"], "Speaker note for the bullets.")

    def test_meta_line_travels_with_its_slide(self):
        out = reorder.move_chunk(self.DECK, 2, 0)
        slides = md.parse_markdown(out)
        self.assertEqual(slides[0]["meta"]["type"], "split")
        self.assertEqual(slides[0]["meta"]["ratio"], [2, 3])

    def test_every_slide_survives_a_full_reversal(self):
        before = md.parse_markdown(self.DECK)
        n = reorder.count_chunks(self.DECK)
        out = reorder.reorder_chunks(self.DECK, list(reversed(range(n))))
        after = md.parse_markdown(out)
        self.assertEqual(len(before), len(after))
        self.assertEqual([s["title"] for s in after],
                         list(reversed([s["title"] for s in before])))
        # Blocks are unchanged, only their order in the deck.
        by_title = {s["title"]: s["blocks"] for s in after}
        for s in before:
            self.assertEqual(by_title[s["title"]], s["blocks"])

    def test_moving_a_chunk_does_not_touch_its_neighbours_text(self):
        before = sorted(c.rstrip("\n") for c in reorder.chunk_texts(self.DECK))
        after = sorted(c.rstrip("\n") for c in reorder.chunk_texts(reorder.move_chunk(self.DECK, 0, 3)))
        self.assertEqual(before, after)


class MoveChunks(unittest.TestCase):
    """Several blocks travelling as one — a whole section, or a whole included sub-deck."""

    FOUR = "# One\n---\n# Two\n---\n# Three\n---\n# Four\n"

    def titles(self, text):
        return [s.get("title") for s in md.parse_markdown(text)]

    def test_move_a_pair_forward(self):
        out = reorder.move_chunks(self.FOUR, 0, 1, 2)
        self.assertEqual(self.titles(out), ["Three", "Four", "One", "Two"])

    def test_move_a_pair_backward(self):
        out = reorder.move_chunks(self.FOUR, 2, 3, 0)
        self.assertEqual(self.titles(out), ["Three", "Four", "One", "Two"])

    def test_the_block_keeps_its_internal_order(self):
        out = reorder.move_chunks(self.FOUR, 0, 2, 1)
        self.assertEqual(self.titles(out), ["Four", "One", "Two", "Three"])

    def test_a_single_chunk_matches_move_chunk(self):
        for src in range(4):
            for dst in range(4):
                with self.subTest(src=src, dst=dst):
                    self.assertEqual(reorder.move_chunks(self.FOUR, src, src, dst),
                                     reorder.move_chunk(self.FOUR, src, dst))

    def test_landing_where_it_started_is_a_no_op(self):
        self.assertEqual(reorder.move_chunks(self.FOUR, 1, 2, 1), self.FOUR)

    def test_move_and_move_back_restores_the_file(self):
        for first in range(4):
            for last in range(first, 4):
                size = last - first + 1
                for dst in range(4 - size + 1):
                    with self.subTest(first=first, last=last, dst=dst):
                        there = reorder.move_chunks(self.FOUR, first, last, dst)
                        back = reorder.move_chunks(there, dst, dst + size - 1, first)
                        self.assertEqual(back, self.FOUR)

    def test_every_move_is_a_permutation(self):
        before = sorted(c.rstrip("\n") for c in reorder.chunk_texts(self.FOUR))
        for first in range(4):
            for last in range(first, 4):
                size = last - first + 1
                for dst in range(4 - size + 1):
                    out = reorder.move_chunks(self.FOUR, first, last, dst)
                    after = sorted(c.rstrip("\n") for c in reorder.chunk_texts(out))
                    self.assertEqual(after, before)

    def test_the_whole_deck_can_only_stay_put(self):
        self.assertEqual(reorder.move_chunks(self.FOUR, 0, 3, 0), self.FOUR)
        with self.assertRaises(IndexError):
            reorder.move_chunks(self.FOUR, 0, 3, 1)

    def test_out_of_range_raises(self):
        for first, last, dst in ((0, 4, 0), (-1, 1, 0), (2, 1, 0), (0, 1, 3), (0, 1, -1)):
            with self.subTest(first=first, last=last, dst=dst):
                with self.assertRaises(IndexError):
                    reorder.move_chunks(self.FOUR, first, last, dst)

    def test_notes_and_meta_travel_with_the_block(self):
        deck = (":: title\n# Top\n"
                "---\n"
                ":: section\n# Part\n"
                "---\n"
                "# Body\n???\na note\n"
                "---\n"
                "# Tail\n")
        out = reorder.move_chunks(deck, 1, 2, 0)     # the section and its slide, to the front
        slides = md.parse_markdown(out)
        self.assertEqual([s["title"] for s in slides], ["Part", "Body", "Top", "Tail"])
        self.assertEqual(slides[0]["meta"]["type"], "section")
        self.assertEqual(slides[1]["notes"], "a note")


class ReorderChunks(unittest.TestCase):
    THREE = "# One\n---\n# Two\n---\n# Three\n"

    def test_identity_permutation_is_a_no_op(self):
        self.assertEqual(reorder.reorder_chunks(self.THREE, [0, 1, 2]), self.THREE)

    def test_reverse(self):
        out = reorder.reorder_chunks(self.THREE, [2, 1, 0])
        self.assertEqual([s["title"] for s in md.parse_markdown(out)],
                         ["Three", "Two", "One"])

    def test_rejects_a_non_permutation(self):
        for bad in ([0, 1], [0, 1, 1], [0, 1, 3], [], [0, 1, 2, 3]):
            with self.subTest(order=bad):
                with self.assertRaises(ValueError):
                    reorder.reorder_chunks(self.THREE, bad)


def _slide(index, src_index, src="slides.md", title=""):
    return {"index": index, "src": src, "src_index": src_index, "title": title,
            "file": f"{index:02d}.rc"}


class PlanMove(unittest.TestCase):
    # Four rendered slides from three chunks: chunk 1 was expanded into two fragment steps.
    SLIDES = [_slide(0, 0, title="One"),
              _slide(1, 1, title="Two"),
              _slide(2, 1, title="Two"),
              _slide(3, 2, title="Three")]

    def test_maps_slide_indices_to_chunk_indices(self):
        self.assertEqual(reorder.plan_move(self.SLIDES, 0, 3), ("slides.md", 0, 2))

    def test_an_expanded_slide_moves_as_one_chunk(self):
        # Dragging either fragment step of chunk 1 moves the whole chunk.
        for i in (1, 2):
            self.assertEqual(reorder.plan_move(self.SLIDES, i, 0), ("slides.md", 1, 0))

    def test_dropping_onto_a_sibling_step_is_a_no_op(self):
        src, a, b = reorder.plan_move(self.SLIDES, 1, 2)
        self.assertEqual((a, b), (1, 1))
        text = "# One\n---\n# Two\n---\n# Three\n"
        self.assertEqual(reorder.move_chunk(text, a, b), text)

    def test_rejects_a_move_across_files(self):
        slides = [_slide(0, 0), _slide(1, 0, src="includes/sub/slides.md")]
        with self.assertRaises(ValueError) as cm:
            reorder.plan_move(slides, 0, 1)
        self.assertIn("different files", str(cm.exception))

    def test_allows_a_move_inside_an_included_deck(self):
        slides = [_slide(0, 0),
                  _slide(1, 0, src="includes/sub/slides.md"),
                  _slide(2, 1, src="includes/sub/slides.md")]
        self.assertEqual(reorder.plan_move(slides, 2, 1),
                         ("includes/sub/slides.md", 1, 0))

    def test_rejects_a_deck_without_provenance(self):
        slides = [{"index": 0, "src": "slides.md"}, {"index": 1, "src": "slides.md"}]
        with self.assertRaises(ValueError) as cm:
            reorder.plan_move(slides, 0, 1)
        self.assertIn("src_index", str(cm.exception))

    def test_out_of_range_slide_raises(self):
        for frm, to in ((4, 0), (0, 4), (-1, 0)):
            with self.subTest(frm=frm, to=to):
                with self.assertRaises(IndexError):
                    reorder.plan_move(self.SLIDES, frm, to)

    def test_move_slide_text_end_to_end(self):
        text = "# One\n---\n# Two\n---\n# Three\n"
        out = reorder.move_slide_text(text, self.SLIDES, 3, 0)
        self.assertEqual([s["title"] for s in md.parse_markdown(out)],
                         ["Three", "One", "Two"])


class RunTool(unittest.TestCase):
    """The chunk-range CLI form the deck view uses for sections and sub-decks."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.out = os.path.join(self.deck, "out")
        os.makedirs(self.out)
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write("# One\n---\n# Two\n---\n# Three\n---\n# Four\n")
        doc = {"version": 1, "deck": "d", "deck_dir": "..", "width": 1600, "height": 900,
               "slides": [_slide(i, i, title=t) for i, t in
                          enumerate(["One", "Two", "Three", "Four"])]}
        with open(os.path.join(self.out, "deck.json"), "w") as f:
            json.dump(doc, f)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL, self.out, *args],
                              capture_output=True, text=True)

    def titles(self):
        with open(self.md) as f:
            return [s.get("title") for s in md.parse_markdown(f.read())]

    def test_moves_a_block_range(self):
        p = self.run_tool("--file", "slides.md", "--chunks", "0", "1", "--to-chunk", "2",
                          "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        res = json.loads(p.stdout)
        self.assertTrue(res["ok"] and res["changed"])
        self.assertEqual(res["chunks"], [0, 1])
        self.assertEqual(res["dst"], 2)
        self.assertEqual(self.titles(), ["Three", "Four", "One", "Two"])

    def test_a_no_op_range_move(self):
        p = self.run_tool("--file", "slides.md", "--chunks", "1", "2", "--to-chunk", "1",
                          "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)["changed"])
        self.assertEqual(self.titles(), ["One", "Two", "Three", "Four"])

    def test_out_of_range_fails_cleanly(self):
        p = self.run_tool("--file", "slides.md", "--chunks", "0", "9", "--to-chunk", "0",
                          "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("out of date", json.loads(p.stdout)["error"])
        self.assertEqual(self.titles(), ["One", "Two", "Three", "Four"])

    def test_a_missing_file_fails_cleanly(self):
        p = self.run_tool("--file", "gone.md", "--chunks", "0", "1", "--to-chunk", "2",
                          "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("cannot find", json.loads(p.stdout)["error"])

    def test_chunks_needs_its_companions(self):
        p = self.run_tool("--file", "slides.md", "--chunks", "0", "1", "--no-rebuild")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--to-chunk", p.stderr)

    def test_one_form_or_the_other_is_required(self):
        p = self.run_tool("--no-rebuild")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--move", p.stderr)

    def test_the_slide_form_still_works(self):
        p = self.run_tool("--move", "3", "--to", "0", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.titles(), ["Four", "One", "Two", "Three"])


class Provenance(unittest.TestCase):
    """`src_index` / `src` are what make the mapping back to markdown possible at all."""

    def test_parse_markdown_counts_empty_chunks(self):
        slides = md.parse_markdown("---\n# A\n---\n---\n# B\n")
        self.assertEqual([s["src_index"] for s in slides], [1, 3])

    def test_load_deck_records_the_source_file(self):
        from refractkit.deck import load_deck
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "slides.md"), "w") as f:
            f.write("# A\n---\n# B\n")
        slides = load_deck(d, {os.path.abspath(d)})
        for s in slides:
            self.assertEqual(s["src_file"], os.path.join(os.path.abspath(d), "slides.md"))
        self.assertEqual([s["src_index"] for s in slides], [0, 1])

    def test_included_slides_record_the_include_that_pulled_them_in(self):
        from refractkit.deck import load_deck
        d = tempfile.mkdtemp()
        sub = os.path.join(d, "includes", "sub")
        os.makedirs(sub)
        with open(os.path.join(d, "slides.md"), "w") as f:
            f.write("# A\n---\n:: include : sub\n---\n# C\n")
        with open(os.path.join(sub, "slides.md"), "w") as f:
            f.write("# S1\n---\n# S2\n")
        slides = load_deck(d, {os.path.abspath(d)})
        # The parent's own slides came straight from its markdown.
        self.assertIsNone(slides[0].get("src_via"))
        self.assertIsNone(slides[3].get("src_via"))
        # The spliced-in ones remember the `:: include` line, which is chunk 1 of the parent —
        # the block that moves the whole sub-deck.
        for s in slides[1:3]:
            self.assertEqual([v["src_index"] for v in s["src_via"]], [1])
            self.assertEqual([os.path.basename(os.path.dirname(v["src"])) for v in s["src_via"]],
                             [os.path.basename(d)])

    def test_a_nested_include_records_the_whole_chain(self):
        from refractkit.deck import load_deck
        d = tempfile.mkdtemp()
        mid = os.path.join(d, "includes", "mid")
        inner = os.path.join(mid, "includes", "inner")
        os.makedirs(inner)
        with open(os.path.join(d, "slides.md"), "w") as f:
            f.write("# A\n---\n:: include : mid\n")
        with open(os.path.join(mid, "slides.md"), "w") as f:
            f.write("# M\n---\n:: include : inner\n")
        with open(os.path.join(inner, "slides.md"), "w") as f:
            f.write("# I\n")
        slides = load_deck(d, {os.path.abspath(d)})
        self.assertEqual([s["title"] for s in slides], ["A", "M", "I"])
        # Outermost first: the parent's include line, then the middle deck's.
        self.assertEqual([v["src_index"] for v in slides[2]["src_via"]], [1, 1])
        self.assertEqual([os.path.basename(os.path.dirname(v["src"]))
                          for v in slides[2]["src_via"]],
                         [os.path.basename(d), "mid"])

    def test_included_slides_point_at_the_sub_deck(self):
        from refractkit.deck import load_deck
        d = tempfile.mkdtemp()
        sub = os.path.join(d, "includes", "sub")
        os.makedirs(sub)
        with open(os.path.join(d, "slides.md"), "w") as f:
            f.write("# A\n---\n:: include : sub\n---\n# C\n")
        with open(os.path.join(sub, "slides.md"), "w") as f:
            f.write("# S1\n---\n# S2\n")
        slides = load_deck(d, {os.path.abspath(d)})
        self.assertEqual([s["title"] for s in slides], ["A", "S1", "S2", "C"])
        self.assertEqual([os.path.basename(os.path.dirname(s["src_file"])) for s in slides],
                         [os.path.basename(d), "sub", "sub", os.path.basename(d)])
        # Within each file the chunk indices are that file's own.
        self.assertEqual([s["src_index"] for s in slides], [0, 0, 1, 2])

    def test_a_synthesized_outline_keeps_its_source(self):
        import refract
        slides = [{"meta": {"type": "section"}, "title": "Part", "blocks": [],
                   "src_file": "/deck/slides.md", "src_index": 0},
                  {"meta": {"type": "outline", "params": ""}, "title": None, "blocks": [],
                   "src_file": "/deck/slides.md", "src_index": 1}]
        out = refract.apply_agenda(slides)
        self.assertEqual(out[1]["src_index"], 1)
        self.assertEqual(out[1]["src_file"], "/deck/slides.md")


class Tool(unittest.TestCase):
    """The CLI the player actually shells out to."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.out = os.path.join(self.deck, "out")
        os.makedirs(self.out)
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write("# One\n---\n# Two\n---\n# Three\n")
        self.write_deck([_slide(0, 0, title="One"),
                         _slide(1, 1, title="Two"),
                         _slide(2, 2, title="Three")])

    def write_deck(self, slides, **extra):
        doc = {"version": 1, "deck": os.path.basename(self.deck), "deck_dir": "..",
               "width": 1600, "height": 900, "slides": slides}
        doc.update(extra)
        with open(os.path.join(self.out, "deck.json"), "w") as f:
            json.dump(doc, f)

    def run_tool(self, *args):
        p = subprocess.run([sys.executable, TOOL, self.out, *args],
                           capture_output=True, text=True)
        return p

    def titles(self):
        with open(self.md) as f:
            return [s.get("title") for s in md.parse_markdown(f.read())]

    def test_moves_and_reports_json(self):
        p = self.run_tool("--move", "2", "--to", "0", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        res = json.loads(p.stdout)
        self.assertTrue(res["ok"])
        self.assertTrue(res["changed"])
        self.assertFalse(res["rebuilt"])
        self.assertEqual((res["from_chunk"], res["to_chunk"]), (2, 0))
        self.assertEqual(self.titles(), ["Three", "One", "Two"])

    def test_dry_run_writes_nothing(self):
        p = self.run_tool("--move", "0", "--to", "2", "--dry-run", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["changed"])
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_no_op_move_is_reported_as_unchanged(self):
        p = self.run_tool("--move", "1", "--to", "1", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)["changed"])
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_out_of_range_fails_without_touching_the_file(self):
        p = self.run_tool("--move", "9", "--to", "0", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["ok"])
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_stale_deck_json_pointing_past_the_markdown_fails_cleanly(self):
        self.write_deck([_slide(0, 0), _slide(1, 7)])
        p = self.run_tool("--move", "1", "--to", "0", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("out of date", json.loads(p.stdout)["error"])
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_missing_markdown_fails_cleanly(self):
        self.write_deck([_slide(0, 0, src="gone.md"), _slide(1, 1, src="gone.md")])
        p = self.run_tool("--move", "1", "--to", "0", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("cannot find", json.loads(p.stdout)["error"])

    def test_cross_file_move_is_refused(self):
        self.write_deck([_slide(0, 0), _slide(1, 0, src="includes/sub/slides.md")])
        p = self.run_tool("--move", "0", "--to", "1", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("different files", json.loads(p.stdout)["error"])

    def test_missing_deck_json(self):
        os.remove(os.path.join(self.out, "deck.json"))
        p = self.run_tool("--move", "0", "--to", "1", "--no-rebuild")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no deck.json", p.stderr)

    def test_repeated_moves_compose(self):
        self.run_tool("--move", "2", "--to", "0", "--no-rebuild")   # Three One Two
        self.write_deck([_slide(0, 0, title="Three"), _slide(1, 1, title="One"),
                         _slide(2, 2, title="Two")])
        self.run_tool("--move", "0", "--to", "2", "--no-rebuild")   # One Two Three
        self.assertEqual(self.titles(), ["One", "Two", "Three"])

    def test_writes_atomically_leaving_no_temp_file(self):
        self.run_tool("--move", "0", "--to", "1", "--no-rebuild")
        self.assertEqual([f for f in os.listdir(self.deck) if f.endswith(".tmp")], [])


class BuildArgs(unittest.TestCase):
    """The rebuild has to repeat the build, not just run one."""

    def build_args(self, deck):
        import importlib.util
        spec = importlib.util.spec_from_file_location("reorder_tool", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build_args(deck)

    def test_no_build_record_means_no_flags(self):
        self.assertEqual(self.build_args({}), [])

    def test_transitions_are_replayed(self):
        # The one that matters: `--transitions` is a command-line flag with nothing in the
        # deck to say it was given, so a rebuild that forgot it would silently strip every
        # transition out of the deck the first time a slide moved.
        self.assertIn("--transitions", self.build_args({"build": {"transitions": True}}))
        self.assertNotIn("--transitions", self.build_args({"build": {"transitions": False}}))

    def test_debug_is_replayed(self):
        self.assertIn("--debug", self.build_args({"build": {"debug": True}}))

    def test_the_slide_size_is_replayed(self):
        args = self.build_args({"width": 1920, "height": 1080})
        self.assertEqual(args, ["--width", "1920", "--height", "1080"])

    def test_a_bad_size_is_ignored_rather_than_passed_on(self):
        self.assertEqual(self.build_args({"width": "wide", "height": None}), [])


class EndToEnd(unittest.TestCase):
    """A real deck: build it, reorder it through the tool, rebuild, and read the order back.

    This is the only test that exercises the whole chain — provenance written by refract,
    read by the tool, used to rewrite the markdown, and reflected in a fresh build. Skipped
    where refract cannot build (no renderer on the machine), since the unit tests above
    already cover the reordering itself.
    """

    SLIDES = (
        "# One\n\nfirst slide\n"
        "---\n"
        ":: content steps\n# Two\n\n- alpha\n- beta\n- gamma\n"
        "???\nnotes for two\n"
        "---\n"
        "# Three\n\nthird slide\n"
        "---\n"
        "# Four\n\nfourth slide\n"
    )

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        with open(os.path.join(self.deck, "slides.md"), "w") as f:
            f.write(self.SLIDES)
        self.build()

    def build(self):
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest(f"refract could not build the deck: {p.stderr.strip()[-200:]}")

    def deck_json(self):
        with open(os.path.join(self.deck, "out", "deck.json")) as f:
            return json.load(f)

    def titles(self):
        return [s["title"] for s in self.deck_json()["slides"]]

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL, os.path.join(self.deck, "out"), *args],
                              capture_output=True, text=True)

    def test_provenance_is_written(self):
        doc = self.deck_json()
        self.assertEqual(doc["deck_dir"], "..")
        for rec in doc["slides"]:
            self.assertEqual(rec["src"], "slides.md")
            self.assertIsInstance(rec["src_index"], int)

    def test_a_stepped_slide_shares_one_source_block(self):
        # `steps` expands the three bullets into three slides, all from chunk 1.
        blocks = [s["src_index"] for s in self.deck_json()["slides"]]
        self.assertEqual(len(blocks), len(set(blocks)) + 2,
                         f"expected one block expanded into three slides, got {blocks}")

    def test_moving_a_slide_rebuilds_the_deck_in_the_new_order(self):
        before = self.titles()
        self.assertEqual(before[0], "One")
        last = len(before) - 1
        p = self.run_tool("--move", "0", "--to", str(last), "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        res = json.loads(p.stdout)
        self.assertTrue(res["ok"] and res["changed"] and res["rebuilt"], res)
        after = self.titles()
        self.assertEqual(after[-1], "One")
        self.assertEqual(sorted(after), sorted(before))

    def test_an_expanded_block_keeps_its_slides_together(self):
        titles = self.titles()
        two = titles.index("Two")
        p = self.run_tool("--move", str(two), "--to", str(len(titles) - 1), "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        after = self.titles()
        # All three steps travelled, and they are still consecutive and still last.
        self.assertEqual(after[-3:], ["Two", "Two", "Two"])
        doc = self.deck_json()
        tail = {s["src_index"] for s in doc["slides"][-3:]}
        self.assertEqual(len(tail), 1, "the three steps still share one source block")

    def test_the_rc_files_are_renumbered_to_match(self):
        self.run_tool("--move", "0", "--to", "1", "--json")
        doc = self.deck_json()
        out = os.path.join(self.deck, "out")
        for i, rec in enumerate(doc["slides"]):
            self.assertTrue(os.path.isfile(os.path.join(out, rec["file"])), rec["file"])
            self.assertTrue(rec["file"].startswith(f"{i + 1:02d}_"), rec["file"])
        # Nothing from the previous order was left behind for the player to pick up.
        listed = {rec["file"] for rec in doc["slides"]}
        on_disk = {f for f in os.listdir(out) if f.endswith(".rc")}
        self.assertEqual(on_disk, listed)

    def test_notes_survive_the_round_trip(self):
        self.run_tool("--move", "0", "--to", "3", "--json")
        doc = self.deck_json()
        noted = [s for s in doc["slides"] if s.get("notes")]
        self.assertTrue(noted, "the ??? note should still be on a slide")
        self.assertTrue(all(s["title"] == "Two" for s in noted))

    def test_moving_back_restores_the_original_deck(self):
        with open(os.path.join(self.deck, "slides.md")) as f:
            original = f.read()
        before = self.titles()
        last = len(before) - 1
        self.run_tool("--move", "0", "--to", str(last), "--json")
        # The first slide is now last; put it back by moving it to the front again.
        self.run_tool("--move", str(last), "--to", "0", "--json")
        with open(os.path.join(self.deck, "slides.md")) as f:
            self.assertEqual(f.read(), original)
        self.assertEqual(self.titles(), before)

    def test_the_rebuild_keeps_the_deck_transitions(self):
        # Built with transitions, reordered, still built with transitions.
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck,
                            "--transitions"], capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest("refract could not build the deck")
        self.assertTrue(self.deck_json()["build"]["transitions"])
        self.run_tool("--move", "0", "--to", "2", "--json")
        self.assertTrue(self.deck_json()["build"]["transitions"],
                        "the rebuild dropped --transitions")

    def test_no_rebuild_leaves_the_deck_stale(self):
        before = self.titles()
        p = self.run_tool("--move", "0", "--to", "1", "--no-rebuild", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)["rebuilt"])
        self.assertEqual(self.titles(), before, "deck.json is untouched without a rebuild")
        self.build()
        self.assertNotEqual(self.titles(), before, "and picks the change up on the next build")


if __name__ == "__main__":
    unittest.main()

"""`:: section duration=` — the talk's plan, from the markdown to deck.json.

The player does the arithmetic (see player/tests/plan_test.cpp); what is checked here is the
half that lives in refract: that a duration is written the way the rest of the player writes
one, that it reaches the manifest on the slides that carry the plan, and that it does *not*
quietly land on the ones that do not.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import refract
from refractkit import meta


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ParseDuration(unittest.TestCase):
    """The same grammar as the player's `--duration`, on purpose."""

    def test_units(self):
        self.assertEqual(meta.parse_duration("90s"), 90)
        self.assertEqual(meta.parse_duration("12m"), 720)
        self.assertEqual(meta.parse_duration("2h"), 7200)
        self.assertEqual(meta.parse_duration("1h30m"), 5400)
        self.assertEqual(meta.parse_duration("1h5m30s"), 3930)

    def test_a_bare_number_is_minutes(self):
        # It matches `--duration 45`, which a person reads as forty-five minutes.
        self.assertEqual(meta.parse_duration("45"), 45 * 60)
        self.assertEqual(meta.parse_duration(10), 600)

    def test_fractions(self):
        self.assertEqual(meta.parse_duration("1.5m"), 90)

    def test_case(self):
        self.assertEqual(meta.parse_duration("12M"), 720)
        self.assertEqual(meta.parse_duration("1H"), 3600)

    def test_nothing_is_no_plan(self):
        for bad in ("", "   ", "soon", None, [], "m"):
            with self.subTest(value=bad):
                self.assertEqual(meta.parse_duration(bad), 0)


class OnASlide(unittest.TestCase):
    def _slide(self, value=None, section=False):
        slide = {"meta": {"type": "section" if section else "content",
                          "overrides": {} if value is None else {"duration": value}}}
        if section:
            slide["section_number"] = 1
        return slide

    def test_read_off_the_meta_line(self):
        self.assertEqual(refract.meta_duration(self._slide("12m", section=True)), 720)

    def test_a_slide_that_says_nothing(self):
        self.assertEqual(refract.meta_duration(self._slide(section=True)), 0)

    def test_nonsense_is_no_plan_rather_than_an_error(self):
        self.assertEqual(refract.meta_duration(self._slide("later", section=True)), 0)


class InTheManifest(unittest.TestCase):
    """A built deck: the duration reaches the player, on the section slide and nowhere else."""

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        shutil.copytree(os.path.join(REPO, "examples", "deck"), self.deck,
                        dirs_exist_ok=True)

    def build(self, markdown):
        with open(os.path.join(self.deck, "slides.md"), "w") as f:
            f.write(markdown)
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck,
                            "--force"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        with open(os.path.join(self.deck, "out", "deck.json")) as f:
            return json.load(f), p.stderr

    def test_a_section_carries_its_duration(self):
        deck, _ = self.build("# Open\n\n---\n\n:: section duration=12m\n# Part One\n"
                             "\n---\n\n# A slide\n")
        durations = {s["index"]: s.get("duration") for s in deck["slides"]}
        section = next(s for s in deck["slides"] if s.get("section"))
        self.assertEqual(section["duration"], 720.0)
        # And only that slide: nothing else in the deck claims a length.
        self.assertEqual([i for i, d in durations.items() if d], [section["index"]])

    def test_two_sections_carry_their_own(self):
        deck, _ = self.build(":: section duration=5m\n# One\n\n---\n\n"
                             ":: section duration=25m\n# Two\n")
        planned = [s["duration"] for s in deck["slides"] if "duration" in s]
        self.assertEqual(planned, [300.0, 1500.0])

    def test_a_duration_on_an_ordinary_slide_is_reported_not_recorded(self):
        # Summed into nothing, so the build says so rather than letting it look like it
        # worked. This is the mistake the syntax invites.
        deck, errors = self.build("# Open\n\n---\n\n:: content duration=12m\n# A slide\n")
        self.assertTrue(all("duration" not in s for s in deck["slides"]))
        self.assertIn("starts no section", errors)

    def test_a_deck_with_no_plan_says_nothing(self):
        deck, errors = self.build("# Open\n\n---\n\n:: section\n# Part One\n")
        self.assertTrue(all("duration" not in s for s in deck["slides"]))
        self.assertNotIn("starts no section", errors)


if __name__ == "__main__":
    unittest.main()

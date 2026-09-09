"""The `::` line's vocabulary.

A list of words is only worth having if it is the same list the code acts on. These check the
parts that can be checked — that the layout types are refract's own, that nothing is listed
twice, and that every word could actually be written on a `::` line and survive the parser.
"""

import json
import os
import subprocess
import sys
import unittest

from refractkit import markdown, meta, render


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "player", "tools", "meta.py")


class Vocabulary(unittest.TestCase):
    def test_the_layout_types_are_the_ones_render_lays_out(self):
        listed = {name for name, _ in meta.types()}
        self.assertTrue(set(render.SLIDE_TYPES) <= listed,
                        "a layout type render knows about is missing from the vocabulary")

    def test_the_default_type_comes_first(self):
        # It is what a slide is when the `::` line says nothing, so it heads the list.
        self.assertEqual(meta.types()[0][0], render.DEFAULT_TYPE)

    def test_everything_is_documented(self):
        for name, doc in meta.types():
            self.assertTrue(doc, f"{name} has no line saying what it is for")
        for name, doc in meta.FLAGS:
            self.assertTrue(doc, f"{name} has no line saying what it is for")
        for name, doc, _ in meta.KEYS:
            self.assertTrue(doc, f"{name} has no line saying what it is for")

    def test_nothing_is_listed_twice(self):
        for label, names in [("types", [n for n, _ in meta.types()]),
                             ("flags", [n for n, _ in meta.FLAGS]),
                             ("keys", [n for n, _, _ in meta.KEYS])]:
            self.assertEqual(len(names), len(set(names)), f"a {label} entry is repeated")

    def test_a_word_that_is_both_a_flag_and_a_key_is_deliberate(self):
        # `skip`, `steps` and `freeze` are each written both ways — `:: content skip` and
        # `:: content skip=true` — and the parser treats them differently, so both lists
        # carry them on purpose.
        both = {n for n, _ in meta.FLAGS} & {n for n, _, _ in meta.KEYS}
        self.assertEqual(both, {"skip", "steps", "freeze"})


class ThroughTheParser(unittest.TestCase):
    """Every word survives being written on a `::` line — the thing a suggestion promises."""

    def test_every_type_parses_as_the_type(self):
        for name, _ in meta.types():
            with self.subTest(type=name):
                self.assertEqual(markdown.parse_meta(name)["type"], name)

    def test_every_flag_parses_as_a_flag(self):
        for name, _ in meta.FLAGS:
            with self.subTest(flag=name):
                self.assertIn(name, markdown.parse_meta("content " + name)["flags"])

    def test_every_key_parses_as_an_override(self):
        for name, _, values in meta.KEYS:
            value = values[0] if values else "1"
            with self.subTest(key=name):
                parsed = markdown.parse_meta(f"content {name}={value}")
                self.assertEqual(parsed["overrides"].get(name), value)


class IncludeOptions(unittest.TestCase):
    """`<name | key=value … flag>` — the options an embed can carry."""

    def test_every_option_parses_off_an_include_line(self):
        for name, _, values, _, takes in meta.INCLUDE_OPTS:
            if not takes:
                continue
            value = values[0] if values else "1"
            with self.subTest(option=name):
                block = markdown.parse_slide(f"<thing.mp4 | {name}={value}>")["blocks"][0]
                self.assertEqual(block["opts"].get(name), value)

    def test_a_bare_option_is_a_flag(self):
        block = markdown.parse_slide("<thing.mp4 | stagger>")["blocks"][0]
        self.assertIs(block["opts"].get("stagger"), True)

    def test_every_flag_parses_as_a_bare_word(self):
        # The editor inserts these without an `=`, so they have to work that way.
        for name, _, _, _, takes in meta.INCLUDE_OPTS:
            if takes:
                continue
            with self.subTest(flag=name):
                block = markdown.parse_slide(f"<thing.mp4 | {name}>")["blocks"][0]
                self.assertIs(block["opts"].get(name), True)

    def test_several_options_at_once(self):
        block = markdown.parse_slide('<a.mp4 | fit=fill title="Two Words" stagger>')["blocks"][0]
        self.assertEqual(block["opts"]["fit"], "fill")
        self.assertEqual(block["opts"]["title"], "Two Words")
        self.assertIs(block["opts"]["stagger"], True)

    def test_everything_is_documented_and_listed_once(self):
        names = [n for n, _, _, _, _ in meta.INCLUDE_OPTS]
        self.assertEqual(len(names), len(set(names)))
        for name, doc, _, kinds, _ in meta.INCLUDE_OPTS:
            self.assertTrue(doc, f"{name} has no line saying what it is for")
            self.assertTrue(kinds, f"{name} applies to nothing")

    def test_the_kinds_are_kinds_assets_actually_reports(self):
        # The editor filters by what `assets.scan` said a file is, so an option aimed at a
        # kind that scan never produces would silently never be offered.
        from refractkit import assets
        known = {name for name, _ in assets.KINDS} | {"other"}
        for name, _, _, kinds, _ in meta.INCLUDE_OPTS:
            for kind in kinds:
                self.assertIn(kind, known, f"{name} names a kind assets.scan never reports")

    def test_the_options_that_frame_an_embed_are_honoured_for_their_kinds(self):
        # crop/fit/ratio only do anything to a frameable block; the vocabulary says video and
        # document, and deck.py is what decides. These have to agree.
        from refractkit import deck
        for opt, value, field in [("crop", "0,0,0.5,0.5", "crop"), ("fit", "fill", "fit"),
                                  ("ratio", "16:9", "ratio")]:
            with self.subTest(option=opt):
                block = deck._apply_include_opts({"kind": "video"}, {opt: value})
                self.assertIn(field, block, f"{opt} is offered for video but ignored there")
                image = deck._apply_include_opts({"kind": "image"}, {opt: value})
                self.assertNotIn(field, image,
                                 f"{opt} is not offered for an image and does nothing there")

    def test_a_caption_works_on_an_image_too(self):
        from refractkit import deck
        block = deck._apply_include_opts({"kind": "image"}, {"title": "A caption"})
        self.assertEqual(block["caption"], "A caption")


class ThroughTheTool(unittest.TestCase):
    def test_list(self):
        p = subprocess.run([sys.executable, TOOL, "--list"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        doc = json.loads(p.stdout)
        self.assertTrue(doc["ok"])
        self.assertIn("content", [t["name"] for t in doc["types"]])
        self.assertIn("transition", [k["name"] for k in doc["keys"]])
        transition = next(k for k in doc["keys"] if k["name"] == "transition")
        self.assertIn("push", transition["values"])
        self.assertIn("crop", [o["name"] for o in doc["include_opts"]])
        fit = next(o for o in doc["include_opts"] if o["name"] == "fit")
        self.assertEqual(fit["values"], ["fit", "fill", "native"])
        self.assertIn("video", fit["kinds"])

    def test_it_needs_no_deck(self):
        # The grammar is refract's, not a deck's — the tool takes no directory at all.
        p = subprocess.run([sys.executable, TOOL, "--list"], capture_output=True, text=True,
                           cwd=os.path.dirname(REPO))
        self.assertEqual(p.returncode, 0)
        self.assertTrue(json.loads(p.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()

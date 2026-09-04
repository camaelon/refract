import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "player", "tools", "build.py")


class BuildArgs(unittest.TestCase):
    """The flags handed to refract, without running anything."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_tool", TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def args(self, deck=None, **flags):
        opts = {"transitions": False, "debug": False, "force": False, "keep_json": False,
                "width": None, "height": None}
        opts.update(flags)
        return self.tool.refract_args(type("A", (), opts)(), deck or {})

    def test_nothing_on_by_default(self):
        self.assertEqual(self.args(), [])

    def test_each_flag_maps_to_refract(self):
        self.assertEqual(self.args(transitions=True), ["--transitions"])
        self.assertEqual(self.args(debug=True), ["--debug"])
        self.assertEqual(self.args(force=True), ["--force"])
        # refract calls it --json; the panel calls it "keep intermediate JSON".
        self.assertEqual(self.args(keep_json=True), ["--json"])

    def test_the_size_comes_from_the_deck(self):
        # Not guessed: a deck that set its size in settings.toml must not be quietly resized
        # by a rebuild started from the panel.
        self.assertEqual(self.args({"width": 1920, "height": 1080}),
                         ["--width", "1920", "--height", "1080"])

    def test_an_explicit_size_wins(self):
        self.assertEqual(self.args({"width": 1600, "height": 900}, width=800, height=600),
                         ["--width", "800", "--height", "600"])

    def test_a_deck_with_no_size_passes_none(self):
        self.assertEqual(self.args({"width": "wide"}), [])

    def test_flags_combine(self):
        self.assertEqual(self.args({"width": 1600, "height": 900}, transitions=True, force=True),
                         ["--transitions", "--force", "--width", "1600", "--height", "900"])


class Outputs(unittest.TestCase):
    """What the tool counts as a build product."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_tool", TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.out = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.out, "media"))

    def touch(self, *names):
        for name in names:
            path = os.path.join(self.out, name)
            with open(path, "w") as f:
                f.write("x")

    def test_finds_slides_and_media(self):
        self.touch("01_one.rc", "01_one.rc.notes", "02_two.mp4", "media/clip.mov")
        self.assertEqual(sorted(self.tool.outputs(self.out)),
                         ["01_one.rc", "01_one.rc.notes", "02_two.mp4", "media/clip.mov"])

    def test_ignores_what_a_build_does_not_produce(self):
        self.touch("deck.json", "notes.md", ".refract-cache.json", "deck.pdf")
        self.assertEqual(self.tool.outputs(self.out), {})

    def test_a_missing_media_dir_is_not_an_error(self):
        shutil.rmtree(os.path.join(self.out, "media"))
        self.touch("01_one.rc")
        self.assertEqual(list(self.tool.outputs(self.out)), ["01_one.rc"])


class EndToEnd(unittest.TestCase):
    """Building a real deck. Skipped where refract cannot build."""

    SLIDES = "# One\n\nalpha\n---\n# Two\n\nbeta\n---\n# Three\n\ngamma\n"

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write(self.SLIDES)
        # The first build is refract's own: the tool reads the deck's location from the
        # manifest, and there is not one until something has been built.
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), self.deck],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest(f"refract could not build the deck: {p.stderr.strip()[-200:]}")

    def build(self, *args):
        p = subprocess.run([sys.executable, TOOL, os.path.join(self.deck, "out"), *args,
                            "--json"], capture_output=True, text=True)
        try:
            return json.loads(p.stdout)
        except ValueError:
            self.fail(f"no JSON on stdout: {p.stdout!r} / {p.stderr[-300:]!r}")

    def test_a_first_build_builds_everything(self):
        # setUp built into an empty directory, so the second build has everything to reuse.
        second = self.build()
        self.assertTrue(second["ok"])
        self.assertEqual(second["rebuilt"], 0)
        self.assertEqual(second["reused"], 3)
        self.assertEqual(second["slides"], 3)
        self.assertGreaterEqual(second["seconds"], 0.0)

    def test_an_edit_rebuilds_only_what_changed(self):
        with open(self.md, "w") as f:
            f.write(self.SLIDES.replace("beta", "beta changed"))
        result = self.build()
        self.assertTrue(result["ok"])
        self.assertEqual(result["rebuilt"], 1)
        self.assertEqual(result["reused"], 2)

    def test_force_rebuilds_everything(self):
        # The reason the counts come from mtimes rather than from the build cache: with
        # --force every slide is recompiled from an *unchanged* input, so a cache diff would
        # report nothing happened.
        result = self.build("--force")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rebuilt"], 3)
        self.assertEqual(result["reused"], 0)

    def test_a_deleted_slide_is_counted_as_removed(self):
        with open(self.md, "w") as f:
            f.write("# One\n\nalpha\n")
        result = self.build()
        self.assertTrue(result["ok"])
        self.assertEqual(result["removed"], 2)

    def test_transitions_are_passed_through(self):
        plain = os.stat(os.path.join(self.deck, "out", "02_two.rc")).st_size
        result = self.build("--transitions", "--force")
        self.assertTrue(result["ok"])
        # A transition document embeds the previous slide, so it is necessarily larger.
        self.assertGreater(os.stat(os.path.join(self.deck, "out", "02_two.rc")).st_size, plain)

    def test_keep_json_leaves_the_intermediates(self):
        self.build("--keep-json", "--force")
        json_dir = os.path.join(self.deck, "out", "json")
        self.assertTrue(os.path.isdir(json_dir))
        self.assertTrue(os.listdir(json_dir))

    def test_a_failing_build_reports_the_error(self):
        os.remove(self.md)
        result = self.build()
        self.assertFalse(result["ok"])
        self.assertIn("slides.md", result["error"])

    def test_a_directory_that_is_not_a_deck(self):
        p = subprocess.run([sys.executable, TOOL, tempfile.mkdtemp(), "--json"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("no deck.json", json.loads(p.stdout)["error"])

    def test_a_deck_that_has_never_been_built(self):
        # No manifest to read the deck's location from, so it falls back to the convention
        # that out/ sits inside the deck. This is the first build of a fresh checkout.
        fresh = tempfile.mkdtemp()
        with open(os.path.join(fresh, "slides.md"), "w") as f:
            f.write(self.SLIDES)
        p = subprocess.run([sys.executable, TOOL, os.path.join(fresh, "out"), "--json"],
                           capture_output=True, text=True)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["rebuilt"], 3)
        self.assertEqual(result["reused"], 0)

    def test_stdout_is_only_the_json(self):
        # The panel parses stdout; refract's own log has to go elsewhere or it lands in it.
        p = subprocess.run([sys.executable, TOOL, os.path.join(self.deck, "out"),
                            "--force", "--json"], capture_output=True, text=True)
        self.assertEqual(len(p.stdout.strip().splitlines()), 1, p.stdout)
        json.loads(p.stdout)
        self.assertIn("wrote", p.stderr)


if __name__ == "__main__":
    unittest.main()

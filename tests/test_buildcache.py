import json
import os
import subprocess
import sys
import tempfile
import unittest

from refractkit import buildcache as bc


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFRACT = os.path.join(REPO, "refract.py")
REORDER = os.path.join(REPO, "player", "tools", "reorder.py")


class ReferencedFiles(unittest.TestCase):
    """What a document points at that json2rc will inline — images, mostly."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.img = os.path.join(self.d, "logo.png")
        with open(self.img, "wb") as f:
            f.write(b"pixels")

    def test_finds_an_absolute_path(self):
        doc = {"root": [{"type": "image", "image": self.img}]}
        self.assertEqual(bc.referenced_files(doc), [self.img])

    def test_finds_paths_at_any_depth(self):
        doc = {"a": {"b": [{"c": [{"image": self.img}]}]}}
        self.assertEqual(bc.referenced_files(doc), [self.img])

    def test_ignores_paths_that_do_not_exist(self):
        self.assertEqual(bc.referenced_files({"image": "/no/such/file.png"}), [])

    def test_ignores_relative_paths(self):
        # media/ references are loaded at runtime, not inlined, and a relative string would
        # resolve against whatever directory refract happened to be run from.
        self.assertEqual(bc.referenced_files({"src": "media/clip.mp4"}), [])

    def test_ignores_non_path_strings(self):
        doc = {"agsl": "uniform float2 res;\nhalf4 main() {}", "value": "Hello / world"}
        self.assertEqual(bc.referenced_files(doc), [])

    def test_deduplicates_and_sorts(self):
        other = os.path.join(self.d, "a.png")
        with open(other, "wb") as f:
            f.write(b"x")
        doc = {"one": self.img, "two": self.img, "three": other}
        self.assertEqual(bc.referenced_files(doc), sorted([self.img, other]))


class DocFingerprint(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.img = os.path.join(self.d, "logo.png")
        with open(self.img, "wb") as f:
            f.write(b"pixels")

    def test_same_document_same_fingerprint(self):
        doc = {"root": [{"type": "text", "value": "hello"}]}
        self.assertEqual(bc.doc_fingerprint(doc), bc.doc_fingerprint(dict(doc)))

    def test_key_order_does_not_matter(self):
        a = {"width": 1600, "height": 900}
        b = {"height": 900, "width": 1600}
        self.assertEqual(bc.doc_fingerprint(a), bc.doc_fingerprint(b))

    def test_a_changed_value_changes_it(self):
        a = {"root": [{"value": "hello"}]}
        b = {"root": [{"value": "hello!"}]}
        self.assertNotEqual(bc.doc_fingerprint(a), bc.doc_fingerprint(b))

    def test_the_page_number_changes_it(self):
        # This is what makes a reorder rebuild every slide after the move: the chrome's page
        # number is in the document, so a slide that only changed position is not the same.
        a = {"chrome": {"page": 3, "total": 40}, "root": []}
        b = {"chrome": {"page": 4, "total": 40}, "root": []}
        self.assertNotEqual(bc.doc_fingerprint(a), bc.doc_fingerprint(b))

    def test_an_image_edit_changes_it(self):
        doc = {"image": self.img}
        before = bc.doc_fingerprint(doc)
        with open(self.img, "wb") as f:
            f.write(b"different pixels")
        self.assertNotEqual(bc.doc_fingerprint(doc), before)

    def test_touching_an_image_does_not(self):
        # Content, not mtime: a checkout or a `touch` must not rebuild the deck.
        doc = {"image": self.img}
        before = bc.doc_fingerprint(doc)
        os.utime(self.img, (1, 1))
        self.assertEqual(bc.doc_fingerprint(doc), before)

    def test_moving_an_image_changes_it(self):
        # The path is part of the input even when the bytes are not: json2rc is handed the
        # path, and a document naming a different file is a different document.
        other = os.path.join(self.d, "other.png")
        with open(other, "wb") as f:
            f.write(b"pixels")
        self.assertNotEqual(bc.doc_fingerprint({"image": self.img}),
                            bc.doc_fingerprint({"image": other}))


class CopyFingerprint(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.clip = os.path.join(self.d, "clip.mp4")
        with open(self.clip, "wb") as f:
            f.write(b"video")

    def test_stable_for_an_untouched_file(self):
        self.assertEqual(bc.copy_fingerprint(self.clip), bc.copy_fingerprint(self.clip))

    def test_changes_when_the_file_changes(self):
        before = bc.copy_fingerprint(self.clip)
        with open(self.clip, "wb") as f:
            f.write(b"different video")
        self.assertNotEqual(bc.copy_fingerprint(self.clip), before)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(bc.copy_fingerprint(os.path.join(self.d, "gone.mp4")), "")


class ToolStamp(unittest.TestCase):
    def test_missing_tool(self):
        self.assertEqual(bc.tool_stamp(None), "none")
        self.assertEqual(bc.tool_stamp("/no/such/json2rc"), "none")

    def test_names_the_tool(self):
        d = tempfile.mkdtemp()
        tool = os.path.join(d, "json2rc")
        with open(tool, "wb") as f:
            f.write(b"#!/bin/sh\n")
        self.assertIn("json2rc", bc.tool_stamp(tool))


class Cache(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.rc = os.path.join(self.out, "01_one.rc")
        with open(self.rc, "wb") as f:
            f.write(b"compiled")

    def cache(self, stamp="tool:1"):
        return bc.BuildCache(self.out, stamp)

    def test_nothing_is_fresh_without_a_cache(self):
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_a_recorded_output_is_fresh(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        self.assertTrue(self.cache().load().fresh(self.rc, "abc"))

    def test_a_different_fingerprint_is_not(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        self.assertFalse(self.cache().load().fresh(self.rc, "xyz"))

    def test_a_deleted_output_is_not_fresh(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        os.remove(self.rc)
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_a_new_compiler_drops_everything(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        self.assertFalse(self.cache("tool:2").load().fresh(self.rc, "abc"))

    def test_an_older_cache_format_is_ignored(self):
        with open(os.path.join(self.out, bc.CACHE_NAME), "w") as f:
            json.dump({"version": bc.CACHE_VERSION - 1, "stamp": "tool:1",
                       "outputs": {"01_one.rc": "abc"}}, f)
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_a_corrupt_cache_is_ignored(self):
        with open(os.path.join(self.out, bc.CACHE_NAME), "w") as f:
            f.write("{not json")
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_only_what_this_build_vouched_for_is_written(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        # A build that says nothing about the file forgets it — which is what happens when a
        # conversion fails, and is the safe direction.
        self.cache().load().save()
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_forget_removes_an_entry(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.forget(self.rc)
        c.save()
        self.assertFalse(self.cache().load().fresh(self.rc, "abc"))

    def test_paths_are_stored_relative_to_out(self):
        c = self.cache().load()
        c.keep(self.rc, "abc")
        c.save()
        with open(os.path.join(self.out, bc.CACHE_NAME)) as f:
            self.assertEqual(list(json.load(f)["outputs"]), ["01_one.rc"])

    def test_an_unwritable_cache_is_not_an_error(self):
        c = bc.BuildCache(os.path.join(self.out, "nope"), "tool:1")
        c.keep("x", "abc")
        c.save()          # must not raise


class Prune(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        for name in ("01_one.rc", "02_two.rc", "01_one.rc.notes", "notes.md", "clip.mp4"):
            with open(os.path.join(self.d, name), "w") as f:
                f.write("x")

    def paths(self, *names):
        return {os.path.abspath(os.path.join(self.d, n)) for n in names}

    def test_removes_unclaimed_generated_files(self):
        removed = bc.prune([(self.d, (".rc", ".notes", ".mp4"))], self.paths("01_one.rc"))
        self.assertEqual(sorted(os.path.basename(p) for p in removed),
                         ["01_one.rc.notes", "02_two.rc", "clip.mp4"])
        self.assertTrue(os.path.isfile(os.path.join(self.d, "01_one.rc")))

    def test_leaves_unmanaged_extensions_alone(self):
        # notes.md is refract's, but it is not in the managed list, and neither is anything a
        # user dropped into out/ by hand.
        bc.prune([(self.d, (".rc",))], set())
        self.assertTrue(os.path.isfile(os.path.join(self.d, "notes.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.d, "clip.mp4")))

    def test_keeps_everything_that_was_claimed(self):
        keep = self.paths("01_one.rc", "02_two.rc", "01_one.rc.notes", "clip.mp4")
        self.assertEqual(bc.prune([(self.d, (".rc", ".notes", ".mp4"))], keep), [])

    def test_a_missing_directory_is_not_an_error(self):
        self.assertEqual(bc.prune([(os.path.join(self.d, "gone"), (".rc",))], set()), [])


class IncrementalBuilds(unittest.TestCase):
    """The whole thing, against a real deck. Skipped where refract cannot build."""

    SLIDES = ("# One\n\nalpha\n"
              "---\n"
              "# Two\n\nbeta\n"
              "---\n"
              "# Three\n\ngamma\n"
              "---\n"
              "# Four\n\ndelta\n")

    def setUp(self):
        self.deck = tempfile.mkdtemp()
        self.md = os.path.join(self.deck, "slides.md")
        with open(self.md, "w") as f:
            f.write(self.SLIDES)
        self.build()

    def build(self, *args):
        p = subprocess.run([sys.executable, REFRACT, self.deck, *args],
                           capture_output=True, text=True)
        if p.returncode != 0:
            self.skipTest(f"refract could not build the deck: {p.stderr.strip()[-200:]}")
        return p.stdout

    def rc_files(self):
        out = os.path.join(self.deck, "out")
        return sorted(f for f in os.listdir(out) if f.endswith(".rc"))

    def contents(self):
        out = os.path.join(self.deck, "out")
        result = {}
        for name in self.rc_files():
            with open(os.path.join(out, name), "rb") as f:
                result[name] = f.read()
        return result

    def stamps(self):
        out = os.path.join(self.deck, "out")
        return {f: os.stat(os.path.join(out, f)).st_mtime_ns for f in self.rc_files()}

    def test_an_unchanged_deck_is_not_rebuilt(self):
        before = self.stamps()
        output = self.build()
        self.assertIn("reused 4 slides", output)
        self.assertEqual(self.stamps(), before, "no .rc was rewritten")

    def test_a_cache_file_is_written(self):
        self.assertTrue(os.path.isfile(os.path.join(self.deck, "out", bc.CACHE_NAME)))

    def test_only_the_edited_slide_is_rebuilt(self):
        before = self.stamps()
        with open(self.md, "w") as f:
            f.write(self.SLIDES.replace("gamma", "gamma changed"))
        self.build()
        after = self.stamps()
        changed = [f for f in after if after[f] != before.get(f)]
        self.assertEqual(changed, ["03_three.rc"])

    def test_a_deleted_output_comes_back(self):
        target = os.path.join(self.deck, "out", "02_two.rc")
        os.remove(target)
        self.build()
        self.assertTrue(os.path.isfile(target))

    def test_a_renamed_slide_does_not_leave_the_old_one_behind(self):
        with open(self.md, "w") as f:
            f.write(self.SLIDES.replace("# Two", "# Second"))
        self.build()
        self.assertNotIn("02_two.rc", self.rc_files())
        self.assertIn("02_second.rc", self.rc_files())

    def test_a_deleted_slide_is_swept(self):
        with open(self.md, "w") as f:
            f.write("# One\n\nalpha\n---\n# Two\n\nbeta\n")
        self.build()
        self.assertEqual(self.rc_files(), ["01_one.rc", "02_two.rc"])

    def test_an_incremental_build_matches_a_clean_one(self):
        # The property that matters: reusing an output must never produce a deck that differs
        # from one built from scratch.
        with open(self.md, "w") as f:
            f.write(self.SLIDES.replace("beta", "beta changed"))
        self.build()
        incremental = self.contents()
        import shutil
        shutil.rmtree(os.path.join(self.deck, "out"))
        self.build()
        self.assertEqual(incremental, self.contents())

    def test_transitions_rebuild_the_slide_that_follows_a_change(self):
        # With transitions on, a slide's document embeds the one before it — so editing a
        # slide has to rebuild its successor too. Nothing says so anywhere: it falls out of
        # fingerprinting the document rather than the markdown.
        self.build("--transitions")
        before = self.stamps()
        with open(self.md, "w") as f:
            f.write(self.SLIDES.replace("beta", "beta changed"))
        self.build("--transitions")
        after = self.stamps()
        changed = sorted(f for f in after if after[f] != before.get(f))
        self.assertEqual(changed, ["02_two.rc", "03_three.rc"])

    def test_reordering_rebuilds_the_slides_that_moved(self):
        # The case the cache must not get clever about: the slides' *content* is untouched by
        # a reorder, but their page numbers and progress bars are not.
        before = self.stamps()
        p = subprocess.run([sys.executable, REORDER, os.path.join(self.deck, "out"),
                            "--move", "0", "--to", "3", "--json"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

        with open(os.path.join(self.deck, "out", "deck.json")) as f:
            self.assertEqual([s["title"] for s in json.load(f)["slides"]],
                             ["Two", "Three", "Four", "One"])
        after = self.stamps()
        self.assertEqual(len(after), 4)
        # Every slide is written at a new position, so every one of them is a new file — and
        # any name that does happen to survive was still rebuilt, never reused.
        untouched = [f for f in after if after[f] == before.get(f)]
        self.assertEqual(untouched, [], "nothing was reused across the reorder")

    def test_force_ignores_the_cache(self):
        before = self.stamps()
        output = self.build("--force")
        self.assertNotIn("reused", output)
        after = self.stamps()
        self.assertEqual(sorted(after), sorted(before))
        self.assertTrue(all(after[f] != before[f] for f in after), "every slide rewritten")

    def test_a_new_compiler_rebuilds_everything(self):
        cache_path = os.path.join(self.deck, "out", bc.CACHE_NAME)
        with open(cache_path) as f:
            doc = json.load(f)
        doc["stamp"] = "json2rc:different"
        with open(cache_path, "w") as f:
            json.dump(doc, f)
        output = self.build()
        self.assertNotIn("reused", output)


class DeterministicOutput(unittest.TestCase):
    """Two builds of the same deck must produce the same bytes.

    Not a nicety: a slide whose document differs between runs can never be reused, and the
    order commands are emitted in is the order they are drawn in — a graph whose nodes came
    out in a different order each build was also drawing them in a different z-order.
    """

    GRAPH = ("# Flow\n"
             "```dot\n"
             "digraph G {\n"
             "  rankdir=LR\n"
             "  Client -> API\n"
             "  API -> Cache\n"
             "  API -> DB\n"
             "  DB -> Archive\n"
             "}\n"
             "```\n"
             "---\n"
             ":: same\n"
             "# Flow\n"
             "```dot\n"
             "digraph G {\n"
             "  rankdir=LR\n"
             "  Client -> API\n"
             "  API -> Cache\n"
             "  API -> Queue\n"
             "  Queue -> DB\n"
             "}\n"
             "```\n")

    def build_twice(self, *args):
        deck = tempfile.mkdtemp()
        with open(os.path.join(deck, "slides.md"), "w") as f:
            f.write(self.GRAPH)
        shots = []
        import shutil
        for _ in range(2):
            p = subprocess.run([sys.executable, REFRACT, deck, *args],
                               capture_output=True, text=True)
            if p.returncode != 0:
                self.skipTest(f"refract could not build: {p.stderr.strip()[-200:]}")
            out = os.path.join(deck, "out")
            shot = {}
            for name in sorted(os.listdir(out)):
                if name.endswith(".rc"):
                    with open(os.path.join(out, name), "rb") as f:
                        shot[name] = f.read()
            shots.append(shot)
            shutil.rmtree(out)
        return shots

    def test_a_graph_morph_builds_the_same_bytes_every_time(self):
        first, second = self.build_twice("--transitions")
        self.assertEqual(sorted(first), sorted(second))
        self.assertEqual(first, second)

    def test_a_graph_morph_is_reusable(self):
        # The consequence: with a stable document, even the magic-move slide is cached.
        deck = tempfile.mkdtemp()
        with open(os.path.join(deck, "slides.md"), "w") as f:
            f.write(self.GRAPH)
        for args in ([], ["--transitions"]):
            p = subprocess.run([sys.executable, REFRACT, deck, *args],
                               capture_output=True, text=True)
            if p.returncode != 0:
                self.skipTest(f"refract could not build: {p.stderr.strip()[-200:]}")
        again = subprocess.run([sys.executable, REFRACT, deck, "--transitions"],
                               capture_output=True, text=True)
        self.assertIn("reused 2 slides", again.stdout)


if __name__ == "__main__":
    unittest.main()

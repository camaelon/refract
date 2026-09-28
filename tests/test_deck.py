import os
import struct
import tempfile
import unittest

from refractkit import deck


def _png(path, w=10, h=20):
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h))


class ResolveInclude(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_image(self):
        _png(os.path.join(self.d, "a.png"))
        b = deck.resolve_include("a.png", self.d)
        self.assertEqual(b["kind"], "image")
        self.assertTrue(b["path"].endswith("a.png"))

    def test_extension_probing(self):
        _png(os.path.join(self.d, "logo.png"))
        b = deck.resolve_include("logo", self.d)   # no extension
        self.assertEqual(b["kind"], "image")

    def test_rc_with_sibling_json(self):
        open(os.path.join(self.d, "w.rc"), "wb").close()
        open(os.path.join(self.d, "w.json"), "w").close()
        b = deck.resolve_include("w.rc", self.d)
        self.assertEqual(b["kind"], "rc_include")
        self.assertTrue(b["json"].endswith("w.json"))

    def test_rc_without_sibling_json(self):
        open(os.path.join(self.d, "w.rc"), "wb").close()
        b = deck.resolve_include("w.rc", self.d)
        self.assertEqual(b["kind"], "rc_include")
        self.assertIsNone(b["json"])

    def test_json(self):
        open(os.path.join(self.d, "c.json"), "w").close()
        b = deck.resolve_include("c.json", self.d)
        self.assertEqual(b["kind"], "json_include")

    def test_missing(self):
        b = deck.resolve_include("nope", self.d)
        self.assertEqual(b["kind"], "missing")
        self.assertEqual(b["name"], "nope")


class ResolveBlocks(unittest.TestCase):
    def test_replaces_include(self):
        d = tempfile.mkdtemp()
        inc = os.path.join(d, "includes")
        os.makedirs(inc)
        _png(os.path.join(inc, "p.png"))
        slide = {"base_dir": d, "blocks": [
            {"kind": "include", "name": "p.png"},
            {"kind": "text", "text": "keep"},
        ]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["kind"], "image")
        self.assertEqual(out[1]["kind"], "text")

    def test_camera_is_an_include_without_a_file(self):
        d = tempfile.mkdtemp()
        b = deck.resolve_include("camera", d)
        self.assertEqual(b["kind"], "camera")
        self.assertEqual(b["device"], "")
        b = deck.resolve_include("camera:FaceTime", d)
        self.assertEqual(b["device"], "FaceTime")

    def test_camera_opts(self):
        slide = {"base_dir": tempfile.mkdtemp(), "blocks": [
            {"kind": "include", "name": "camera",
             "opts": {"ratio": "1:1", "clip": "circle", "mirror": True, "device": "1",
                      "crop": "0.1,0,0.9,1"}},
        ]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["kind"], "camera")
        self.assertEqual(out[0]["ratio"], 1.0)
        self.assertEqual(out[0]["clip"], "circle")
        self.assertTrue(out[0]["mirror"])
        self.assertEqual(out[0]["device"], "1")
        self.assertEqual(out[0]["crop"], [0.1, 0.0, 0.9, 1.0])

    def test_zoom_is_a_centred_crop(self):
        self.assertEqual(deck.zoom_crop(2), [0.25, 0.25, 0.75, 0.75])
        self.assertEqual(deck.zoom_crop(2, (0.0, 0.5)), [0.0, 0.25, 0.5, 0.75], "a focus at the edge stays inside")
        self.assertEqual(deck.zoom_crop(1), None, "no zoom is no crop")
        self.assertEqual(deck.zoom_crop(2, None, [0.0, 0.0, 0.5, 1.0]), [0.125, 0.25, 0.375, 0.75],
                         "a zoom inside a crop")
        slide = {"base_dir": tempfile.mkdtemp(), "blocks": [
            {"kind": "include", "name": "camera",
             "opts": {"zoom": "1.6", "focus": "0.5,0.4", "width": "190.66", "height": "190.66"}}]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["crop"], [0.1875, 0.0875, 0.8125, 0.7125])
        self.assertEqual((out[0]["width"], out[0]["height"]), (190.66, 190.66))

    def test_clip_applies_to_video_too(self):
        d = tempfile.mkdtemp()
        inc = os.path.join(d, "includes")
        os.makedirs(inc)
        open(os.path.join(inc, "v.mp4"), "wb").close()
        slide = {"base_dir": d, "blocks": [
            {"kind": "include", "name": "v.mp4", "opts": {"clip": "24"}}]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["clip"], "24")

    def test_include_opts_apply_crop_and_fit(self):
        d = tempfile.mkdtemp()
        inc = os.path.join(d, "includes")
        os.makedirs(inc)
        open(os.path.join(inc, "v.mp4"), "wb").close()
        slide = {"base_dir": d, "blocks": [
            {"kind": "include", "name": "v.mp4",
             "opts": {"crop": "0.28,0,0.72,1", "fit": "fill"}},
        ]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["kind"], "video")
        self.assertEqual(out[0]["crop"], [0.28, 0.0, 0.72, 1.0])
        self.assertEqual(out[0]["fit"], "fill")

    def test_include_title_becomes_caption(self):
        d = tempfile.mkdtemp()
        inc = os.path.join(d, "includes")
        os.makedirs(inc)
        open(os.path.join(inc, "v.mp4"), "wb").close()
        slide = {"base_dir": d, "blocks": [
            {"kind": "include", "name": "v.mp4", "opts": {"title": "My Clip"}},
        ]}
        out = deck.resolve_blocks(slide)
        self.assertEqual(out[0]["caption"], "My Clip")


class ParseCrop(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(deck.parse_crop("0.28,0,0.72,1"), [0.28, 0.0, 0.72, 1.0])

    def test_clamped_to_unit_square(self):
        self.assertEqual(deck.parse_crop("-0.1,0,2,1"), [0.0, 0.0, 1.0, 1.0])

    def test_rejects_bad_shapes(self):
        self.assertIsNone(deck.parse_crop(""))
        self.assertIsNone(deck.parse_crop("0,0,1"))          # only 3 numbers
        self.assertIsNone(deck.parse_crop("0.5,0,0.5,1"))    # zero width
        self.assertIsNone(deck.parse_crop("a,b,c,d"))        # non-numeric


class LoadDeck(unittest.TestCase):
    def _deck(self, text):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "slides.md"), "w") as f:
            f.write(text)
        return d

    def test_basic(self):
        d = self._deck("# A\n---\n# B")
        slides = deck.load_deck(d, {os.path.abspath(d)})
        self.assertEqual(len(slides), 2)
        self.assertTrue(all("base_dir" in s for s in slides))

    def test_missing_slides_md(self):
        with self.assertRaises(FileNotFoundError):
            deck.load_deck(tempfile.mkdtemp(), set())

    def test_deck_include_expands(self):
        d = self._deck(":: include : sub\n---\n# Master")
        sub = os.path.join(d, "includes", "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "slides.md"), "w") as f:
            f.write("# Sub1\n---\n# Sub2")
        slides = deck.load_deck(d, {os.path.abspath(d)})
        titles = [s.get("title") for s in slides]
        self.assertIn("Sub1", titles)
        self.assertIn("Sub2", titles)
        self.assertIn("Master", titles)

    def test_deck_include_missing_placeholder(self):
        d = self._deck(":: include : ghost")
        slides = deck.load_deck(d, {os.path.abspath(d)})
        self.assertEqual(len(slides), 1)
        self.assertIn("ghost", slides[0]["blocks"][0]["text"])

    def test_include_author_propagates(self):
        # ``:: include : sub @Nico`` attributes every included slide to Nico,
        # unless a slide names its own author.
        d = self._deck(":: include : sub @Nico")
        sub = os.path.join(d, "includes", "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "slides.md"), "w") as f:
            f.write("# Sub1\n---\n:: @John\n# Sub2")
        slides = deck.load_deck(d, {os.path.abspath(d)})
        by_title = {s.get("title"): (s.get("meta") or {}).get("author") for s in slides}
        self.assertEqual(by_title["Sub1"], "Nico")     # inherited from the include
        self.assertEqual(by_title["Sub2"], "John")     # own attribution wins


if __name__ == "__main__":
    unittest.main()

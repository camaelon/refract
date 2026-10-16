"""Video ``start=`` / ``still=`` options and the ``cue`` slide expansion."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import refract  # noqa: E402
from refractkit.deck import parse_clip_time, _apply_include_opts  # noqa: E402
from refractkit.render import render_video  # noqa: E402


class ClipTime(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_clip_time("12"), 12.0)
        self.assertEqual(parse_clip_time("12.5"), 12.5)
        self.assertEqual(parse_clip_time("1:23"), 83.0)
        self.assertEqual(parse_clip_time("1:02:03.5"), 3723.5)
        self.assertIsNone(parse_clip_time(None))
        self.assertIsNone(parse_clip_time(True))
        self.assertIsNone(parse_clip_time("soon"))

    def test_options_reach_the_block(self):
        b = _apply_include_opts({"kind": "video", "path": "/x/demo.mp4"}, {"start": "0:12", "still": "3"})
        self.assertEqual((b["start"], b["still"]), (12.0, 3.0))
        b = _apply_include_opts({"kind": "image", "path": "/x/a.png"}, {"start": "12"})
        self.assertNotIn("start", b)


class LoopAndZoom(unittest.TestCase):
    def test_once_and_loop(self):
        b = _apply_include_opts({"kind": "video", "path": "/x/d.mp4"}, {"once": True})
        self.assertIs(b["loop"], False)
        b = _apply_include_opts({"kind": "video", "path": "/x/d.mp4"}, {"loop": "0"})
        self.assertIs(b["loop"], False)
        b = _apply_include_opts({"kind": "video", "path": "/x/d.mp4"}, {})
        self.assertNotIn("loop", b)

    def test_zoom_keys(self):
        from refractkit.deck import parse_zooms
        self.assertEqual(parse_zooms("0:04@0.7,0.5,3; 1@0.3,0.4,2;bad;9@0.5,0.5"),
                         [(1.0, 0.3, 0.4, 2.0), (4.0, 0.7, 0.5, 3.0), (9.0, 0.5, 0.5, 1.0)])
        self.assertIsNone(parse_zooms(None))
        self.assertEqual(parse_zooms("2@1.5,-1,0.5"), [(2.0, 1.0, 0.0, 1.0)])   # clamped, z >= 1

    def test_config(self):
        from refractkit.theme import Theme
        b = _apply_include_opts({"kind": "video", "path": "/x/d.mp4", "src": "media/d.mp4"},
                                {"once": True, "zooms": "1@0.3,0.4,2; 0:04@0.7,0.5,3"})
        cfg = str(render_video(b, Theme(), False, 800, 450))
        self.assertIn("loop=0", cfg)
        self.assertIn("zooms=1@0.3,0.4,2;4@0.7,0.5,3", cfg)


class Cue(unittest.TestCase):
    def _slide(self, opts):
        return {"title": "Demo", "meta": {}, "blocks": [
            {"kind": "text", "text": "hello"}, {"kind": "include", "name": "demo.mp4", "opts": opts}]}

    def test_no_cue_is_untouched(self):
        s = self._slide({"start": "12"})
        self.assertEqual(refract.expand_video_cue([s]), [s])

    def test_cue_makes_a_still_then_the_playing_slide(self):
        still, play = refract.expand_video_cue([self._slide({"start": "12", "cue": True})])
        self.assertEqual(still["blocks"][1]["opts"], {"still": "12"})
        self.assertNotIn("stagger_step", still["meta"])
        self.assertEqual(play["blocks"][1]["opts"], {"start": "12"})
        self.assertTrue(play["meta"]["stagger_step"])
        self.assertEqual(still["blocks"][0], play["blocks"][0])

    def test_cue_time_and_default(self):
        still, _ = refract.expand_video_cue([self._slide({"cue": "0:05"})])
        self.assertEqual(still["blocks"][1]["opts"]["still"], "5")
        still, _ = refract.expand_video_cue([self._slide({"cue": True})])
        self.assertEqual(still["blocks"][1]["opts"]["still"], "0")
        self.assertEqual(len(refract.expand_video_cue([self._slide({"cue": "off"})])), 1)

    def test_config_carries_start_and_still(self):
        from refractkit.theme import Theme
        cfg = render_video({"kind": "video", "path": "/x/demo.mp4", "src": "media/demo.mp4", "start": 12.0},
                           Theme(), False, 800, 450)
        self.assertIn("video:media/demo.mp4#start=12", str(cfg))
        cfg = render_video({"kind": "video", "path": "/x/demo.mp4", "src": "media/demo.mp4", "still": 0.0},
                           Theme(), False, 800, 450)
        self.assertIn("still=0", str(cfg))


class Walk(unittest.TestCase):
    def _s(self, opts, title="Demo"):
        return {"title": title, "meta": {}, "blocks": [{"kind": "include", "name": "demo.mov", "opts": opts}]}

    def _opts(self, slides):
        return [s["blocks"][0]["opts"] for s in slides]

    def test_steps_expand_then_chain(self):
        slides = refract.resolve_video_chains(refract.expand_video_steps(
            [self._s({"start": "2", "zooms": "5@0.7,0.3,2.5; 0:12@0.2,0.6,3", "steps": True})]))
        self.assertEqual(len(slides), 3)
        o = self._opts(slides)
        self.assertEqual(o[0], {"start": "2", "until": "5"})
        self.assertEqual(o[1], {"start": "5", "until": "12", "zooms": "4@0.5,0.5,1;5@0.7,0.3,2.5"})
        self.assertEqual(o[2], {"start": "12", "zooms": "11@0.7,0.3,2.5;12@0.2,0.6,3"})
        self.assertNotIn("stagger_step", slides[0]["meta"])
        self.assertTrue(slides[1]["meta"]["stagger_step"] and slides[2]["meta"]["stagger_step"])

    def test_explicit_slides_chain(self):
        slides = refract.resolve_video_chains([
            self._s({"zoom": "0:05@0.7,0.3,2.5"}, "a"), self._s({"zoom": "0:12@0.2,0.6,3"}, "b"),
            self._s({"zoom": "20@0.5,0.5,1", "once": True}, "c")])
        o = self._opts(slides)
        self.assertEqual(o[0], {"start": "5", "until": "12", "zooms": "5@0.7,0.3,2.5"})
        self.assertEqual(o[1]["until"], "20")
        self.assertEqual(o[2], {"once": True, "start": "20", "zooms": "19@0.2,0.6,3;20@0.5,0.5,1"})

    def test_other_clips_and_lone_slides_untouched(self):
        a, b = self._s({"zoom": "5@0.7,0.3,2"}), self._s({"zoom": "9@0.5,0.5,1"})
        b["blocks"][0]["name"] = "other.mov"
        self.assertEqual(refract.resolve_video_chains([a, b]), [a, b])


if __name__ == "__main__":
    unittest.main()

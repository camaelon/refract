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


if __name__ == "__main__":
    unittest.main()

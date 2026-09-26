"""refract.py's command line: the flags a script or a Makefile typed once and expects to keep.

The parser is built without running anything, so each case is just a command line and what
it should mean. The export flags matter most: `--pdf`, `--images` and `--video` each take an
optional path, and a flag left bare must still be "asked for" rather than "not given".
"""
import unittest

import refract


class CliArgs(unittest.TestCase):
    def parse(self, *words):
        return refract.build_parser().parse_args(list(words))

    def test_defaults(self):
        a = self.parse()
        self.assertEqual(a.deck, ".")
        self.assertIsNone(a.pdf)
        self.assertIsNone(a.images)
        self.assertIsNone(a.video)
        self.assertFalse(a.watch or a.force or a.json_only or a.check)

    def test_bare_export_flags_mean_the_default_path(self):
        a = self.parse("mytalk", "--pdf")
        self.assertEqual(a.pdf, "", "asked for, path left to the default")
        self.assertEqual(self.parse("--video").video, "")
        self.assertEqual(self.parse("--images").images, "")

    def test_export_flags_take_a_path(self):
        self.assertEqual(self.parse("--pdf", "talk.pdf").pdf, "talk.pdf")
        self.assertEqual(self.parse("--video", "talk.mp4", "mytalk").video, "talk.mp4")

    def test_video_range_and_timing(self):
        a = self.parse("mytalk", "--video", "--from", "3", "--to", "12", "--fps", "24", "--dwell", "2.5")
        self.assertEqual((a.video_from, a.video_to), (3, 12))
        self.assertEqual(a.fps, 24.0)
        self.assertEqual(a.dwell, 2.5)

    def test_video_captions(self):
        self.assertFalse(self.parse("--video").captions, "off unless asked: it makes the picture taller")
        self.assertTrue(self.parse("--video", "--captions").captions)

    def test_video_defaults_cover_the_whole_deck(self):
        a = self.parse("--video")
        self.assertEqual((a.video_from, a.video_to), (1, 0), "0 for --to means the last slide")
        self.assertEqual(a.fps, 30.0)
        self.assertEqual(a.dwell, 4.0)

    def test_every_flag_is_in_the_help(self):
        text = refract.build_parser().format_help()
        for flag in ("--pdf", "--images", "--video", "--from", "--to", "--fps", "--dwell", "--captions",
                     "--watch", "--force", "--json-only", "--json2rc", "--check", "--transitions"):
            self.assertIn(flag, text, flag)


if __name__ == "__main__":
    unittest.main()

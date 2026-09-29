"""The web export's slide selection: the same rule the player's --slides reads."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("web", os.path.join(HERE, "..", "player", "tools", "web.py"))
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class WebSlides(unittest.TestCase):
    def test_reads_ranges_and_numbers(self):
        self.assertEqual(web.parse_slides("3-5, 9", 12), [2, 3, 4, 8])
        self.assertEqual(web.parse_slides("", 3), [0, 1, 2])
        self.assertEqual(web.parse_slides("all", 3), [0, 1, 2])
        self.assertEqual(web.parse_slides("9, 3, 3", 12), [2, 8], "in order, without repeats")
        self.assertEqual(web.parse_slides("10-", 12), [9, 10, 11], "an open range runs to the end")
        self.assertEqual(web.parse_slides("0-2, 40", 12), [0, 1], "clamped to the deck")

    def test_refuses_what_it_cannot_read(self):
        for bad in ("3-x", "seven", "50"):
            with self.assertRaises(ValueError, msg=bad):
                web.parse_slides(bad, 12)
        self.assertEqual(web.parse_slides("1-3", 0), [])


if __name__ == "__main__":
    unittest.main()


class CameraTakes(unittest.TestCase):
    """Shipping a camera take at the size the slide shows it, not the size it was recorded."""

    def test_the_box_and_the_crop_come_out_of_the_config(self):
        self.assertEqual(web.camera_options("camera:default#crop=0.25,0.25,0.75,0.75&box=90x90"),
                         {"crop": [0.25, 0.25, 0.75, 0.75], "box": (90, 90)})
        self.assertEqual(web.camera_options("camera:default"), {})
        # A config read out of a slide's bytes has whatever followed it stuck on the end, and
        # a device name can hold spaces: what is read has to survive both.
        self.assertEqual(web.camera_options("camera:FaceTime HD#box=90x90&mirror=1]"),
                         {"box": (90, 90)})
        self.assertEqual(web.camera_options("camera:x#crop=0.9,0,0.1,1&box=10x10"),
                         {"box": (10, 10)}, "an inside-out crop is not a crop")
        data = b"\x00\x08camera:default#box=90x90\x00\x17other\x00camera:x#box=50x50\x01"
        self.assertEqual(web.camera_configs(data),
                         ["camera:default#box=90x90", "camera:x#box=50x50"])
        self.assertEqual(web.camera_configs(b"no cameras here"), [])

    def test_a_badge_ships_a_badge(self):
        # A 90x90 circle showing the middle half of a 1080p frame: 960x540 of source for a
        # box worth 270 pixels — so the region is scaled down to cover it, and no further.
        plan = web.take_frame_plan("camera:default#crop=0.25,0.25,0.75,0.75&box=90x90", 1920, 1080)
        self.assertEqual(plan["crop"], (480, 270, 960, 540))
        self.assertEqual(plan["out"], (480, 270), "cover the 270-pixel box, keeping the shape")
        self.assertLess(plan["out"][0] * plan["out"][1], 1920 * 1080 / 10, "a tenth of the pixels or less")

    def test_it_never_scales_up(self):
        # A box bigger than the recording: the recording is the ceiling.
        plan = web.take_frame_plan("camera:default#crop=0.25,0.25,0.75,0.75&box=900x900", 1920, 1080)
        self.assertEqual(plan["out"], (960, 540), "the cropped region, unscaled")

    def test_fit_sits_inside_the_box_where_fill_covers_it(self):
        fill = web.take_frame_plan("camera:default#box=100x100", 1000, 500)
        fits = web.take_frame_plan("camera:default#fit=fit&box=100x100", 1000, 500)
        self.assertEqual(fill["out"], (600, 300), "cover: the short side reaches 300")
        self.assertEqual(fits["out"], (300, 150), "fit: the long side reaches 300")

    def test_no_box_no_plan(self):
        self.assertIsNone(web.take_frame_plan("camera:default", 1920, 1080), "nothing said")
        self.assertIsNone(web.take_frame_plan("camera:default#box=0x0", 1920, 1080), "no box")
        self.assertIsNone(web.take_frame_plan("camera:default#box=90x90", 0, 0), "no source")
        self.assertIsNone(web.take_frame_plan("camera:default#box=9000x9000", 100, 100),
                          "nothing to gain: the whole frame, unscaled")

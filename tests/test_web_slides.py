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

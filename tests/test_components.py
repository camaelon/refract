import unittest

from refractkit import components as c


class Dbg(unittest.TestCase):
    def test_off(self):
        self.assertEqual(c.dbg(["a"], False), ["a"])

    def test_on_appends_border(self):
        out = c.dbg(["a"], True)
        self.assertEqual(out[-1], c.DEBUG_BORDER)


class Text(unittest.TestCase):
    def test_basic(self):
        t = c.text("hi", 24.0, "#FFFFFFFF", False)
        self.assertEqual(t["type"], "text")
        self.assertEqual(t["value"], "hi")
        self.assertEqual(t["fontSize"], 24.0)
        self.assertNotIn("modifiers", t)          # no modifiers when none

    def test_mono(self):
        t = c.text("x", 20.0, "#FF000000", False, mono=True)
        self.assertEqual(t["fontFamily"], "monospace")

    def test_extra_and_debug_modifiers(self):
        t = c.text("x", 20.0, "#FF000000", True, extra=[{"weight": 1.0}])
        self.assertIn({"weight": 1.0}, t["modifiers"])
        self.assertIn(c.DEBUG_BORDER, t["modifiers"])


if __name__ == "__main__":
    unittest.main()

import unittest

from refractkit import inline
from refractkit.theme import build_theme

THEME = build_theme({})


class ParseSpans(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(inline.parse_spans("hello"), [("hello", set())])

    def test_bold(self):
        spans = inline.parse_spans("a **b** c")
        self.assertEqual(spans, [("a ", set()), ("b", {"bold"}), (" c", set())])

    def test_italic_and_code(self):
        spans = inline.parse_spans("*i* and `c`")
        types = [s for _, s in spans]
        self.assertIn({"italic"}, types)
        self.assertIn({"code"}, types)

    def test_has_markup(self):
        self.assertTrue(inline.has_markup("x **y**"))
        self.assertFalse(inline.has_markup("plain text"))


class StyledLine(unittest.TestCase):
    def test_row_of_spans(self):
        row = inline.styled_line("a **b** `c`", 40.0, "#FFFFFFFF", THEME, False)
        self.assertEqual(row["type"], "row")
        kids = row["children"]
        bold = next(k for k in kids if k["value"] == "b")
        self.assertEqual(bold["fontWeight"], 700.0)
        code = next(k for k in kids if k["value"] == "c")
        self.assertEqual(code["fontFamily"], "monospace")
        self.assertEqual(code["color"], THEME.accent)

    def test_italic_style(self):
        row = inline.styled_line("*x*", 40.0, "#FFFFFFFF", THEME, False)
        self.assertEqual(row["children"][0]["fontStyle"], "italic")


if __name__ == "__main__":
    unittest.main()

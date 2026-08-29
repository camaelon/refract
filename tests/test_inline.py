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
        # Inline-styled lines render as a wrapping Flow of word/space tokens.
        self.assertEqual(row["type"], "flow")
        kids = row["children"]
        bold = next(k for k in kids if k["value"] == "b")
        self.assertEqual(bold["fontWeight"], 700.0)
        code = next(k for k in kids if k["value"] == "c")
        self.assertEqual(code["fontFamily"], "monospace")
        self.assertEqual(code["color"], THEME.accent)

    def test_italic_style(self):
        row = inline.styled_line("*x*", 40.0, "#FFFFFFFF", THEME, False)
        self.assertEqual(row["children"][0]["fontStyle"], "italic")

    def test_tokens_align_by_baseline(self):
        # Every token carries alignByBaseline so mixed styles share one baseline
        # when the Flow wraps across lines.
        row = inline.styled_line("a **b** c", 40.0, "#FFFFFFFF", THEME, False)
        for kid in row["children"]:
            self.assertIn("alignByBaseline", kid["modifiers"])

    def test_wraps_preserve_spacing(self):
        # Whitespace is kept as its own token so spacing survives word-level wrapping.
        row = inline.styled_line("a *b* c", 40.0, "#FFFFFFFF", THEME, False)
        self.assertEqual([k["value"] for k in row["children"]],
                         ["a", " ", "b", " ", "c"])


class AuthorColors(unittest.TestCase):
    AUTHORS = {"Nicolas Roard": "#FF5CC8FF", "Nico": "#FF5CC8FF",
               "John Hoford": "#FFF6A96B", "John": "#FFF6A96B"}

    def test_longest_name_wins(self):
        segs = inline._author_segments("Nicolas Roard / John Hoford", self.AUTHORS)
        self.assertEqual(segs, [("Nicolas Roard", "#FF5CC8FF"), (" / ", None),
                                ("John Hoford", "#FFF6A96B")])

    def test_whole_word_only(self):
        # 'Nico' must not tint the substring inside 'Nicolas'.
        segs = inline._author_segments("Nicolas", {"Nico": "#FF5CC8FF"})
        self.assertEqual(segs, [("Nicolas", None)])

    def test_styled_line_tints_authors(self):
        from dataclasses import replace
        theme = replace(THEME, authors=self.AUTHORS)
        flow = inline.styled_line("Nicolas Roard / John Hoford", 46.0, "#FFEEEEEE",
                                  theme, False)
        nico = next(k for k in flow["children"] if k["value"] == "Nicolas")
        john = next(k for k in flow["children"] if k["value"] == "John")
        self.assertEqual(nico["color"], "#FF5CC8FF")
        self.assertEqual(john["color"], "#FFF6A96B")


class FlowAlignment(unittest.TestCase):
    def test_default_start(self):
        flow = inline.styled_line("a **b**", 40.0, "#FFFFFFFF", THEME, False)
        self.assertEqual(flow["horizontalAlignment"], "start")

    def test_centered(self):
        flow = inline.styled_line("a **b**", 40.0, "#FFFFFFFF", THEME, False,
                                  align="center")
        self.assertEqual(flow["horizontalAlignment"], "center")


if __name__ == "__main__":
    unittest.main()

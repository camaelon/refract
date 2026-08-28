import unittest

from refractkit import highlight as hl
from refractkit.theme import build_theme


def _types(line_spans):
    return {ttype for _, ttype in line_spans}


def _text(line_spans):
    return "".join(t for t, _ in line_spans)


class Kotlin(unittest.TestCase):
    def tok(self, code):
        return hl.tokenize_kotlin(code)

    def test_keyword(self):
        line = self.tok("val x = 1")[0]
        self.assertIn(("val", "keyword"), line)

    def test_type_capitalized(self):
        line = self.tok("val s: String")[0]
        self.assertIn(("String", "type"), line)

    def test_string(self):
        line = self.tok('val s = "hi"')[0]
        self.assertIn('"hi"', [t for t, _ in line])
        self.assertIn("string", _types(line))

    def test_comment(self):
        line = self.tok("// note")[0]
        self.assertIn("comment", _types(line))

    def test_number(self):
        line = self.tok("val n = 42")[0]
        self.assertIn("number", _types(line))

    def test_annotation(self):
        line = self.tok("@Composable")[0]
        self.assertIn("annotation", _types(line))

    def test_line_reconstructs_exactly(self):
        code = "fun greet(name: String) {"
        line = self.tok(code)[0]
        self.assertEqual(_text(line), code)


class Json(unittest.TestCase):
    def test_key_vs_string(self):
        line = hl.tokenize_json('{"k": "v"}')[0]
        types = dict((t, tt) for t, tt in line)
        self.assertEqual(types['"k"'], "key")
        self.assertEqual(types['"v"'], "string")

    def test_number_and_literal(self):
        line = hl.tokenize_json('{"a": 3, "b": true}')[0]
        tt = _types(line)
        self.assertIn("number", tt)
        self.assertIn("literal", tt)


class Registry(unittest.TestCase):
    def test_unknown_language_plain(self):
        lines = hl.highlight("some text", "brainfuck")
        self.assertEqual(lines, [[("some text", "default")]])

    def test_blank_line_empty(self):
        lines = hl.highlight("a\n\nb", "brainfuck")
        self.assertEqual(lines[1], [])


class RenderCode(unittest.TestCase):
    def test_structure(self):
        theme = build_theme({})
        out = hl.render_code({"lang": "kotlin", "text": "val x = 1"}, theme, False)
        col = out[0]
        self.assertEqual(col["type"], "column")
        rows = col["children"]
        self.assertEqual(rows[0]["type"], "row")
        # all spans are monospace text
        self.assertTrue(all(s.get("fontFamily") == "monospace"
                            for s in rows[0]["children"]))

    def test_rounded_clip_when_radius(self):
        theme = build_theme({"code": {"corner_radius": 16}})
        col = hl.render_code({"lang": "json", "text": "{}"}, theme, False)[0]
        clips = [m for m in col["modifiers"] if isinstance(m, dict) and "clip" in m]
        self.assertEqual(clips, [{"clip": 16.0}])

    def test_no_clip_by_default(self):
        theme = build_theme({})
        col = hl.render_code({"lang": "json", "text": "{}"}, theme, False)[0]
        self.assertFalse(any(isinstance(m, dict) and "clip" in m for m in col["modifiers"]))


if __name__ == "__main__":
    unittest.main()

import unittest

from refractkit.markdown import parse_meta
import refract


class MetaOverrides(unittest.TestCase):
    def test_overrides_extracted(self):
        m = parse_meta("content bg=#000 accent=#FFF")
        self.assertEqual(m["overrides"], {"bg": "#000", "accent": "#FFF"})

    def test_flags(self):
        self.assertIn("fragment", parse_meta("content fragment")["flags"])

    def test_speaker_with_overrides_and_flags(self):
        m = parse_meta("content fragment bg=#000 : Yuri")
        self.assertEqual(m["type"], "content")
        self.assertEqual(m["params"], "Yuri")
        self.assertIn("fragment", m["flags"])
        self.assertEqual(m["overrides"]["bg"], "#000")

    def test_backward_compat(self):
        m = parse_meta("content [2:3] : Nico")
        self.assertEqual(m["type"], "content")
        self.assertEqual(m["params"], "Nico")
        self.assertEqual(m["ratio"], [2, 3])

    def test_author_attribution(self):
        # ``@name`` is pulled out as the slide's author, anywhere on the line.
        self.assertEqual(parse_meta("content @John")["author"], "John")
        self.assertEqual(parse_meta("@Nico")["author"], "Nico")
        m = parse_meta("include : intro @Nico")
        self.assertEqual(m["author"], "Nico")
        self.assertEqual(m["params"], "intro")            # @name not swallowed into params
        self.assertIsNone(parse_meta("content")["author"])


class ThemeOverrides(unittest.TestCase):
    def test_bg_and_shader_none(self):
        from refractkit.theme import build_theme
        theme = build_theme({"shader": {"source": "x"}})
        ch = refract.theme_overrides({"bg": "#FF101010", "shader": "none"}, theme)
        self.assertEqual(ch["background"], "#FF101010")
        self.assertEqual(ch["shaders"], {})


class Fragments(unittest.TestCase):
    def _slide(self, flags, items):
        return {"meta": {"type": "content", "flags": flags},
                "blocks": [{"kind": "bullets", "items": items}]}

    def test_expands_by_group(self):
        items = [{"level": 0, "text": "a"}, {"level": 1, "text": "a1"},
                 {"level": 0, "text": "b"}]
        out = refract.expand_fragments([self._slide(["fragment"], items)])
        self.assertEqual(len(out), 2)                        # 2 top-level groups
        self.assertEqual(len(out[0]["blocks"][0]["items"]), 2)   # a + a1
        self.assertEqual(len(out[1]["blocks"][0]["items"]), 3)   # a + a1 + b

    def test_non_fragment_passthrough(self):
        s = self._slide([], [{"level": 0, "text": "a"}])
        self.assertEqual(refract.expand_fragments([s]), [s])


if __name__ == "__main__":
    unittest.main()


class Agenda(unittest.TestCase):
    def test_numbering_and_toc(self):
        slides = [
            {"meta": {"type": "agenda"}, "title": "Agenda", "blocks": [], "base_dir": "."},
            {"meta": {"type": "section"}, "title": "Intro", "blocks": []},
            {"meta": {"type": "section"}, "title": "Deep Dive", "blocks": []},
        ]
        out = refract.apply_agenda(slides)
        # sections numbered
        self.assertEqual(out[1]["title"], "1. Intro")
        self.assertEqual(out[2]["title"], "2. Deep Dive")
        # agenda expanded to a bullets TOC
        items = out[0]["blocks"][0]["items"]
        self.assertEqual(len(items), 2)
        self.assertIn("Intro", items[0]["text"])

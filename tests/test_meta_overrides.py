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

    def test_steps_after_first_marked_reveal(self):
        items = [{"level": 0, "text": "a"}, {"level": 0, "text": "b"},
                 {"level": 0, "text": "c"}]
        out = refract.expand_fragments([self._slide(["steps"], items)])
        self.assertEqual(len(out), 3)
        self.assertFalse(out[0]["meta"].get("reveal_step"))      # first step: normal
        self.assertTrue(out[1]["meta"]["reveal_step"])           # later steps animate the diff
        self.assertTrue(out[2]["meta"]["reveal_step"])

    def test_global_steps_default_and_overrides(self):
        items = [{"level": 0, "text": "a"}, {"level": 0, "text": "b"}]
        base = {"meta": {"type": "content", "flags": [], "overrides": {}},
                "blocks": [{"kind": "bullets", "items": items}]}
        # global default on → a plain content slide with bullets is stepped
        self.assertEqual(len(refract.expand_fragments([base], steps_default=True)), 2)
        # per-slide opt-out wins over the global default
        off = {**base, "meta": {"type": "content", "flags": ["nosteps"], "overrides": {}}}
        self.assertEqual(len(refract.expand_fragments([off], steps_default=True)), 1)
        # and `steps=off` override too
        off2 = {**base, "meta": {"type": "content", "flags": [], "overrides": {"steps": "off"}}}
        self.assertEqual(len(refract.expand_fragments([off2], steps_default=True)), 1)


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
        # sections keep a clean title but carry their number (renderer colours it)
        self.assertEqual(out[1]["title"], "Intro")
        self.assertEqual(out[1]["section_number"], 1)
        self.assertEqual(out[2]["section_number"], 2)
        # agenda expanded to a bullets TOC
        items = out[0]["blocks"][0]["items"]
        self.assertEqual(len(items), 2)
        self.assertIn("Intro", items[0]["text"])

    def test_compute_sections_colors_by_expected_speaker(self):
        from refractkit.theme import build_theme
        theme = build_theme({"theme": {"primary": "#FF111111"},
                             "authors": {"Nico": "#FF00AAFF", "John": "#FFEE8800"}})
        speakers = {}
        slides = [
            {"meta": {"type": "content"}, "title": "Cover"},                 # 0: no section
            {"meta": {"type": "section", "author": "Nico"}, "title": "A"},   # 1: Nico
            {"meta": {"type": "content", "author": "Nico"}, "title": "a1"},  # 2
            {"meta": {"type": "section"}, "title": "B"},                     # 3: unattributed…
            {"meta": {"type": "content", "author": "John"}, "title": "b1"},  # 4: …first authored = John
        ]
        secs = refract.compute_sections(slides, theme, speakers)
        self.assertEqual([(s["start"], s["color"]) for s in secs],
                         [(1, "#FF00AAFF"), (3, "#FFEE8800")])

    def test_outline_slide_synthesizes_section_list(self):
        slides = [
            {"meta": {"type": "outline"}, "title": None, "blocks": [], "base_dir": "."},
            {"meta": {"type": "section"}, "title": "Intro", "blocks": []},
            {"meta": {"type": "section"}, "title": "Deep Dive", "blocks": []},
        ]
        out = refract.apply_agenda(slides)
        block = out[0]["blocks"][0]
        self.assertEqual(block["kind"], "outline")
        self.assertEqual(out[0]["title"], "Outline")
        self.assertEqual([(it["num"], it["title"]) for it in block["items"]],
                         [(1, "Intro"), (2, "Deep Dive")])

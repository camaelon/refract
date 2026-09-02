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

    def test_pad_left_override(self):
        from refractkit.theme import build_theme
        ch = refract.theme_overrides({"pad_left": "120"}, build_theme({}))
        self.assertEqual(ch["pad_extra"], (120.0, 0.0, 0.0, 0.0))

    def test_pad_all_sides(self):
        from refractkit.theme import build_theme
        ch = refract.theme_overrides({"pad": "30", "pad_top": "10"}, build_theme({}))
        self.assertEqual(ch["pad_extra"], (30.0, 40.0, 30.0, 30.0))   # pad + per-side

    def test_no_pad_override(self):
        from refractkit.theme import build_theme
        self.assertNotIn("pad_extra", refract.theme_overrides({}, build_theme({})))


class Skip(unittest.TestCase):
    def _slide(self, flags=None, overrides=None):
        return {"meta": {"type": "content", "flags": flags or [],
                         "overrides": overrides or {}}, "blocks": []}

    def test_skip_flag(self):
        self.assertTrue(refract.is_skipped(self._slide(flags=["skip"])))

    def test_skip_override_true(self):
        self.assertTrue(refract.is_skipped(self._slide(overrides={"skip": "true"})))

    def test_skip_override_bare(self):
        # `skip` with no value (present in overrides) still skips.
        self.assertTrue(refract.is_skipped(self._slide(overrides={"skip": ""})))

    def test_not_skipped_by_default(self):
        self.assertFalse(refract.is_skipped(self._slide()))

    def test_skip_false_stays(self):
        self.assertFalse(refract.is_skipped(self._slide(overrides={"skip": "false"})))


class SameType(unittest.TestCase):
    def test_same_inherits_previous_type(self):
        slides = [{"meta": {"type": "split"}, "blocks": []},
                  {"meta": {"type": "same"}, "blocks": []}]
        out = refract.resolve_same_types(slides)
        self.assertEqual(out[1]["meta"]["type"], "split")   # inherited
        self.assertTrue(out[1]["meta"]["_same"])            # still animates the diff

    def test_consecutive_sames_inherit_base(self):
        slides = [{"meta": {"type": "split"}, "blocks": []},
                  {"meta": {"type": "same"}, "blocks": []},
                  {"meta": {"type": "same"}, "blocks": []}]
        out = refract.resolve_same_types(slides)
        self.assertEqual([s["meta"]["type"] for s in out], ["split", "split", "split"])

    def test_non_same_untouched(self):
        s = {"meta": {"type": "content"}, "blocks": []}
        out = refract.resolve_same_types([s])
        self.assertEqual(out[0]["meta"]["type"], "content")
        self.assertNotIn("_same", out[0]["meta"])


class EmbedStagger(unittest.TestCase):
    def _slide(self, n_stagger, plain=1):
        blocks = [{"kind": "text", "text": "x"} for _ in range(plain)]
        blocks += [{"kind": "include", "name": f"e{i}", "opts": {"stagger": True}}
                   for i in range(n_stagger)]
        return {"meta": {"type": "content"}, "blocks": blocks}

    def _reveals(self, slide):
        return [b["opts"]["_reveal"] for b in slide["blocks"] if b["kind"] == "include"]

    def test_no_stagger_passthrough(self):
        s = {"meta": {}, "blocks": [{"kind": "include", "name": "e", "opts": {}}]}
        self.assertEqual(refract.expand_embed_stagger([s]), [s])

    def test_one_embed_two_steps(self):
        out = refract.expand_embed_stagger([self._slide(1)])
        self.assertEqual(len(out), 2)                       # N+1 steps
        self.assertEqual(self._reveals(out[0]), ["hidden"])
        self.assertEqual(self._reveals(out[1]), ["fade"])
        self.assertFalse(out[0]["meta"].get("stagger_step"))
        self.assertTrue(out[1]["meta"]["stagger_step"])     # later steps render statically

    def test_two_embeds_three_steps(self):
        out = refract.expand_embed_stagger([self._slide(2)])
        self.assertEqual(len(out), 3)
        self.assertEqual(self._reveals(out[0]), ["hidden", "hidden"])
        self.assertEqual(self._reveals(out[1]), ["fade", "hidden"])   # first reveals
        self.assertEqual(self._reveals(out[2]), ["shown", "fade"])    # second reveals, first stays

    def test_does_not_mutate_source(self):
        s = self._slide(1)
        refract.expand_embed_stagger([s])
        self.assertNotIn("_reveal", s["blocks"][-1]["opts"])          # source opts untouched


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


class ScrollPlan(unittest.TestCase):
    def test_fits_no_pages(self):
        self.assertEqual(refract._scroll_plan("auto", 400, 560), (1, [0.0]))
        self.assertEqual(refract._scroll_plan("3", 400, 560), (1, [0.0]))

    def test_auto_uses_fixed_viewport_step(self):
        n, offs = refract._scroll_plan("auto", 2000, 560)
        self.assertGreater(n, 1)
        self.assertEqual(offs[0], 0.0)
        step = 560 * (1 - refract.SCROLL_OVERLAP)
        self.assertAlmostEqual(offs[1], round(step, 2), places=1)   # one viewport minus overlap
        self.assertLessEqual(offs[-1], 2000 - 560 + 0.5)            # last page clamped to bottom

    def test_explicit_n_spreads_evenly(self):
        n, offs = refract._scroll_plan("4", 2000, 560)
        self.assertEqual(n, 4)
        self.assertEqual(offs[0], 0.0)
        self.assertAlmostEqual(offs[-1], 2000 - 560, places=1)      # last lands at the bottom
        gaps = [round(offs[i + 1] - offs[i], 1) for i in range(3)]
        self.assertEqual(len(set(gaps)), 1)                         # evenly spaced


class ExpandScroll(unittest.TestCase):
    def _slide(self, overrides, n_paras=24, stype="content"):
        blocks = [{"kind": "text", "text": "word " * 30} for _ in range(n_paras)]
        return {"base_dir": "/tmp", "meta": {"type": stype, "overrides": overrides},
                "blocks": blocks, "title": "T"}

    def _theme(self):
        from refractkit.theme import build_theme
        return build_theme({})

    def test_overflowing_content_expands(self):
        out = refract.expand_scroll([self._slide({"scroll": "auto"})], self._theme(), 1600, 900)
        self.assertGreater(len(out), 1)
        self.assertEqual(out[0]["meta"]["scroll_page"]["index"], 0)
        self.assertIsNone(out[0]["meta"]["scroll_page"]["prev_offset"])
        self.assertIsNotNone(out[1]["meta"]["scroll_page"]["prev_offset"])

    def test_explicit_count(self):
        out = refract.expand_scroll([self._slide({"scroll": "3"})], self._theme(), 1600, 900)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[-1]["meta"]["scroll_page"]["count"], 3)

    def test_no_scroll_passthrough(self):
        s = self._slide({})
        self.assertEqual(refract.expand_scroll([s], self._theme(), 1600, 900), [s])

    def test_same_slide_not_paginated(self):
        # `:: same scroll=1` is a manual offset, handled in the main loop — not expanded here.
        s = self._slide({"scroll": "1"}, stype="same")
        self.assertEqual(refract.expand_scroll([s], self._theme(), 1600, 900), [s])

    def test_fitting_content_passthrough(self):
        s = self._slide({"scroll": "auto"}, n_paras=1)
        self.assertEqual(len(refract.expand_scroll([s], self._theme(), 1600, 900)), 1)

    def _split_slide(self, overrides, n_paras=20):
        # A split slide: overflowing left column + a pane break + a right block.
        left = [{"kind": "text", "text": "word " * 30} for _ in range(n_paras)]
        blocks = left + [{"kind": "pane_break"}, {"kind": "text", "text": "right"}]
        return {"base_dir": "/tmp", "meta": {"type": "split", "overrides": overrides},
                "blocks": blocks, "title": "T"}

    def test_split_scrolls_first_column(self):
        # scroll on a multi-column split paginates the first (overflowing) column.
        out = refract.expand_scroll([self._split_slide({"scroll": "auto"})],
                                    self._theme(), 1600, 900)
        self.assertGreater(len(out), 1)
        self.assertEqual(out[0]["meta"]["scroll_page"]["index"], 0)

    def test_split_fitting_passthrough(self):
        s = self._split_slide({"scroll": "auto"}, n_paras=1)
        self.assertEqual(len(refract.expand_scroll([s], self._theme(), 1600, 900)), 1)


class SameScrollFrac(unittest.TestCase):
    def test_reads_fraction(self):
        self.assertEqual(refract._same_scroll_frac({"overrides": {"scroll": "1.5"}}), 1.5)

    def test_absent_is_zero(self):
        self.assertEqual(refract._same_scroll_frac({"overrides": {}}), 0.0)

    def test_bad_value_is_zero(self):
        self.assertEqual(refract._same_scroll_frac({"overrides": {"scroll": "auto"}}), 0.0)


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

    def test_cleanup_never_deletes_source_includes(self):
        # Only intermediates under json_dir are removable; a source compiled from includes/
        # must never be returned (regression: we once deleted user source files).
        json_dir = "/deck/out/json"
        pairs = [
            ("/deck/out/json/01_slide.json", "/deck/out/01_slide.rc"),          # intermediate
            ("/deck/includes/demo/aliens.json", "/deck/out/media/aliens.rc"),   # SOURCE — keep!
        ]
        self.assertEqual(refract.intermediate_jsons(pairs, json_dir),
                         ["/deck/out/json/01_slide.json"])

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

import unittest

import refract
from refractkit import markdown as md
from refractkit.settings import load_settings
from refractkit.theme import build_theme


def theme_for(**settings):
    base = {"slide": {"width": 1600, "height": 900}}
    base.update(settings)
    return build_theme(base, ".")


def slide(source):
    """One slide, parsed and with its blocks resolved — what the build loop works on."""
    parsed = md.parse_slide(source)
    parsed["base_dir"] = "."
    return parsed


class SlideStyle(unittest.TestCase):
    """The theme a slide renders with, and how it transitions in.

    Pulled out of the build loop so it can be asked directly. Every one of these used to be
    reachable only by building a deck and looking at the pixels.
    """

    def style(self, source, *, speakers=None, transitions=None, **kw):
        return refract.slide_style(slide(source), theme_for(**kw), speakers or {},
                                   transitions or {})

    def test_a_plain_slide_uses_the_deck_theme(self):
        theme = theme_for()
        stheme, style, dur = refract.slide_style(slide("# Hello"), theme, {}, {})
        self.assertEqual(stheme.accent, theme.accent)
        self.assertEqual(style, "fade")
        self.assertEqual(dur, refract.PUSH_DURATION)

    def test_a_named_speaker_colours_the_slide(self):
        stheme, _, _ = self.style(":: content : Ada\n# Hello", speakers={"Ada": "#FF00FF00"})
        self.assertEqual(stheme.accent, "#FF00FF00")

    def test_an_author_colours_it_and_is_named_in_the_chrome(self):
        theme = theme_for(authors={"Ada": "#FF0000FF"})
        stheme, _, _ = refract.slide_style(slide(":: content @Ada\n# Hello"), theme, {}, {})
        self.assertEqual(stheme.slide_author, "Ada")
        self.assertEqual(stheme.accent, "#FF0000FF")

    def test_a_slide_override_wins_over_the_deck(self):
        stheme, _, _ = self.style(":: content accent=#FFABCDEF\n# Hello")
        self.assertEqual(stheme.accent.upper(), "#FFABCDEF")

    def test_the_transition_style_comes_from_the_slide_then_its_type_then_the_deck(self):
        deck = {"style": "fade", "section": {"style": "slide-up"}}
        # The deck's default.
        _, style, _ = self.style("# Hello", transitions=deck)
        self.assertEqual(style, "fade")
        # The slide type's.
        _, style, _ = self.style(":: section\n# Part", transitions=deck)
        self.assertEqual(style, "slide-up")
        # The slide's own, over both.
        _, style, _ = self.style(":: section transition=push\n# Part", transitions=deck)
        self.assertEqual(style, "push")

    def test_the_push_duration_follows_the_same_order(self):
        deck = {"duration": 0.5, "section": {"duration": 0.9}}
        self.assertEqual(self.style("# Hello", transitions=deck)[2], 0.5)
        self.assertEqual(self.style(":: section\n# P", transitions=deck)[2], 0.9)
        self.assertEqual(
            self.style(":: section transition_duration=1.4\n# P", transitions=deck)[2], 1.4)

    def test_transition_fx_is_opt_in(self):
        # The deck may have a transition shader; a slide draws it only when it, or its slide
        # type, asks for it. Off, the shader is cleared for that slide rather than the deck.
        from dataclasses import replace
        theme = replace(theme_for(), transition_shader="half4 main() { return half4(1); }")
        stheme, _, _ = refract.slide_style(slide("# Hello"), theme, {}, {})
        self.assertEqual(stheme.transition_shader, "")
        stheme, _, _ = refract.slide_style(slide(":: content transition_fx=on\n# Hello"),
                                           theme, {}, {})
        self.assertEqual(stheme.transition_shader, theme.transition_shader)
        # A slide type can ask for it on the deck's behalf.
        stheme, _, _ = refract.slide_style(slide(":: section\n# Part"), theme, {},
                                           {"section": {"fx": True}})
        self.assertEqual(stheme.transition_shader, theme.transition_shader)

    def test_a_reveal_override(self):
        stheme, _, _ = self.style(":: content reveal=immediate\n# Hello")
        self.assertEqual(stheme.content_reveal, "immediate")


class RenderSlide(unittest.TestCase):
    """Which of the seven ways a slide can be built gets used, and why.

    This is the branch that decides whether a slide crossfades, pushes, morphs a graph,
    diffs against the one before it or just draws — and it depends on what came *before* the
    slide as much as on the slide. Checking it used to mean building a deck and looking.
    """

    def render(self, source, *, prev=None, transitions=False, style="fade", index=1):
        s = slide(source)
        blocks = s["blocks"]
        theme = theme_for()
        prev_pair = None
        if prev is not None:
            p = slide(prev)
            prev_pair = (p, p["blocks"])
        return refract.render_slide(s, blocks, theme, prev_pair, theme,
                                    1600, 900, index, 5, False,
                                    transitions=transitions, style=style, push_dur=0.6)

    def test_the_first_slide_is_drawn_on_its_own(self):
        # Nothing to animate in from, whatever the deck's transitions say.
        _, tag = self.render("# Hello", prev=None, transitions=True)
        self.assertEqual(tag, "content")

    def test_a_later_slide_crossfades_when_transitions_are_on(self):
        _, tag = self.render("# Two", prev="# One", transitions=True)
        self.assertEqual(tag, "transition")

    def test_and_does_not_when_they_are_off(self):
        _, tag = self.render("# Two", prev="# One", transitions=False)
        self.assertEqual(tag, "content")

    def test_push_and_push_up(self):
        _, tag = self.render("# Two", prev="# One", transitions=True, style="push")
        self.assertEqual(tag, "push")
        _, tag = self.render("# Two", prev="# One", transitions=True, style="slide-up")
        self.assertEqual(tag, "push-up")

    def test_same_diffs_against_the_slide_before_it(self):
        # `:: same` animates the change in place, and does so whether or not the deck has
        # transitions on — it is a different mechanism.
        s = slide(":: content\n# One\n- a")
        prev = (s, s["blocks"])
        after = slide(":: same\n# One\n- a\n- b")
        after["meta"]["_same"] = True
        _, tag = refract.render_slide(after, after["blocks"], theme_for(), prev, theme_for(),
                                      1600, 900, 1, 5, False,
                                      transitions=False, style="fade", push_dur=0.6)
        self.assertEqual(tag, "same")

    def test_a_reveal_step_is_a_step(self):
        s = slide("# One\n- a")
        prev = (s, s["blocks"])
        step = slide("# One\n- a\n- b")
        step["meta"] = {"reveal_step": True}
        _, tag = refract.render_slide(step, step["blocks"], theme_for(), prev, theme_for(),
                                      1600, 900, 1, 5, False,
                                      transitions=False, style="fade", push_dur=0.6)
        self.assertEqual(tag, "step")

    def test_a_stagger_step_renders_statically(self):
        s = slide("# One")
        s["meta"] = {"stagger_step": True}
        _, tag = refract.render_slide(s, s["blocks"], theme_for(), None, None,
                                      1600, 900, 1, 5, False,
                                      transitions=True, style="fade", push_dur=0.6)
        self.assertEqual(tag, "stagger")

    def test_a_scroll_page_after_the_first_scrolls(self):
        s = slide("# Long\nbody")
        s["meta"] = {"scroll_page": {"index": 1, "count": 3, "offset": 400.0,
                                     "prev_offset": 0.0, "viewport": 600.0}}
        _, tag = refract.render_slide(s, s["blocks"], theme_for(), None, None,
                                      1600, 900, 1, 5, False,
                                      transitions=False, style="fade", push_dur=0.6)
        self.assertEqual(tag, "scroll 2/3")

    def test_every_branch_produces_a_document(self):
        for source, prev, transitions, style in (
                ("# Hello", None, False, "fade"),
                ("# Two", "# One", True, "fade"),
                ("# Two", "# One", True, "push"),
                ("# Two", "# One", True, "slide-up")):
            with self.subTest(style=style, transitions=transitions):
                doc, _ = self.render(source, prev=prev, transitions=transitions, style=style)
                self.assertIn("root", doc)
                # The root is a component tree of some shape; what matters here is that every
                # branch produced one at all, and that it has something in it.
                self.assertTrue(doc["root"])


class ManifestRecord(unittest.TestCase):
    """What a player is told about a slide without opening it."""

    def record(self, source, index=3, **extra):
        s = slide(source)
        s.update(extra)
        return refract.manifest_record(s, index, "/deck/out/04_hello.rc", "/deck")

    def test_the_basics(self):
        r = self.record("# Hello")
        self.assertEqual(r["index"], 3)
        self.assertEqual(r["file"], "04_hello.rc")
        self.assertEqual(r["title"], "Hello")
        self.assertEqual(r["type"], "content")
        self.assertFalse(r["notes"])

    def test_notes_are_flagged_not_carried(self):
        r = self.record("# Hello\n???\nsay this")
        self.assertTrue(r["notes"])
        self.assertNotIn("say this", str(r))

    def test_provenance(self):
        r = self.record("# Hello", src_file="/deck/slides.md", src_index=7)
        self.assertEqual(r["src"], "slides.md")
        self.assertEqual(r["src_index"], 7)
        self.assertNotIn("src_via", r)

    def test_an_included_slide_carries_its_chain(self):
        r = self.record("# Hello",
                        src_file="/deck/includes/intro/slides.md", src_index=1,
                        src_via=[{"src": "/deck/slides.md", "src_index": 4}])
        self.assertEqual(r["src"], "includes/intro/slides.md")
        self.assertEqual(r["src_via"], [{"src": "slides.md", "src_index": 4}])

    def test_a_deck_without_provenance_says_nothing_about_it(self):
        r = self.record("# Hello")
        self.assertNotIn("src", r)
        self.assertNotIn("src_index", r)

    def test_speaker_and_author(self):
        r = self.record(":: content : Ada @Grace\n# Hello")
        self.assertEqual(r["speaker"], "Ada")
        self.assertEqual(r["author"], "Grace")

    def test_a_section_number(self):
        self.assertEqual(self.record("# Part", section_number=2)["section"], 2)
        self.assertNotIn("section", self.record("# Hello"))


if __name__ == "__main__":
    unittest.main()

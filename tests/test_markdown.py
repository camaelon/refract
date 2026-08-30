import unittest

from refractkit import markdown as md


class ParseMeta(unittest.TestCase):
    def test_type_only(self):
        m = md.parse_meta("title")
        self.assertEqual(m["type"], "title")
        self.assertEqual(m["params"], "")
        self.assertIsNone(m["ratio"])

    def test_type_and_params(self):
        m = md.parse_meta("content : hello world")
        self.assertEqual(m["type"], "content")
        self.assertEqual(m["params"], "hello world")

    def test_ratio_standalone(self):
        m = md.parse_meta("[2:3]")
        self.assertEqual(m["ratio"], [2, 3])
        self.assertEqual(m["type"], "")

    def test_ratio_with_type(self):
        m = md.parse_meta("content [2:2:4]")
        self.assertEqual(m["ratio"], [2, 2, 4])
        self.assertEqual(m["type"], "content")

    def test_empty(self):
        m = md.parse_meta("")
        self.assertEqual(m["type"], "")
        self.assertIsNone(m["ratio"])


class ParseSlide(unittest.TestCase):
    def test_title_and_text(self):
        s = md.parse_slide("# Title\nsome body text")
        self.assertEqual(s["title"], "Title")
        self.assertEqual(s["blocks"], [{"kind": "text", "text": "some body text"}])

    def test_bullets_levels(self):
        s = md.parse_slide("- a\n  - b\n    - c")
        bl = s["blocks"][0]
        self.assertEqual(bl["kind"], "bullets")
        self.assertEqual([it["level"] for it in bl["items"]], [0, 1, 2])
        self.assertEqual(bl["items"][0]["text"], "a")

    def test_code_block(self):
        s = md.parse_slide("# C\n```kotlin\nfun x() {}\n```")
        code = [b for b in s["blocks"] if b["kind"] == "code"][0]
        self.assertEqual(code["lang"], "kotlin")
        self.assertEqual(code["text"], "fun x() {}")

    def test_graph_block_detected(self):
        s = md.parse_slide("# G\n```dot\ndigraph { A -> B }\n```")
        g = [b for b in s["blocks"] if b["kind"] == "graph"][0]
        self.assertEqual(g["engine"], "dot")
        self.assertIn("digraph", g["dot"])

    def test_pane_break_and_include(self):
        s = md.parse_slide("left\n+++\n<pic.png>")
        kinds = [b["kind"] for b in s["blocks"]]
        self.assertEqual(kinds, ["text", "pane_break", "include"])
        self.assertEqual(s["blocks"][2]["name"], "pic.png")

    def test_metadata_line(self):
        s = md.parse_slide(":: section : hi\n# Head")
        self.assertEqual(s["meta"]["type"], "section")
        self.assertEqual(s["title"], "Head")

    def test_weblink(self):
        s = md.parse_slide("# Demo\n<https://demo.dev | Live>")
        b = s["blocks"][0]
        self.assertEqual(b["kind"], "weblink")
        self.assertEqual(b["url"], "https://demo.dev")
        self.assertEqual(b["label"], "Live")

    def test_weblink_without_label(self):
        s = md.parse_slide("<http://x.io>")
        b = s["blocks"][0]
        self.assertEqual(b["kind"], "weblink")
        self.assertEqual(b["url"], "http://x.io")
        self.assertEqual(b["label"], "")

    def test_non_url_angle_is_include(self):
        s = md.parse_slide("<pic.png>")
        self.assertEqual(s["blocks"][0]["kind"], "include")

    def test_empty_slide_is_none(self):
        self.assertIsNone(md.parse_slide("   \n\n"))


class ParseMarkdown(unittest.TestCase):
    def test_splits_on_hr(self):
        slides = md.parse_markdown("# A\n\n---\n\n# B\n")
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0]["title"], "A")
        self.assertEqual(slides[1]["title"], "B")

    def test_skips_empty_chunks(self):
        slides = md.parse_markdown("---\n# A\n---\n\n")
        self.assertEqual(len(slides), 1)


if __name__ == "__main__":
    unittest.main()

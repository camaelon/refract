import os
import tempfile
import unittest

from refractkit.theme import Theme, build_theme, DEFAULT_SYNTAX


class ThemeDefaults(unittest.TestCase):
    def test_defaults(self):
        t = build_theme({})
        self.assertEqual(t.background, "#FF0D1B2A")
        self.assertEqual(t.code_font_size, 28.0)
        self.assertEqual(t.image_corner_radius, 0.0)
        self.assertEqual(t.shaders, {})

    def test_syntax_color_fallback(self):
        t = Theme()
        self.assertEqual(t.syntax_color("keyword"), DEFAULT_SYNTAX["keyword"])
        self.assertEqual(t.syntax_color("nonexistent"), t.code_foreground)


class ThemeSettings(unittest.TestCase):
    def test_theme_colors(self):
        t = build_theme({"theme": {"background": "#FF111111", "title_color": "#FF222222"}})
        self.assertEqual(t.background, "#FF111111")
        self.assertEqual(t.title_color, "#FF222222")

    def test_code_and_syntax(self):
        t = build_theme({"code": {"font_size": 40, "syntax": {"keyword": "#FFAAAAAA"}}})
        self.assertEqual(t.code_font_size, 40.0)
        self.assertEqual(t.syntax_color("keyword"), "#FFAAAAAA")
        # unspecified tokens keep defaults
        self.assertEqual(t.syntax_color("string"), DEFAULT_SYNTAX["string"])

    def test_image_corner_radius(self):
        self.assertEqual(build_theme({"image": {"corner_radius": 24}}).image_corner_radius, 24.0)

    def test_image_rounded_bool(self):
        self.assertGreater(build_theme({"image": {"rounded": True}}).image_corner_radius, 0)

    def test_code_corner_radius(self):
        self.assertEqual(build_theme({"code": {"corner_radius": 12}}).code_corner_radius, 12.0)

    def test_graph_colors(self):
        t = build_theme({"graph": {"node_fill": "#FF010203", "edge": "#FF040506"}})
        self.assertEqual(t.graph_node_fill, "#FF010203")
        self.assertEqual(t.graph_edge, "#FF040506")


class ThemeShaders(unittest.TestCase):
    def test_inline_source(self):
        t = build_theme({"shader": {"source": "half4 main(){return half4(1);}"}})
        self.assertIn("default", t.shaders)
        self.assertEqual(t.shader_for("content"), t.shaders["default"])

    def test_per_type_override_and_fallback(self):
        t = build_theme({"shader": {"source": "A", "title": {"source": "B"}}})
        self.assertEqual(t.shader_for("title"), "B")
        self.assertEqual(t.shader_for("content"), "A")  # falls back to default

    def test_file_source(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "s.sksl"), "w") as f:
            f.write("SHADER_BODY")
        t = build_theme({"shader": {"file": "s.sksl"}}, d)
        self.assertEqual(t.shader_for("content"), "SHADER_BODY")

    def test_disabled_shader(self):
        t = build_theme({"shader": {"source": "A", "enabled": False}})
        self.assertEqual(t.shaders, {})


class ThemeFonts(unittest.TestCase):
    def test_defaults(self):
        t = build_theme({})
        self.assertEqual(t.title_size("content"), 72.0)
        self.assertEqual(t.body_size("content"), 40.0)
        self.assertEqual(t.title_size("title"), 120.0)

    def test_alias_overrides(self):
        t = build_theme({"font": {"body": 48, "heading": 80, "table": 42, "title": 130}})
        self.assertEqual(t.body_size("content"), 48.0)
        self.assertEqual(t.title_size("content"), 80.0)   # heading alias
        self.assertEqual(t.title_size("title"), 130.0)    # title alias
        self.assertEqual(t.fonts["table"], 42.0)

    def test_direct_key_override(self):
        t = build_theme({"font": {"section_body": 55}})
        self.assertEqual(t.body_size("section"), 55.0)

    def test_font_code_alias(self):
        self.assertEqual(build_theme({"font": {"code": 30}}).code_font_size, 30.0)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

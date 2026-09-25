import unittest

from picker import metrics
from tests.support import SandboxCase, fixture


class ContrastVerdicts(unittest.TestCase):
    def test_high_contrast_theme(self):
        m = metrics.css_metrics(fixture("high_contrast.css"))
        self.assertEqual(m["warnings"], [])
        self.assertTrue(m["high_contrast"])
        self.assertEqual(m["mode"], "dark")
        self.assertEqual(m["family"], "blue")          # from the bare "R, G, B" accent
        self.assertEqual(set(m["ratios"]), set(metrics.HC_BAR))
        self.assertEqual(m["ratios"]["--text"], 21.0)

    def test_low_contrast_theme(self):
        m = metrics.css_metrics(fixture("low_contrast.css"))
        self.assertFalse(m["high_contrast"])
        self.assertEqual(m["mode"], "light")
        self.assertEqual(m["family"], "red")           # from a hex accent
        joined = " | ".join(m["warnings"])
        self.assertIn("body text 2.8:1 on panels (want 4.5:1)", joined)
        self.assertIn("muted text 1.6:1 on panels (want 3:1)", joined)
        self.assertIn("button label", joined)
        self.assertEqual(len(m["warnings"]), 3)

    def test_no_theme_is_high_contrast_by_omission(self):
        m = metrics.css_metrics(fixture("no_button_text.css"))
        self.assertIn("--button-text not defined", m["warnings"])
        self.assertNotIn("--button-text", m["ratios"])
        self.assertFalse(m["high_contrast"])

    def test_blackberry_style_overlay_reads_dark_and_readable(self):
        m = metrics.css_metrics(fixture("blackberry_like.css"))
        self.assertEqual(m["mode"], "dark")
        self.assertLess(m["lum"], 0.05)
        self.assertFalse(any("text" in w for w in m["warnings"]), m["warnings"])
        self.assertEqual(m["family"], "pink")

    def test_empty_sheet(self):
        m = metrics.css_metrics("")
        self.assertEqual((m["mode"], m["family"], m["high_contrast"]), ("", "neutral", False))
        self.assertEqual(m["warnings"], ["--button-text not defined"])

    def test_accent_falls_back_to_button_colour(self):
        m = metrics.css_metrics(":root { --button-color: #30a46c; }")
        self.assertEqual(m["family"], "green")


class ThemeMetricsByName(SandboxCase):
    def test_reads_custom_theme_from_disk(self):
        self.add_custom("hc", fixture("high_contrast.css"))
        self.assertTrue(metrics.theme_metrics("hc")["high_contrast"])
        self.add_custom("lc", fixture("low_contrast.css"))
        self.assertFalse(metrics.theme_metrics("lc")["high_contrast"])


if __name__ == "__main__":
    unittest.main()

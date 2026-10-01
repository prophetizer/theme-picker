import time
import unittest
from unittest import mock

from picker import themes
from tests.support import SandboxCase, fixture


class Palette(unittest.TestCase):
    def test_values_pass_through_as_background_shorthands(self):
        pal = themes.parse_palette(fixture("blackberry_like.css"))
        self.assertEqual(list(pal), list(themes.SWATCH_VARS))
        self.assertTrue(pal["--main-bg-color"].startswith("linear-gradient(rgba(10, 10, 20, 0.85)"))
        # var() resolved against the same file.
        self.assertEqual(pal["--modal-bg-color"], pal["--main-bg-color"])

    def test_fixed_attachment_becomes_scroll_in_swatches(self):
        pal = themes.parse_palette(fixture("blackberry_like.css"))
        self.assertIn("no-repeat scroll", pal["--main-bg-color"])
        self.assertNotIn("fixed", pal["--main-bg-color"])

    def test_url_layers_are_dropped_not_the_whole_value(self):
        pal = themes.parse_palette("--main-bg-color: url(noise.png), linear-gradient(#111, #222);")
        self.assertEqual(pal["--main-bg-color"], "linear-gradient(#111, #222)")

    def test_var_fallback_and_missing(self):
        pal = themes.parse_palette("--text: var(--nope, #abcdef); --link-color: var(--nope);")
        self.assertEqual(pal, {"--text": "#abcdef"})


class Discovery(SandboxCase):
    def test_fallback_lists_without_a_manifest(self):
        self.assertEqual(themes.official_themes(), themes.FALLBACK_OFFICIAL)
        self.assertEqual(themes.community_themes(), themes.FALLBACK_COMMUNITY)
        self.assertIsNone(themes._MANIFEST["data"])     # failure cached until the TTL

    def test_custom_themes_only_plain_names(self):
        for name in ("mine", "other-1", ".hidden", "-dash"):
            self.add_custom(name, ":root{}")
        (self.custom_dir / "notes.txt").write_text("")
        self.assertEqual(themes.custom_themes(), ["mine", "other-1"])

    def test_allowlist_is_all_three_sections(self):
        self.add_custom("mine", ":root{}")
        allowed = themes.allowed_themes()
        self.assertIn("nord", allowed)
        self.assertIn("catppuccin-mocha", allowed)
        self.assertIn("mine", allowed)
        self.assertNotIn("nord; rm -rf /", allowed)

    def test_current_theme(self):
        from picker import config
        self.assertEqual(themes.current_theme(), "unknown")
        config.CONFIG_FILE.write_text("# comment\nCURRENT_THEME=nord\n")
        self.assertEqual(themes.current_theme(), "nord")


class Manifest(SandboxCase):
    def setUp(self):
        super().setUp()
        from picker import config
        config.SETTINGS_FILE.write_text("BASE_URL=https://tp.example.test/\n")
        themes._MANIFEST["data"] = {
            "themes": {
                "Nord": {"url": "https://None.theme-park.dev/css/theme-options/nord.css?sha=abc"},
                "Mine": {"url": "https://None.theme-park.dev/css/theme-options/mine.css?sha=def"},
                "Bad": {"url": "https://x/css/theme-options/..%2fevil.css"},
            },
            "community-themes": {
                "Mocha": {"url": "https://None.theme-park.dev/css/community-theme-options/catppuccin-mocha.css"},
            },
        }
        self.add_custom("mine", ":root{}")

    def test_only_the_path_is_taken(self):
        self.assertEqual(themes.theme_css_url("nord"),
                         "https://tp.example.test/css/theme-options/nord.css?sha=abc")
        self.assertEqual(themes.theme_css_url("catppuccin-mocha"),
                         "https://tp.example.test/css/community-theme-options/catppuccin-mocha.css")

    def test_customs_are_not_listed_as_official(self):
        self.assertEqual(themes.official_themes(), ["nord"])
        self.assertEqual(themes.community_themes(), ["catppuccin-mocha"])

    def test_unsafe_slugs_are_skipped(self):
        self.assertNotIn("..%2fevil", themes.allowed_themes())

    def test_unknown_theme_url(self):
        self.assertEqual(themes.theme_css_url("unknown"), "")
        self.assertEqual(themes.theme_css_url("other"),
                         "https://tp.example.test/css/theme-options/other.css")


class Refresh(SandboxCase):
    """Caches follow the stylesheet: a redeployed theme must not keep its old
    swatches and badges until the picker is restarted."""

    def test_edited_custom_theme_is_re_read(self):
        import os
        from picker import metrics
        path = self.custom_dir / "t.css"
        path.write_text(fixture("high_contrast.css"))
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        self.assertTrue(metrics.theme_metrics("t")["high_contrast"])
        self.assertFalse(themes.is_gradient("t"))
        path.write_text(fixture("blackberry_like.css"))
        os.utime(path, ns=(2_000_000_000, 2_000_000_000))
        self.assertFalse(metrics.theme_metrics("t")["high_contrast"])
        self.assertTrue(themes.is_gradient("t"))

    def test_unchanged_theme_is_not_re_read(self):
        self.add_custom("t", fixture("high_contrast.css"))
        themes.theme_css("t")
        with mock.patch.object(themes, "_load_css", side_effect=AssertionError("re-read")):
            themes.theme_css("t")
            themes.theme_palette("t")

    def test_theme_park_theme_is_refetched_when_its_sha_changes(self):
        from picker import config
        config.SETTINGS_FILE.write_text("BASE_URL=https://tp.example.test\n")
        def manifest_with(sha):
            themes._MANIFEST.update(data={"themes": {"N": {"url": f"https://x/css/theme-options/nord.css?sha={sha}"}}},
                                    at=time.monotonic())
        fetched = []
        def fake_load(theme):
            fetched.append(themes.theme_css_url(theme))
            return fixture("high_contrast.css")
        with mock.patch.object(themes, "_load_css", side_effect=fake_load):
            manifest_with("aaa")
            themes.theme_css("nord"); themes.theme_css("nord")
            manifest_with("bbb")
            themes.theme_css("nord")
        self.assertEqual(fetched, ["https://tp.example.test/css/theme-options/nord.css?sha=aaa",
                                   "https://tp.example.test/css/theme-options/nord.css?sha=bbb"])

    def test_manifest_is_refetched_after_its_ttl(self):
        from picker import config
        config.SETTINGS_FILE.write_text("BASE_URL=https://tp.example.test\n")
        calls = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"themes": {}}'

        def fake_urlopen(url, timeout):
            calls.append(url)
            return Resp()
        with mock.patch.object(themes.urllib.request, "urlopen", side_effect=fake_urlopen), \
             mock.patch.object(themes.time, "monotonic", side_effect=[100.0, 200.0, 100.0 + themes.MANIFEST_TTL + 1]):
            themes.manifest(); themes.manifest(); themes.manifest()
        self.assertEqual(calls, ["https://tp.example.test/themes.json"] * 2)


class Gradient(SandboxCase):
    def test_is_gradient(self):
        self.add_custom("bb", fixture("blackberry_like.css"))
        self.add_custom("flat", fixture("high_contrast.css"))
        self.assertTrue(themes.is_gradient("bb"))
        self.assertFalse(themes.is_gradient("flat"))


if __name__ == "__main__":
    unittest.main()


class Variants(SandboxCase):
    VARIANT = "/*\n * theme.park custom theme: Nord (light)\n *\n * Generated variant: light of 'nord'\n */\n:root {\n  --main-bg-color: #eceff4;\n}\n"

    def test_found_by_header_and_kept_out_of_own_themes(self):
        from tests.support import fixture
        self.add_custom("mine", fixture("high_contrast.css"))
        self.add_custom("nord-light", self.VARIANT)
        self.assertEqual(themes.variant_themes(), ["nord-light"])
        self.assertEqual(themes.own_themes(), ["mine"])
        self.assertIn("nord-light", themes.allowed_themes())              # applies like any theme
        self.assertEqual([themes.section_of(t) for t in ("nord-light", "mine", "nord", "catppuccin-mocha")],
                         ["variants", "custom", "official", "community"])

    def test_pairs(self):
        self.add_custom("nord-light", self.VARIANT)
        self.add_custom("orphan-dark", self.VARIANT)                  # source gone: no pair
        self.assertEqual(themes.variant_pairs(), {"nord": "nord-light"})

    def test_added_timestamps_keep_the_new_badge_and_the_time(self):
        import json
        from datetime import datetime, timezone
        from picker import render, state
        self.add_custom("fresh-one", fixture("high_contrast.css"))
        self.add_custom("old-one", fixture("high_contrast.css"))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state.DATES_FILE.write_text(json.dumps({"fresh-one": now, "old-one": "2020-01-01"}))
        page = render.render_page()
        tile = lambda n: page[page.index(f'data-theme="{n}"'):page.index("</button>", page.index(f'data-theme="{n}"'))]
        self.assertIn(f'data-added="{now}"', tile("fresh-one"))           # the full time, for sorting
        self.assertIn('data-new="1"', tile("fresh-one"))                   # a timestamp still counts as new
        self.assertIn(f'title="Added {render.added_day(now)}"', tile("fresh-one"))
        self.assertIn('data-new="0"', tile("old-one"))

    def test_added_day_is_the_local_day(self):
        import os, time as _t
        from picker import render
        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/Chicago"; _t.tzset()
        try:
            self.assertEqual(render.added_day("2026-09-30T02:01:20Z"), "2026-09-29")   # 21:01 CDT
            self.assertEqual(render.added_day("2026-09-30T12:00:00Z"), "2026-09-30")
            self.assertEqual(render.added_day("2026-08-31"), "2026-08-31")            # older day-only value
            self.assertEqual(render.added_day("garbage-T"), "")
        finally:
            if old is None: os.environ.pop("TZ", None)
            else: os.environ["TZ"] = old
            _t.tzset()

    def test_twin_follows_its_source_in_the_same_section_and_is_never_new(self):
        import json
        from datetime import date
        from picker import render, state
        self.add_custom("nord-light", self.VARIANT)
        state.DATES_FILE.write_text(json.dumps({"nord-light": date.today().isoformat()}))
        page = render.render_page()
        grid = page[page.index('id="grid-official"'):]
        grid = grid[:grid.index("</details>")]
        nord = grid.index('data-theme="nord"')
        twin = grid.index('data-theme="nord-light"')
        self.assertLess(nord, twin)                                    # right after its source
        self.assertNotIn('data-theme="nord-light"', grid[:nord])
        tile = grid[twin:grid.index("</button>", twin)]
        self.assertIn('data-section="official"', tile)
        self.assertIn('data-twin-of="nord"', tile)
        self.assertIn('data-new="0"', tile)
        self.assertIn('data-form="light"', tile)                       # the sun/moon switch
        source = grid[nord:grid.index("</button>", nord)]
        self.assertIn('data-twin="nord-light"', source)
        self.assertNotIn('id="grid-variants"', page)


class RealPairs(SandboxCase):
    """Hand-made themes published in both modes pair like generated twins."""
    DARK = "/*\n * theme.park custom theme: X\n */\n:root {\n  --main-bg-color: #101418;\n}\n"
    LIGHT = "/*\n * theme.park custom theme: X\n */\n:root {\n  --main-bg-color: #f4f4f0;\n}\n"

    def test_counterpart_names(self):
        self.assertEqual(themes.mode_counterparts("gruvbox-light"),
                         ["gruvbox-dark", "gruvbox", "gruvbox-light-light", "gruvbox-light-dark"])
        self.assertIn("github-light-high-contrast", themes.mode_counterparts("github-dark-high-contrast"))
        self.assertNotIn("", themes.mode_counterparts("dark"))

    def test_pairs_and_which_leads(self):
        for name, css in [("gruvbox", self.DARK), ("gruvbox-light", self.LIGHT),
                          ("ayu-light", self.LIGHT), ("ayu-dark", self.DARK),
                          ("gh-dark-hc", self.DARK), ("gh-light-hc", self.LIGHT),
                          ("both-dark", self.DARK), ("both", self.DARK)]:   # same mode: no pair
            self.add_custom(name, css)
        self.assertEqual(themes.variant_pairs(), {"gruvbox": "gruvbox-light", "ayu-dark": "ayu-light",
                                                  "gh-dark-hc": "gh-light-hc"})

    def test_a_generated_twin_wins(self):
        self.add_custom("sol", self.DARK)
        self.add_custom("sol-light", Variants.VARIANT.replace("'nord'", "'sol'"))
        self.add_custom("sol-dark", self.LIGHT)      # hand-made, but sol already has its twin
        self.assertEqual(themes.variant_pairs(), {"sol": "sol-light"})

    def test_custom_themes_are_grouped(self):
        from picker import render
        from picker.editor import EDITOR_MARKER
        self.add_custom("inky", self.DARK)
        self.add_custom("paper", self.LIGHT)
        self.add_custom("wash", self.DARK.replace("#101418", "linear-gradient(135deg, #101418 0%, #203040 100%)"))
        self.add_custom("mine", f"/*\n * theme.park custom theme: Mine\n *\n * {EDITOR_MARKER} on 2026-01-01\n */\n"
                                + self.DARK.split("*/\n", 1)[1])
        self.add_custom("zeta", self.DARK)
        self.add_custom("zeta-light", self.LIGHT)          # a real pair: follows zeta, not listed itself
        groups = render.custom_groups(themes.variant_pairs())
        self.assertEqual(groups, {"custom-dark": ["inky", "zeta"], "custom-light": ["paper"],
                                  "custom-gradient": ["wash"], "custom-editor": ["mine"]})

    def test_real_twin_follows_its_lead_once(self):
        from picker import render
        self.add_custom("zeta-light", self.LIGHT)
        self.add_custom("alpha", self.DARK)
        self.add_custom("zeta", self.DARK)
        page = render.render_page()
        grid = page[page.index('id="grid-custom-dark"'):]
        grid = grid[:grid.index("</details>")]
        self.assertEqual(grid.count('data-theme="zeta-light"'), 1)
        self.assertLess(grid.index('data-theme="zeta"'), grid.index('data-theme="zeta-light"'))
        self.assertIn('data-twin-of="zeta"', grid)
        self.assertIn('data-twin="zeta-light"', grid)

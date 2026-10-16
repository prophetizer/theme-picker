import re

from picker import colour as c, config, dashboards
from tests.support import SandboxCase, fixture

TRIPLET = re.compile(r"--color-(\d+): (\d+) (\d+) (\d+) !important;")


class Homepage(SandboxCase):
    def ramp_lums(self, css):
        steps = {int(k): (int(r), int(g), int(b)) for k, r, g, b in TRIPLET.findall(css)}
        self.assertEqual(sorted(steps), [50, 100, 200, 300, 400, 500, 600, 700, 800, 900])
        return [c.lum(steps[k]) for k in sorted(steps)]

    def test_dark_theme_ramp_runs_light_to_dark_from_its_own_colours(self):
        self.add_custom("hc", fixture("high_contrast.css"))
        css = dashboards.homepage_css("hc")
        lums = self.ramp_lums(css)
        self.assertEqual(lums, sorted(lums, reverse=True))
        self.assertIn("--color-900: 0 0 0 !important;", css)              # the theme's page
        self.assertIn("--color-200: 255 255 255 !important;", css)        # its text
        self.assertIn("--color-logo-start: 255 255 255 !important;", css) # its button
        self.assertTrue(css.startswith("/* Homepage dressed in the theme picker's live theme: hc */"))

    def test_light_theme_lands_at_the_light_end(self):
        self.add_custom("lc", fixture("low_contrast.css"))
        css = dashboards.homepage_css("lc")
        lums = self.ramp_lums(css)
        self.assertEqual(lums, sorted(lums, reverse=True))
        self.assertIn("--color-50: 255 255 255 !important;", css)          # its white panel, lightest
        self.assertIn("--color-100: 244 244 244 !important;", css)         # then its page

    def test_theme_without_css_still_renders(self):
        self.ramp_lums(dashboards.homepage_css("nord"))                    # editor fallbacks


class Glance(SandboxCase):
    def test_dark_theme(self):
        self.add_custom("hc", fixture("high_contrast.css"))
        css = dashboards.glance_css("hc")
        self.assertIn("--bgl: 0% !important;", css)
        self.assertIn("--color-primary: hsl(60, 100%, 50%) !important;", css)   # its link, #ffff00
        self.assertNotIn("--scheme", css)

    def test_light_theme_switches_glance_to_light(self):
        self.add_custom("lc", fixture("low_contrast.css"))
        css = dashboards.glance_css("lc")
        self.assertIn("--scheme: 100% - !important;", css)
        # Its #999 text reads at 7:1 on neither surface, so Glance gets the
        # one with the best contrast (the white panel, not the #f4f4f4 page)
        # and the text only as dark as 4.5:1 needs.
        self.assertIn("--bgl: 100% !important;", css)
        self.assertIn("--color-text-base: #767676 !important;", css)


class GlanceGradients(SandboxCase):
    BOREAL = """:root {
  --main-bg-color: radial-gradient(ellipse at 50% 115%, #4f9d69 0%, #1f4034 45%, #0e1a17 85%) center center/cover no-repeat fixed;
  --modal-bg-color: linear-gradient(-90deg, #1c332b 0%, #0e1a17 100%) center center/cover no-repeat fixed;
  --text: #dfe7e1;
  --text-muted: #9db3a6;
  --link-color: #8fd9c1;
}
"""

    def test_a_glow_stop_is_not_the_background(self):
        # Boreal's first stop is its bright glow; Glance used to take it, at
        # 46% lightness, under text it fixes at 58%. The mid stop reads.
        self.add_custom("boreal", self.BOREAL)
        self.assertEqual(c.to_hex(dashboards.glance_background("boreal")), "#1f4034")
        css = dashboards.glance_css("boreal")
        self.assertIn("--bgl: 19% !important;", css)
        self.assertIn("--color-text-base: #dfe7e1 !important;", css)            # the theme's own text
        self.assertIn("--color-text-base-muted: #9db3a6 !important;", css)

    def test_a_bright_page_falls_back_to_its_panels(self):
        self.add_custom("vivid", self.BOREAL.replace("#4f9d69 0%, #1f4034 45%, #0e1a17 85%", "#f09819 0%, #edde5d 100%"))
        bg = dashboards.glance_background("vivid")
        self.assertIn(c.to_hex(bg), ("#1c332b", "#0e1a17"))

    def test_every_text_role_reads(self):
        self.add_custom("faint", self.BOREAL.replace("--text-muted: #9db3a6", "--text-muted: #3a5a48"))
        css = dashboards.glance_css("faint")
        bg = dashboards.glance_background("faint")
        for role, need in (("--color-text-base", 4.5), ("--color-text-base-muted", 4.5),
                           ("--color-text-subdue", 3)):
            got = c.hex_rgb(re.search(role + r": (#[0-9a-f]{6})", css).group(1))
            self.assertGreaterEqual(c.contrast(got, bg), need, role)


class HomepageHomarrGradients(SandboxCase):
    def test_a_glow_stop_is_replaced_by_the_readable_one(self):
        self.add_custom("boreal", GlanceGradients.BOREAL)
        home = dashboards.homepage_css("boreal")
        self.assertIn(": 31 64 52 !important;", home)                  # the page, #1f4034 (by lightness, not 900)
        self.assertNotIn(": 79 157 105 !important;", home)             # the glow, #4f9d69
        css = dashboards.homarr_css("boreal")
        self.assertIn("--mantine-color-body: rgb(31, 64, 52) !important;", css)
        self.assertIn("background: rgb(31, 64, 52) !important;", css)                       # solid, not the glow

    def test_a_readable_theme_is_untouched(self):
        self.add_custom("hc", fixture("high_contrast.css"))
        self.assertEqual(dashboards._readable_vars("hc"), dashboards._vars("hc"))


class Route(SandboxCase):
    def test_served_for_the_live_theme(self):
        import http.client, threading
        from http.server import ThreadingHTTPServer
        from picker import handler
        self.add_custom("hc", fixture("high_contrast.css"))
        config.CONFIG_FILE.write_text("CURRENT_THEME=hc\n")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        for name, marker in (("homepage.css", b"--color-900: 0 0 0"), ("glance.css", b"--bgl: 0%")):
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            conn.request("GET", f"/dashboards/{name}")
            r = conn.getresponse(); body = r.read(); conn.close()
            self.assertEqual((r.status, r.getheader("Content-Type"), r.getheader("Cache-Control")),
                             (200, "text/css; charset=utf-8", "no-store, max-age=0"))
            self.assertIn(b"live theme: hc", body)
            self.assertIn(marker, body)
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", "/dashboards/other.css")
        self.assertEqual(conn.getresponse().status, 404); conn.close()


class Homarr(SandboxCase):
    def test_mantine_variables_from_the_theme(self):
        self.add_custom("hc", fixture("high_contrast.css"))
        css = dashboards.homarr_css("hc")
        for want in ("--mantine-color-body: rgb(0, 0, 0) !important;",
                     "--mantine-color-text: rgb(255, 255, 255) !important;",
                     "--mantine-color-anchor: rgb(255, 255, 0) !important;",
                     "--mantine-primary-color-filled: rgb(255, 255, 255) !important;",
                     "--mantine-primary-color-contrast: rgb(0, 0, 0) !important;",
                     "--mantine-color-dark-7: rgb(0, 0, 0) !important;",
                     "html, body {\n  background: rgb(0, 0, 0) !important;"):
            self.assertIn(want, css)
        self.assertEqual(len(re.findall(r"--mantine-color-dark-\d:", css)), 10)
        # Tiles use --mantine-color-white in light mode, so they are set directly,
        # keeping Homarr's own per-board opacity.
        self.assertIn('[class*="item-module__"][class*="__itemCard"]', css)
        self.assertIn("--background-color: rgba(0, 0, 0, var(--opacity, 1)) !important;", css)

    def test_gradient_theme_paints_a_gradient_body(self):
        self.add_custom("bb", fixture("blackberry_like.css"))
        self.assertIn("background: linear-gradient(160deg,", dashboards.homarr_css("bb"))

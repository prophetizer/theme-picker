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
        self.assertIn("--bgl: 96% !important;", css)


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

"""The coverage check: the theme link must be in the page AND the file it
points at must exist (theme.park serves no per-theme files for deprecated
apps -- Grafana's link 404'd while coverage said "ok")."""

import io
import urllib.error
from unittest import mock

from picker import config, coverage
from tests.support import SandboxCase

PAGE = '<html><head><link rel="stylesheet" href="https://tp.example/css/base/{app}/{theme}.css"></head></html>'


class Coverage(SandboxCase):
    def setUp(self):
        super().setUp()
        (self.dir / "apps.yml").write_text("apps:\n  - {name: sonarr, theme_app: sonarr}\n"
                                           "  - {name: grafana, theme_app: grafana}\n")
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")
        self.missing = set()          # stylesheet URLs that 404
        self.requested = []
        for obj, name, value in [(config, "DOMAIN", "example.com")]:
            p = mock.patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(config, "base_url", return_value="https://tp.example"); p.start(); self.addCleanup(p.stop)

    def urlopen(self, req, timeout=None):
        url = req.full_url
        self.requested.append(url)
        if url in self.missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"not found"))
        if "/css/base/" in url:
            body = b"@import url(...);"
        else:
            app = url.split("//")[1].split(".")[0]
            body = PAGE.format(app=app, theme="nord").encode()
        resp = mock.MagicMock(status=200)
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        return resp

    def check(self):
        with mock.patch.object(coverage.urllib.request, "urlopen", side_effect=self.urlopen):
            return {r["app"]: r for r in coverage.check_coverage()["results"]}

    def test_link_and_file_present_is_ok(self):
        r = self.check()
        self.assertEqual((r["sonarr"]["state"], r["grafana"]["state"]), ("ok", "ok"))

    def test_link_to_a_missing_file_is_broken(self):
        self.missing.add("https://tp.example/css/base/grafana/nord.css")
        r = self.check()
        self.assertEqual(r["sonarr"]["state"], "ok")
        self.assertEqual(r["grafana"]["state"], "broken")
        self.assertIn("/css/base/grafana/nord.css answers 404", r["grafana"]["detail"])

    def test_stylesheet_host_is_ours_not_the_page_s(self):
        self.check()
        sheets = [u for u in self.requested if "/css/base/" in u]
        self.assertTrue(sheets)
        self.assertTrue(all(u.startswith("https://tp.example/") for u in sheets))

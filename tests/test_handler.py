"""The HTTP layer, against a real server on an ephemeral port. subprocess.run
is always mocked: nothing here can apply a theme."""

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from picker import config, handler, render, state
from tests.support import SandboxCase


class ServerCase(SandboxCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        self.run = self.backend        # what was applied (a recorder -- see support.FakeBackend)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            r = conn.getresponse()
            return r.status, r.getheader("Content-Type"), r.read()
        finally:
            conn.close()

    def post_json(self, path, data, ctype="application/json"):
        return self.request("POST", path, json.dumps(data).encode(), {"Content-Type": ctype})

    def set_theme(self, theme, accept="application/json"):
        from urllib.parse import quote
        return self.request("POST", "/set-theme", f"theme={quote(theme)}".encode(),
                            {"Content-Type": "application/x-www-form-urlencoded", "Accept": accept})


class SetTheme(ServerCase):
    def test_unknown_theme_never_reaches_subprocess(self):
        for bad in ("zzz-nope", "nord; rm -rf /", "$(id)", "../nord", "nord\n", "-x", ""):
            with self.subTest(theme=bad):
                status, _, body = self.set_theme(bad)
                self.assertEqual(status, 400)
                self.assertFalse(json.loads(body)["ok"])
        self.assertEqual(self.backend.applied, [])

    def test_known_theme_reaches_the_backend(self):
        status, _, body = self.set_theme("nord")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["message"], "Theme set to 'nord'.")
        self.assertEqual(self.backend.applied, ["nord"])
        self.assertEqual(state.read_history()[-1]["theme"], "nord")

    def test_backend_failure_is_reported(self):
        self.backend.fail = "set-theme.sh failed: boom"
        status, _, body = self.set_theme("nord")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body)["message"], "set-theme.sh failed: boom")
        self.assertEqual(state.read_history(), [])

    def test_without_javascript_the_page_is_re_rendered(self):
        status, ctype, body = self.set_theme("zzz-nope", accept="text/html")
        self.assertEqual((status, ctype), (400, "text/html; charset=utf-8"))
        self.assertIn(b"Rejected: &#x27;zzz-nope&#x27; is not a known theme.", body)


class CsrfGuard(ServerCase):
    def test_state_changing_endpoints_need_a_json_content_type(self):
        for path in ("/api/favourite", "/api/override", "/api/editor/save"):
            for ctype in ("application/x-www-form-urlencoded", "text/plain", "multipart/form-data"):
                with self.subTest(path=path, ctype=ctype):
                    status, _, body = self.post_json(path, {"theme": "nord", "on": True}, ctype)
                    self.assertEqual(status, 415)
                    self.assertEqual(json.loads(body)["message"], "expected a JSON body")
        self.assertEqual(state.read_favourites(), [])

    def test_json_content_type_is_accepted(self):
        status, _, body = self.post_json("/api/favourite", {"theme": "nord", "on": True})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["favourites"], ["nord"])

    def test_malformed_json_is_refused(self):
        status, _, _ = self.request("POST", "/api/favourite", b"{nope",
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 415)


class CrossSite(ServerCase):
    """Found by the pre-publish security scan: both of these got through."""

    def test_safelisted_content_type_with_json_parameter_is_refused(self):
        # text/plain with a parameter is CORS-safelisted, so a cross-site page
        # can send it without a preflight; a substring check let it through.
        for ctype in ("text/plain; x=application/json", "text/plain;application/json",
                      "application/x-www-form-urlencoded; a=application/json", "application/jsonx"):
            with self.subTest(ctype=ctype):
                status, _, _ = self.post_json("/api/favourite", {"theme": "nord", "on": True}, ctype)
                self.assertEqual(status, 415)
        self.assertEqual(state.read_favourites(), [])

    def test_json_with_charset_still_works(self):
        status, _, _ = self.post_json("/api/favourite", {"theme": "nord", "on": True},
                                      "Application/JSON; charset=utf-8")
        self.assertEqual(status, 200)

    def cross(self, path, headers, body=b"theme=nord"):
        base = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        return self.request("POST", path, body, {**base, **headers})

    def test_cross_site_form_post_cannot_set_the_theme(self):
        for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                        {"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"}):
            with self.subTest(headers=headers):
                status, _, body = self.cross("/set-theme", headers)
                self.assertEqual((status, json.loads(body)["message"]), (403, "cross-site request refused"))
        self.assertEqual(self.backend.applied, [])

    def test_cross_site_api_calls_are_refused(self):
        for path in ("/api/favourite", "/api/override", "/api/editor/save", "/api/schedule"):
            with self.subTest(path=path):
                status, _, _ = self.request("POST", path, b'{"theme": "nord", "on": true}',
                                            {"Content-Type": "application/json",
                                             "Origin": "https://evil.example"})
                self.assertEqual(status, 403)
        self.assertEqual(state.read_favourites(), [])

    def test_same_origin_and_non_browser_requests_work(self):
        host = f"127.0.0.1:{self.server.server_address[1]}"
        for headers in ({}, {"Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"},
                        {"Origin": "https://picker.example.test", "Host": "picker.example.test"},
                        {"Origin": "https://picker.example.test", "X-Forwarded-Host": "picker.example.test"},
                        {"Sec-Fetch-Site": "none"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.cross("/set-theme", headers)[0], 200)

    def test_html_form_gets_an_html_refusal(self):
        status, ctype, body = self.request("POST", "/set-theme", b"theme=nord",
                                           {"Content-Type": "application/x-www-form-urlencoded",
                                            "Origin": "https://evil.example"})
        self.assertEqual((status, ctype, body), (403, "text/html; charset=utf-8", b"Cross-site request refused"))


class BodyLimits(ServerCase):
    def raw_post(self, path, length, body=b"", ctype="application/x-www-form-urlencoded"):
        import socket
        with socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=5) as sock:
            sock.sendall(f"POST {path} HTTP/1.1\r\nHost: x\r\nAccept: application/json\r\n"
                         f"Content-Type: {ctype}\r\nContent-Length: {length}\r\n\r\n".encode() + body)
            reply = b""
            while chunk := sock.recv(4096):        # read to EOF: hanging up mid-reply made
                reply += chunk                     # the server log a (harmless) reset
            return int(reply.split()[1])

    def test_set_theme_refuses_bad_or_huge_lengths_without_reading(self):
        for length in ("-1", "abc", "4097", "999999999"):
            with self.subTest(length=length):
                self.assertEqual(self.raw_post("/set-theme", length), 413)
        self.assertEqual(self.backend.applied, [])

    def test_json_endpoints_refuse_bad_or_huge_lengths(self):
        for length in ("-1", "abc", "20001"):
            with self.subTest(length=length):
                self.assertEqual(self.raw_post("/api/favourite", length, ctype="application/json"), 415)

    def test_normal_bodies_still_work(self):
        self.assertEqual(self.raw_post("/set-theme", 10, b"theme=nord"), 200)


class NotifyLink(ServerCase):
    def test_link_comes_from_config_not_headers(self):
        from picker import ntfy
        with mock.patch.object(ntfy, "schedule_notify") as notify, \
             mock.patch.object(config, "PICKER_URL", "https://picker.example.test/"):
            self.request("POST", "/set-theme", b"theme=nord",
                         {"Content-Type": "application/x-www-form-urlencoded",
                          "X-Forwarded-Host": "evil.example", "Host": "evil.example"})
        self.assertEqual(notify.call_args.args[2], "https://picker.example.test/")


class CoverageCache(SandboxCase):
    def test_shared_for_a_while_but_fresh_after_a_change(self):
        from picker import coverage
        calls = []
        with mock.patch.object(coverage, "_CACHE", {}), \
             mock.patch.object(coverage, "check_coverage", side_effect=lambda: calls.append(1) or {"n": len(calls)}):
            config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")
            self.assertEqual(coverage.cached_coverage(), {"n": 1})
            self.assertEqual(coverage.cached_coverage(), {"n": 1})          # shared
            config.CONFIG_FILE.write_text("CURRENT_THEME=dracula\n")
            self.assertEqual(coverage.cached_coverage(), {"n": 2})          # theme changed: fresh
            with mock.patch.object(coverage.time, "monotonic", return_value=10 ** 9):
                self.assertEqual(coverage.cached_coverage(), {"n": 3})      # expired


class SecurityHeaders(ServerCase):
    def test_on_every_response(self):
        for method, path in (("GET", "/"), ("GET", "/api/current"), ("GET", "/nope"),
                             ("GET", "/metrics"), ("POST", "/set-theme")):
            with self.subTest(path=path):
                conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
                conn.request(method, path, body=b"" if method == "POST" else None)
                r = conn.getresponse(); r.read(); conn.close()
                for k, v in handler.SECURITY_HEADERS.items():
                    self.assertEqual(r.getheader(k), v)
                csp = r.getheader("Content-Security-Policy")
                for part in ("script-src 'self';", "frame-ancestors 'none'", "object-src 'none'",
                             "style-src-attr 'unsafe-inline'", "base-uri 'none'"):
                    self.assertIn(part, csp)
                self.assertNotIn("unsafe-eval", csp)
                self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)

    def test_csp_allows_theme_park_for_styles(self):
        with mock.patch.object(config, "THEME_PARK_URL", "https://tp.example.test/"):
            csp = handler.content_security_policy()
        self.assertIn("style-src 'self' https://tp.example.test;", csp)
        self.assertIn("img-src 'self' https://tp.example.test data: blob:;", csp)


class Routes(ServerCase):
    def test_page(self):
        status, ctype, body = self.request("GET", "/")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        page = body.decode()
        self.assertIn("<title>Theme Picker</title>", page)
        self.assertIn('data-theme="nord"', page)
        for sect in ("official", "community", "custom"):                        # collapsible, open by default
            self.assertIn(f'<details class="sect" data-sect="{sect}" open><summary><h2>', page)
        self.assertIn(f'<script src="/static/app.js?v={render.VERSION["app.js"]}"></script>', page)
        self.assertIn(f'<link rel="stylesheet" href="/static/style.css?v={render.VERSION["style.css"]}">', page)
        self.assertIn(f'<link rel="icon" type="image/svg+xml" href="/static/icon.svg?v={render.VERSION["icon.svg"]}">', page)
        self.assertIn('<input type="file" id="ed-image" accept="image/*">', page)   # theme from an image
        self.assertNotIn("<script>", page)                           # nothing inline for the CSP to allow
        self.assertNotIn("<style>", page)

    def test_static_files(self):
        for name, ctype, marker in (("app.js", "text/javascript; charset=utf-8", b"const tiles = $$('.theme-btn');"),
                                    ("style.css", "text/css; charset=utf-8", b"body { font-family: system-ui"),
                                    ("icon.svg", "image/svg+xml", b"<title>Theme Picker</title>")):
            with self.subTest(name=name):
                status, got, body = self.request("GET", f"/static/{name}?v=anything")
                self.assertEqual((status, got), (200, ctype))
                self.assertIn(marker, body)
        for bad in ("/static/page.html", "/static/../server.py", "/static/", "/static/x.js"):
            with self.subTest(path=bad):
                self.assertEqual(self.request("GET", bad)[0], 404)

    def test_shots_over_http(self):
        thumbs = self.dir / "screenshots" / "thumbs"
        thumbs.mkdir(parents=True)
        (thumbs / "dozzle_nord.jpg").write_bytes(b"jpg")
        (self.dir / "config.env").write_text("secret")
        status, ctype, body = self.request("GET", "/shots/thumb/dozzle_nord.jpg")
        self.assertEqual((status, ctype, body), (200, "image/jpeg", b"jpg"))
        for path in ("/shots/thumb/../../config.env", "/shots/thumb/..%2f..%2fconfig.env",
                     "/shots/thumb/dozzle_nord.png", "/shots/nope/dozzle_nord.jpg"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(body, b"Not found")

    def test_theme_vars_allowlist(self):
        status, _, body = self.request("GET", "/api/theme-vars?theme=../etc/passwd")
        self.assertEqual((status, json.loads(body)), (400, {"error": "unknown theme"}))
        status, _, body = self.request("GET", "/api/theme-vars?theme=nord")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["page_bg"], "#1e1e1e")    # no CSS offline: defaults

    def test_current_and_editor_status(self):
        status, _, body = self.request("GET", "/api/current")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["theme"], "unknown")
        status, _, body = self.request("GET", "/api/editor/status?name=x")
        self.assertEqual(json.loads(body), {"state": "unknown"})

    def test_metrics(self):
        status, ctype, body = self.request("GET", "/metrics")
        self.assertEqual((status, ctype), (200, "text/plain; version=0.0.4; charset=utf-8"))
        self.assertIn(b'theme_picker_theme_info{theme="unknown"', body)

    def test_unknown_routes(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("POST", "/nope")[0], 404)
        self.assertEqual(self.post_json("/api/nope", {})[0], 404)


class Template(unittest.TestCase):
    def test_every_placeholder_is_filled(self):
        import string
        fields = {f for _, f, _, _ in string.Formatter().parse(render.PAGE_TEMPLATE) if f}
        self.assertEqual(fields, {"theme_link", "style_v", "icon_v", "active", "history", "app_opts", "fams",
                                  "grid_official", "grid_community", "grid_custom", "live_swatch", "msg_hidden",
                                  "msg_text", "apps", "stats", "base_opts", "script_v", "undo",
                                  "schedule"})


if __name__ == "__main__":
    unittest.main()

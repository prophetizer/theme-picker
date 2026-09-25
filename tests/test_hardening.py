"""Regressions for the 2026-09-24 security audit (Phase 1)."""

import http.client
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from picker import backend, config, coverage, editor, handler, schedule, shots, themes
from tests.support import SandboxCase
from tests.test_handler import ServerCase


class TrailingNewline(unittest.TestCase):
    """`$` also matches before a final newline; every validator must not."""

    def test_validators_refuse_a_trailing_newline(self):
        cases = [(config.SAFE_NAME, "nord"), (config._APP, "sonarr"), (config._HOST, "sonarr"),
                 (config._URL, "https://example.com"), (editor.NEWNAME, "nord"),
                 (editor.HEX6, "#112233"), (editor.TITLE, "Nord"), (schedule._HHMM, "07:30"),
                 (shots.SHOT_NAME, "sonarr_nord")]
        for rx, good in cases:
            with self.subTest(pattern=rx.pattern):
                self.assertTrue(rx.match(good))
                self.assertIsNone(rx.match(good + "\n"))

    def test_digits_are_ascii(self):
        spinner = "invert(50%) sepia(50%) saturate(500%) hue-rotate(100deg) brightness(90%) contrast(90%)"
        self.assertTrue(editor.SPINNER.match(spinner))
        self.assertIsNone(editor.SPINNER.match(spinner.replace("50%", "٥٠%", 1)))
        self.assertIsNone(schedule._HHMM.match("٠٧:30"))


class EditorName(SandboxCase):
    def test_name_with_newline_is_not_queued(self):
        ok, msg = editor.editor_save({"name": "nord\n", "title": "Nord"})
        self.assertFalse(ok)
        self.assertFalse((self.dir / "editor-queue").exists() and any((self.dir / "editor-queue").iterdir()))


class CurrentTheme(SandboxCase):
    def test_unsafe_value_reads_as_unknown(self):
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord*/ body{display:none} /*\n")
        self.assertEqual(themes.current_theme(), "unknown")
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")
        self.assertEqual(themes.current_theme(), "nord")


class StateFileLinks(unittest.TestCase):
    """The capture calls write_current() on the host; the state file sits in a
    directory the container can write."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="picker-test-"))
        self.addCleanup(lambda: [p.unlink() for p in self.dir.iterdir()] and self.dir.rmdir())
        self.secret = self.dir / "secret"
        self.secret.write_text("TOKEN=abc123\n")
        self.state = self.dir / "current-theme.env"
        self.state.symlink_to(self.secret)

    def test_symlinked_state_is_not_read(self):
        self.assertEqual(backend.read_current(self.state), "")

    def test_write_current_does_not_copy_the_link_target(self):
        backend.write_current(self.state, "nord")
        self.assertFalse(self.state.is_symlink())
        self.assertEqual(self.state.read_text(), "CURRENT_THEME=nord\n")
        self.assertEqual(self.secret.read_text(), "TOKEN=abc123\n")

    def test_fifo_is_not_waited_on(self):
        fifo = self.dir / "fifo"
        os.mkfifo(fifo)
        self.assertEqual(backend.read_current(fifo), "")


class OutputFile(unittest.TestCase):
    def test_must_be_yaml(self):
        for bad in ("~/.bashrc", "/etc/cron.d/x", "/tmp/themes.yml.sh"):
            with self.subTest(path=bad), mock.patch.dict(config.SETTINGS, {"backend.output_file": bad}):
                with self.assertRaises(ValueError):
                    config.output_file()
        with mock.patch.dict(config.SETTINGS, {"backend.output_file": "/x/dynamic/themes.yml"}):
            self.assertEqual(config.output_file(), Path("/x/dynamic/themes.yml"))

    def test_backend_reports_it_as_an_apply_error(self):
        with mock.patch.dict(config.SETTINGS, {"backend.type": "traefik-file",
                                               "backend.output_file": "/tmp/x.sh"}):
            with self.assertRaises(backend.ApplyError):
                backend.get()


class CoverageHost(SandboxCase):
    def test_non_hostname_is_not_fetched(self):
        (self.dir / "apps.yml").write_text(
            "apps:\n  - {name: evil, theme_app: sonarr, host: 'x@attacker.example/#'}\n")
        with mock.patch("urllib.request.urlopen") as urlopen:
            result = coverage.check_coverage()
        urlopen.assert_not_called()
        self.assertIn("not a plain hostname", str(result))


class Http(ServerCase):
    def raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            r = conn.getresponse()
            r.read()
            return r
        finally:
            conn.close()

    def test_non_object_json_gets_an_answer(self):
        for body in (b"[]", b'"x"', b"3", b"null"):
            for path in ("/api/favourite", "/api/schedule", "/api/override", "/api/editor/save"):
                with self.subTest(path=path, body=body):
                    r = self.raw("POST", path, body, {"Content-Type": "application/json"})
                    self.assertEqual(r.status, 415)

    def test_pages_and_api_are_not_cached(self):
        for path in ("/", "/api/current"):
            with self.subTest(path=path):
                self.assertEqual(self.raw("GET", path).getheader("Cache-Control"), "no-store")

    def test_routes_keep_their_own_caching(self):
        r = self.raw("GET", "/static/style.css")
        self.assertIn("immutable", r.getheader("Cache-Control"))
        self.assertEqual(r.headers.get_all("Cache-Control"), [r.getheader("Cache-Control")])

    def test_server_header_does_not_name_python(self):
        self.assertNotIn("Python", self.raw("GET", "/").getheader("Server"))

    def test_idle_connections_time_out(self):
        self.assertEqual(handler.Handler.timeout, 30)


if __name__ == "__main__":
    unittest.main()

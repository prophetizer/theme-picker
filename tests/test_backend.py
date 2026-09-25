import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from picker import backend
from picker.backend import ApplyError, Script, TraefikFile

APPS = [{"name": "sonarr", "theme_app": "sonarr", "host": "sonarr", "addons": []},
        {"name": "forgejo", "theme_app": "gitea", "host": "forgejo", "addons": ["some-addon"]}]


class TempDir(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.d)


class TraefikFileBackend(TempDir):
    def make(self, pins=None, apps=APPS, base="https://tp.example.test"):
        self.pins = dict(pins or {})
        return TraefikFile(output_file=self.d / "dyn" / "themes.yml", state_file=self.d / "current-theme.env",
                           default_theme="dark", apps=lambda: apps, pins=lambda: self.pins,
                           base_url=lambda: base)

    def written(self):
        return yaml.safe_load((self.d / "dyn" / "themes.yml").read_text())

    def test_apply_writes_one_middleware_per_app_and_the_state(self):
        self.make(pins={"forgejo": "dracula"}).apply("nord")
        self.assertEqual(self.written(), {"http": {"middlewares": {
            "sonarr-theme": {"plugin": {"themepark": {"app": "sonarr", "theme": "nord",
                                                      "baseUrl": "https://tp.example.test"}}},
            "forgejo-theme": {"plugin": {"themepark": {"app": "gitea", "theme": "dracula",
                                                       "baseUrl": "https://tp.example.test",
                                                       "addons": ["some-addon"]}}}}}})
        self.assertEqual(backend.read_current(self.d / "current-theme.env"), "nord")
        self.assertEqual([p.name for p in (self.d / "dyn").iterdir()], ["themes.yml"])   # no temp left

    def test_ignore_pins_for_the_capture(self):
        self.make(pins={"forgejo": "dracula"}).apply("nord", ignore_pins=True)
        mws = self.written()["http"]["middlewares"]
        self.assertEqual(mws["forgejo-theme"]["plugin"]["themepark"]["theme"], "nord")

    def test_set_pins_keeps_the_live_theme(self):
        b = self.make()
        b.set_pins()                                          # nothing picked yet: default
        self.assertEqual(self.written()["http"]["middlewares"]["sonarr-theme"]["plugin"]["themepark"]["theme"], "dark")
        b.apply("nord")
        self.pins["sonarr"] = "dracula"
        b.set_pins()
        mws = self.written()["http"]["middlewares"]
        self.assertEqual([m["plugin"]["themepark"]["theme"] for m in mws.values()], ["dracula", "nord"])

    def test_state_file_keeps_its_other_lines(self):
        state = self.d / "current-theme.env"
        state.write_text("# comment\nCURRENT_THEME=old\nOTHER=1\n")
        self.make().apply("nord")
        self.assertEqual(state.read_text(), "# comment\nCURRENT_THEME=nord\nOTHER=1\n")
        state.write_text("# no theme line yet\n")
        self.make().apply("dracula")
        self.assertEqual(state.read_text(), "# no theme line yet\nCURRENT_THEME=dracula\n")

    def test_refuses_what_it_cannot_write_safely(self):
        for b, why in ((self.make(base=""), "no theme-park URL"), (self.make(apps=[]), "no themed apps")):
            with self.subTest(why):
                with self.assertRaisesRegex(ApplyError, why):
                    b.apply("nord")
        for bad in ("nord\n  evil: 1", "../x", "", "a b"):
            with self.subTest(theme=bad):
                with self.assertRaises(ApplyError):
                    self.make().apply(bad)
        with self.assertRaises(ApplyError):
            self.make(pins={"sonarr": "x\ny: 1"}).apply("nord")
        self.assertFalse((self.d / "current-theme.env").exists())         # failures leave state alone
        self.assertFalse((self.d / "dyn" / "themes.yml").exists())

    def test_write_failure_is_an_apply_error(self):
        (self.d / "dyn").write_text("a file where the directory should be")
        with self.assertRaises(ApplyError):
            self.make().apply("nord")


class ScriptBackend(TempDir):
    def run_with(self, returncode=0, stderr=""):
        done = subprocess.CompletedProcess([], returncode, "", stderr)
        return mock.patch.object(backend.subprocess, "run", return_value=done)

    def test_apply_uses_an_argument_list_and_passes_the_pin_switch(self):
        b = Script(self.d / "set-theme.sh", self.d / "gen.py", self.d)
        with self.run_with() as run:
            b.apply("nord", ignore_pins=True)
        (argv,), kw = run.call_args
        self.assertEqual(argv, ["/bin/bash", str(self.d / "set-theme.sh"), "nord"])
        self.assertNotIn("shell", kw)
        self.assertEqual(kw["env"]["THEME_IGNORE_OVERRIDES"], "1")

    def test_failures_and_bad_names(self):
        b = Script(self.d / "set-theme.sh", self.d / "gen.py", self.d)
        with self.run_with(1, "boom"):
            with self.assertRaisesRegex(ApplyError, "^set-theme.sh failed: boom$"):
                b.apply("nord")
            with self.assertRaisesRegex(ApplyError, "^generator failed: boom$"):
                b.set_pins()
        with self.run_with() as run:
            with self.assertRaises(ApplyError):
                b.apply("$(id)")
            run.assert_not_called()


class Selection(unittest.TestCase):
    def test_get_follows_backend_type(self):
        from picker import config
        with mock.patch.dict(config.SETTINGS, {"backend.type": "script"}):
            self.assertIsInstance(backend.get(), Script)
        with mock.patch.dict(config.SETTINGS, {"backend.type": "traefik-file"}):
            self.assertIsInstance(backend.get(), TraefikFile)

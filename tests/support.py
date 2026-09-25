"""Shared fixture: every test gets its own empty theme-switcher directory."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from picker import backend, config, editor, metrics, schedule, shots, state, themes

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text()


class FakeBackend:
    """Records what would be applied; updates current-theme.env the way a
    real backend does, so the rest of the picker sees the change."""
    name = "fake"

    def __init__(self):
        self.applied, self.pin_writes, self.fail = [], 0, None

    def apply(self, theme, ignore_pins=False):
        if self.fail:
            raise backend.ApplyError(self.fail)
        self.applied.append(theme)
        backend.write_current(config.CONFIG_FILE, theme)

    def set_pins(self):
        if self.fail:
            raise backend.ApplyError(self.fail)
        self.pin_writes += 1


class SandboxCase(unittest.TestCase):
    """Repoints every path the picker reads or writes at a fresh temp dir and
    empties the per-process caches, so tests cannot see each other's state
    or the live homelab's. No config.env means no theme-park base URL, so
    nothing goes to the network and the fallback theme lists are used."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="picker-test-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        d = self.dir
        self.custom_dir = d / "themes-src" / "themes"
        self.custom_dir.mkdir(parents=True)
        for obj, name, value in [
            (config, "THEME_DIR", d), (config, "CONFIG_FILE", d / "current-theme.env"),
            (config, "SETTINGS_FILE", d / "config.env"), (config, "SET_THEME_SCRIPT", d / "set-theme.sh"),
            (themes, "CUSTOM_THEMES_DIR", self.custom_dir),
            (state, "APPS_FILE", d / "apps.yml"),
            (state, "OVERRIDES_FILE", d / "theme-overrides.json"),
            (state, "FAVS_FILE", d / "theme-favourites.json"),
            (state, "DATES_FILE", d / "theme-dates.json"),
            (state, "HISTORY_FILE", d / "theme-history.json"),
            (shots, "SHOT_DIR", d / "screenshots"),
            (editor, "QUEUE_DIR", d / "editor-queue"), (editor, "EDITOR_STATUS", d / "editor-status.json"),
            (schedule, "SCHEDULE_FILE", d / "theme-schedule.json"),
            (themes, "_MANIFEST", {}), (themes, "_CSS_CACHE", {}), (themes, "_PALETTE_CACHE", {}),
            (metrics, "_METRICS_CACHE", {}),
        ]:
            p = mock.patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        # No test may write a real proxy config: every backend.get() returns
        # a recorder. Backend tests construct the real classes themselves.
        self.backend = FakeBackend()
        p = mock.patch.object(backend, "get", return_value=self.backend)
        p.start()
        self.addCleanup(p.stop)

    def add_custom(self, name, css):
        (self.custom_dir / f"{name}.css").write_text(css)

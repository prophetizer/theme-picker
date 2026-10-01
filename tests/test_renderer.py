"""The isolated setup: backend.type "state" records the change, and
picker.renderer -- in its own container -- is the only writer of Traefik's
themes.yml."""

import json
from unittest import mock

import yaml

from picker import backend, config, renderer, state
from picker.backend import StateOnly, TraefikFile
from tests.support import SandboxCase

APPS_YML = """apps:
  - name: sonarr
    theme_app: sonarr
  - name: forgejo
    theme_app: gitea
    addons: [some-addon]
"""


class Renderer(SandboxCase):
    def setUp(self):
        super().setUp()
        state.APPS_FILE.write_text(APPS_YML)
        self.out = self.dir / "dynamic" / "themes.yml"
        config.SETTINGS_FILE.write_text(f"BASE_URL=https://tp.example.test\nOUTPUT_FILE={self.out}\n")

    def written(self):
        return yaml.safe_load(self.out.read_text())["http"]["middlewares"]

    def test_state_backend_records_only_the_state(self):
        StateOnly(config.CONFIG_FILE).apply("nord", ignore_pins=True)
        self.assertEqual(backend.read_current(config.CONFIG_FILE), "nord")
        self.assertTrue(backend.read_ignore_pins(config.CONFIG_FILE))
        self.assertFalse(self.out.exists())                          # no proxy config from the picker
        StateOnly(config.CONFIG_FILE).apply("dracula")
        self.assertFalse(backend.read_ignore_pins(config.CONFIG_FILE))
        with self.assertRaises(backend.ApplyError):
            StateOnly(config.CONFIG_FILE).apply("../../etc")

    def test_output_is_identical_to_the_traefik_file_backend(self):
        state.OVERRIDES_FILE.write_text(json.dumps({"forgejo": "dracula"}))
        direct = self.dir / "direct.yml"
        TraefikFile(output_file=direct, state_file=self.dir / "other.env", default_theme="dark",
                    apps=state.load_apps, pins=state.read_overrides, base_url=config.base_url).apply("nord")
        StateOnly(config.CONFIG_FILE).apply("nord")
        self.assertTrue(renderer.render())
        self.assertEqual(self.out.read_text(), direct.read_text())

    def test_honours_pins_and_ignore_pins(self):
        state.OVERRIDES_FILE.write_text(json.dumps({"forgejo": "dracula"}))
        StateOnly(config.CONFIG_FILE).apply("nord")
        renderer.render()
        self.assertEqual(self.written()["forgejo-theme"]["plugin"]["themepark"]["theme"], "dracula")
        StateOnly(config.CONFIG_FILE).apply("nord", ignore_pins=True)  # the screenshot capture
        renderer.render()
        self.assertEqual(self.written()["forgejo-theme"]["plugin"]["themepark"]["theme"], "nord")

    def test_files_are_readable_by_the_other_container(self):
        # The picker writes the state, the renderer (another user) reads it.
        StateOnly(config.CONFIG_FILE).apply("nord")
        renderer.render()
        self.assertEqual(config.CONFIG_FILE.stat().st_mode & 0o777, 0o664)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o644)

    def test_writes_only_on_change(self):
        StateOnly(config.CONFIG_FILE).apply("nord")
        self.assertTrue(renderer.render())
        self.assertFalse(renderer.render())

    def test_refuses_what_the_picker_could_plant(self):
        config.CONFIG_FILE.write_text("CURRENT_THEME=x\n  evil: [1]\n")       # extra lines are ignored
        renderer.render()
        self.assertEqual(self.written()["sonarr-theme"]["plugin"]["themepark"]["theme"], "x")
        config.CONFIG_FILE.write_text("CURRENT_THEME=../x\n")
        with self.assertRaises(backend.ApplyError):
            renderer.render()
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")
        state.OVERRIDES_FILE.write_text(json.dumps({"forgejo": "a b: c", "sonarr": "x\ny"}))
        renderer.render()                                              # bad pins are dropped
        self.assertEqual({m["plugin"]["themepark"]["theme"] for m in self.written().values()}, {"nord"})

    def test_skips_apps_with_odd_names(self):
        state.APPS_FILE.write_text(APPS_YML + "  - name: \"bad name\"\n  - name: ok-app\n    theme_app: \"x/../y\"\n")
        StateOnly(config.CONFIG_FILE).apply("nord")
        with mock.patch("sys.stderr"):
            renderer.render()
        self.assertEqual(sorted(self.written()), ["forgejo-theme", "sonarr-theme"])

    def test_once_command(self):
        StateOnly(config.CONFIG_FILE).apply("nord")
        with mock.patch("builtins.print") as out:
            renderer.main(["--once"])
        self.assertEqual(out.call_args.args[0], "wrote")


class StateDirSetting(SandboxCase):
    def test_comes_from_config_env_unless_set(self):
        config.SETTINGS_FILE.write_text("STATE_DIR=/srv/picker-state\n")
        with mock.patch.dict(config.SETTINGS, {"state_dir": None}):
            self.assertEqual(str(config._state_dir()), "/srv/picker-state")
        with mock.patch.dict(config.SETTINGS, {"state_dir": self.dir / "mine"}):
            self.assertEqual(config._state_dir(), self.dir / "mine")
        config.SETTINGS_FILE.write_text("")
        with mock.patch.dict(config.SETTINGS, {"state_dir": None}):
            self.assertEqual(config._state_dir(), config.THEME_DIR)       # the old layout

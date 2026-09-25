import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from picker import config
from picker.config import ConfigError, read_file, resolve

REPO = Path("/srv/checkout")


def quiet_resolve(env, data):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        return resolve(env, data, REPO), err.getvalue()


class Precedence(unittest.TestCase):
    def test_defaults_are_the_pre_config_behaviour(self):
        s, _ = quiet_resolve({}, {})
        self.assertEqual(s["theme_switcher_dir"], REPO.parent)
        self.assertEqual((s["listen.host"], s["listen.port"]), ("0.0.0.0", 8090))
        self.assertEqual(s["coverage.interval"], 900)
        self.assertEqual(s["screenshots.apps"], config.DEFAULT_SCREENSHOT_APPS)
        self.assertEqual((s["domain"], s["ntfy.url"], s["theme_park_url"], s["picker_url"]),
                         ("", "", None, None))

    def test_file_over_default_and_env_over_file(self):
        data = {"domain": "file.test", "listen": {"port": 9000}, "ntfy": {"topic": "t-file"},
                "coverage": {"interval": 60}, "screenshots": {"apps": ["dozzle", "emby"]}}
        s, _ = quiet_resolve({}, data)
        self.assertEqual((s["domain"], s["listen.port"], s["ntfy.topic"], s["coverage.interval"]),
                         ("file.test", 9000, "t-file", 60))
        self.assertEqual(s["screenshots.apps"], ["dozzle", "emby"])
        s, _ = quiet_resolve({"DOMAIN": "env.test", "LISTEN_PORT": "9100", "COVERAGE_INTERVAL": "0",
                              "APPS": "grafana  forgejo"}, data)
        self.assertEqual((s["domain"], s["listen.port"], s["coverage.interval"]), ("env.test", 9100, 0))
        self.assertEqual(s["screenshots.apps"], ["grafana", "forgejo"])

    def test_empty_env_var_counts_as_unset(self):
        s, _ = quiet_resolve({"DOMAIN": ""}, {"domain": "file.test"})
        self.assertEqual(s["domain"], "file.test")

    def test_theme_switcher_dir_relative_to_checkout(self):
        s, _ = quiet_resolve({}, {"theme_switcher_dir": "../elsewhere"})
        self.assertEqual(s["theme_switcher_dir"], Path("/srv/elsewhere"))
        s, _ = quiet_resolve({"THEME_SWITCHER_DIR": "/abs/dir"}, {"theme_switcher_dir": "x"})
        self.assertEqual(s["theme_switcher_dir"], Path("/abs/dir"))

    def test_ntfy_url_trailing_slash(self):
        s, _ = quiet_resolve({}, {"ntfy": {"url": "http://ntfy:80/"}})
        self.assertEqual(s["ntfy.url"], "http://ntfy:80")


class Validation(unittest.TestCase):
    BAD = [
        ({"listen": {"port": 0}}, "listen.port"),
        ({"listen": {"port": "eighty"}}, "listen.port"),
        ({"coverage": {"interval": -1}}, "coverage.interval"),
        ({"domain": "https://example.com"}, "domain"),
        ({"domain": 5}, "domain"),
        ({"theme_park_url": "theme-park.example.com"}, "theme_park_url"),
        ({"picker_url": "javascript:alert(1)"}, "picker_url"),
        ({"ntfy": {"url": "ntfy:80"}}, "ntfy.url"),
        ({"screenshots": {"apps": ["Dozzle"]}}, "screenshots.apps"),
        ({"screenshots": {"apps": ["../x"]}}, "screenshots.apps"),
        ({"screenshots": {"apps": {"a": 1}}}, "screenshots.apps"),
    ]

    def test_bad_values_fail_loudly_with_the_key(self):
        for data, key in self.BAD:
            with self.subTest(data=data):
                with self.assertRaises(ConfigError) as cm:
                    quiet_resolve({}, data)
                self.assertTrue(str(cm.exception).startswith(key + ":"), str(cm.exception))

    def test_unknown_keys_warn_but_do_not_fail(self):
        _, err = quiet_resolve({}, {"domian": "x", "listen": {"prot": 1}, "ntfy": {"url": ""}})
        self.assertIn("unknown setting 'domian'", err)
        self.assertIn("unknown setting 'listen.prot'", err)
        self.assertNotIn("ntfy", err)


class Files(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        p = Path(d) / "picker.yml"
        p.write_text(text)
        return p

    def test_missing_and_empty_files(self):
        self.assertEqual(read_file("/nonexistent/picker.yml"), {})
        self.assertEqual(read_file(self.write("# only comments\n")), {})

    def test_bad_yaml_and_wrong_shape(self):
        with self.assertRaisesRegex(ConfigError, "not valid YAML"):
            read_file(self.write("domain: [unclosed\n"))
        with self.assertRaisesRegex(ConfigError, "mapping"):
            read_file(self.write("- a\n- b\n"))

    def test_example_file_is_valid_and_complete(self):
        data = read_file(config.REPO_DIR / "picker.example.yml")
        s, err = quiet_resolve({}, data)
        self.assertEqual(err, "")
        documented = set()
        for k, v in data.items():
            documented |= {f"{k}.{kk}" for kk in v} if isinstance(v, dict) else {k}
        self.assertEqual(documented, {".".join(k) for k in config.KEYS})


class Urls(unittest.TestCase):
    def test_config_env_base_url_must_be_http(self):
        d = Path(tempfile.mkdtemp()); self.addCleanup(__import__("shutil").rmtree, d)
        with mock.patch.object(config, "THEME_PARK_URL", None), \
             mock.patch.object(config, "SETTINGS_FILE", d / "config.env"):
            for value, want in (("https://tp.example.test/", "https://tp.example.test"),
                                ("file:///etc/passwd", ""), ("ftp://x", ""), ("tp.example.test", "")):
                (d / "config.env").write_text(f"BASE_URL={value}\n")
                self.assertEqual(config.base_url(), want, value)

    def test_theme_park_url_overrides_config_env(self):
        with mock.patch.object(config, "THEME_PARK_URL", "https://tp.example.test/"):
            self.assertEqual(config.base_url(), "https://tp.example.test")

    def test_picker_url(self):
        with mock.patch.object(config, "PICKER_URL", None), mock.patch.object(config, "DOMAIN", "d.test"):
            self.assertEqual(config.picker_url(), "https://theme-picker.d.test/")
        with mock.patch.object(config, "PICKER_URL", "https://p.test/"):
            self.assertEqual(config.picker_url(), "https://p.test/")
        with mock.patch.object(config, "PICKER_URL", None), mock.patch.object(config, "DOMAIN", ""):
            self.assertEqual(config.picker_url(), "")

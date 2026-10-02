"""Portable custom-theme deploy (custom_themes.theme_park_www).

A fake theme.park www/ with a stub themes.py that writes the per-app wrapper
files the way the real one does. The real script is exercised end to end
against a real theme.park container, not here."""

import json
from pathlib import Path
from unittest import mock

from picker import config, deploy, editor, themes, twins, variants
from tests.support import SandboxCase

STUB = '''
import json, os
apps = [a for a in os.listdir("css/base") if os.path.isfile(f"css/base/{a}/{a}-base.css")
        and not os.path.exists(f"css/base/{a}/.deprecated")]
themes = [t[:-4] for t in os.listdir("css/theme-options") if t.endswith(".css")]
for a in apps:
    for t in themes:
        open(f"css/base/{a}/{t.lower()}.css", "w").write(f'@import url("/css/theme-options/{t}.css");')
json.dump({"themes": {t.capitalize(): {"url": f"https://{os.environ.get('TP_DOMAIN', 'cname')}/css/theme-options/{t}.css"} for t in themes}},
          open("themes.json", "w"))
open("ran.log", "a").write("run\\n")
'''
CSS = ":root { --main-bg-color: #101010; }\n"
FIX = Path(__file__).parent / "fixtures"
DARK = (FIX / "high_contrast.css").read_text().replace(
    "}", "  --petio-spinner: invert(100%);\n}")          # make_variants recomputes it for the twin


class Deploy(SandboxCase):
    def setUp(self):
        super().setUp()
        self.www = self.dir / "www"
        for d in ("css/theme-options", "css/community-theme-options", "css/base/sonarr", "css/base/radarr"):
            (self.www / d).mkdir(parents=True)
        (self.www / "css/base/sonarr/sonarr-base.css").write_text("/* base */")
        (self.www / "css/base/radarr/radarr-base.css").write_text("/* base */")
        (self.www / "css/base/oldapp").mkdir()                        # deprecated: themes.py skips it
        (self.www / "css/base/oldapp/oldapp-base.css").write_text("/* base */")
        (self.www / "css/base/oldapp/.deprecated").write_text("")
        (self.www / "css/theme-options/nord.css").write_text("/* shipped */")
        (self.www / "themes.py").write_text(STUB)
        p = mock.patch.object(config, "THEME_PARK_WWW", self.www)
        p.start()
        self.addCleanup(p.stop)

    def runs(self):
        log = self.www / "ran.log"
        return log.read_text().count("run") if log.exists() else 0

    def test_deploys_and_generates_per_app_files(self):
        self.add_custom("my-theme", CSS)
        r = deploy.deploy()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["deployed"], ["my-theme"])
        self.assertEqual((self.www / "css/theme-options/my-theme.css").read_text(), CSS)
        self.assertTrue((self.www / "css/base/sonarr/my-theme.css").exists())
        self.assertTrue((self.www / "css/base/radarr/my-theme.css").exists())

    def test_nothing_changed_means_no_rerun(self):
        self.add_custom("my-theme", CSS)
        deploy.deploy()
        r = deploy.deploy()
        self.assertEqual((r["deployed"], r["unchanged"], self.runs()), ([], 1, 1))   # deprecated app ignored

    def test_a_changed_theme_is_redeployed(self):
        self.add_custom("my-theme", CSS)
        deploy.deploy()
        self.add_custom("my-theme", CSS.replace("101010", "202020"))
        r = deploy.deploy()
        self.assertEqual(r["deployed"], ["my-theme"])
        self.assertIn("202020", (self.www / "css/theme-options/my-theme.css").read_text())

    def test_missing_per_app_files_are_regenerated(self):
        self.add_custom("my-theme", CSS)
        deploy.deploy()
        (self.www / "css/base/sonarr/my-theme.css").unlink()      # e.g. a fresh www volume
        deploy.deploy()
        self.assertTrue((self.www / "css/base/sonarr/my-theme.css").exists())

    def test_removed_source_is_pruned_with_its_wrappers(self):
        self.add_custom("my-theme", CSS)
        deploy.deploy()
        (self.custom_dir / "my-theme.css").unlink()
        r = deploy.deploy()
        self.assertEqual(r["removed"], ["my-theme"])
        self.assertFalse((self.www / "css/theme-options/my-theme.css").exists())
        self.assertFalse((self.www / "css/base/sonarr/my-theme.css").exists())

    def test_never_touches_a_theme_park_theme(self):
        self.add_custom("nord", CSS)                                  # same name as a shipped one
        r = deploy.deploy()
        self.assertEqual(r["refused"], ["nord"])
        self.assertEqual((self.www / "css/theme-options/nord.css").read_text(), "/* shipped */")
        (self.custom_dir / "nord.css").unlink()
        deploy.deploy()
        self.assertTrue((self.www / "css/theme-options/nord.css").exists())

    def test_an_identical_hand_copied_theme_is_adopted(self):
        (self.www / "css/theme-options/my-theme.css").write_text(CSS)
        self.add_custom("my-theme", CSS)
        r = deploy.deploy()
        self.assertEqual((r["refused"], r["unchanged"]), ([], 1))

    def test_unsafe_sources_are_refused(self):
        self.add_custom("Upper", CSS)
        (self.custom_dir / "linked.css").symlink_to(self.dir / "elsewhere.css")
        (self.dir / "elsewhere.css").write_text(CSS)
        self.add_custom("huge", "x" * (deploy.MAX_THEME_BYTES + 1))
        r = deploy.deploy()
        self.assertEqual(sorted(r["refused"]), ["Upper", "huge", "linked"])
        self.assertEqual(sorted(p.name for p in (self.www / "css/theme-options").iterdir()), ["nord.css"])

    def test_passes_the_theme_park_domain(self):
        self.add_custom("my-theme", CSS)
        with mock.patch.object(config, "THEME_PARK_URL", "https://tp.example.com"):
            deploy.deploy()
        data = json.loads((self.www / "themes.json").read_text())
        self.assertIn("https://tp.example.com/", data["themes"]["My-theme"]["url"])

    def test_not_theme_park_is_an_error_not_a_crash(self):
        with mock.patch.object(config, "THEME_PARK_WWW", self.dir / "nope"):
            r = deploy.deploy()
        self.assertFalse(r["ok"])
        self.assertIn("not found", r["error"])

    def test_editor_saves_straight_to_the_custom_dir_and_deploys(self):
        f = {k: "#123456" for k in editor.EDITOR_FIELDS}
        f.update(text="#eeeeee", text_hover="#ffffff", muted="#aaaaaa", button_text="#ffffff",
                 page_bg="#101010", panel_bg="#181818", queue="#2e8b57")
        ok, msg = editor.editor_save({"name": "made-here", "title": "Made Here", "base": "scratch", **f,
                                      "spinner": "invert(50%) sepia(50%) saturate(500%) hue-rotate(100deg) "
                                                 "brightness(90%) contrast(90%)"})
        self.assertTrue(ok, msg)
        self.assertTrue((self.custom_dir / "made-here.css").exists())
        self.assertTrue((self.www / "css/base/sonarr/made-here.css").exists())
        self.assertFalse(editor.QUEUE_DIR.exists())
        self.assertEqual(editor.editor_status("made-here")["state"], "deployed")


class Twins(Deploy):
    """Portable mode makes every theme's light/dark twin (picker/twins.py)."""

    def twin(self, name):
        p = self.custom_dir / f"{name}.css"
        return p.read_text() if p.exists() else None

    def test_a_dark_theme_gets_a_light_twin_that_deploys(self):
        self.assertEqual(variants.mode_of(variants.declarations(DARK)), "dark")
        self.add_custom("mine", DARK)
        r = deploy.deploy()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["twins_made"], ["mine-light"])
        css = self.twin("mine-light")
        self.assertIn(f"{variants.MARK} light of 'mine'", css)
        self.assertEqual(variants.mode_of(variants.declarations(css)), "light")
        self.assertRegex(css, r"--petio-spinner: invert\(")
        self.assertIn("mine-light", r["deployed"])
        self.assertTrue((self.www / "css/base/sonarr/mine-light.css").exists())
        self.assertIn("mine-light", themes.variant_themes())

    def test_unchanged_source_is_not_remade_and_a_changed_one_is(self):
        self.add_custom("mine", DARK)
        deploy.deploy()
        self.assertEqual(deploy.deploy()["twins_made"], [])
        self.add_custom("mine", DARK.replace("--text:", "--text-hover: #eeeeee;\n  --text:"))
        self.assertEqual(deploy.deploy()["twins_made"], ["mine-light"])

    def test_a_removed_source_takes_its_twin_with_it(self):
        self.add_custom("mine", DARK)
        deploy.deploy()
        (self.custom_dir / "mine.css").unlink()
        r = deploy.deploy()
        self.assertEqual(r["twins_removed"], ["mine-light"])
        self.assertIsNone(self.twin("mine-light"))
        self.assertFalse((self.www / "css/theme-options/mine-light.css").exists())

    def test_a_real_twin_means_no_generated_one(self):
        self.add_custom("mine", DARK)
        deploy.deploy()
        light = self.twin("mine-light").replace(variants.MARK, "hand made")
        self.add_custom("mine-light", light)                # now a real twin, written by hand
        r = deploy.deploy()
        self.assertEqual((r["twins_made"], r["twins_removed"]), ([], []))
        self.assertEqual(self.twin("mine-light"), light)

    def test_never_overwrites_a_hand_made_theme(self):
        self.add_custom("mine", DARK)
        self.add_custom("mine-light", DARK)                 # dark, so not a twin -- and not ours
        r = twins.sync(self.custom_dir, self.www)
        self.assertNotIn("mine-light", r["made"])           # (it gets its own twin, mine-light-light)
        self.assertIn(("mine", "'mine-light' is taken"), r["skipped"])
        self.assertEqual(self.twin("mine-light"), DARK)

    def test_theme_parks_own_themes_get_twins_but_twins_do_not(self):
        (self.www / "css/community-theme-options/dusk.css").write_text(DARK)
        r = deploy.deploy()
        self.assertEqual(r["twins_made"], ["dusk-light"])
        self.assertIn("community theme", self.twin("dusk-light"))
        self.assertEqual(deploy.deploy()["twins_made"], [])     # no dusk-light-dark

    def test_off_with_the_setting(self):
        self.add_custom("mine", DARK)
        with mock.patch.object(config, "MAKE_TWINS", False):
            r = deploy.deploy()
        self.assertEqual(r["twins_made"], [])
        self.assertIsNone(self.twin("mine-light"))


class Disabled(SandboxCase):
    def test_off_by_default_and_editor_still_queues(self):
        self.assertFalse(deploy.enabled())
        self.assertEqual(deploy.deploy.__name__, "deploy")

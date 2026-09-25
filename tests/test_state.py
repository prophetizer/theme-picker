import json
from unittest import mock

from picker import state
from tests.support import SandboxCase


def write_history(entries):
    state.HISTORY_FILE.write_text(json.dumps(entries))


class RecentThemes(SandboxCase):
    def test_distinct_newest_first_excluding_the_live_one(self):
        write_history([{"theme": t, "at": "", "by": "x"}
                       for t in ("a", "b", "a", "c", "live", "b")])
        self.assertEqual([e["theme"] for e in state.recent_themes("live")], ["b", "c", "a"])

    def test_capped_at_the_chip_count(self):
        write_history([{"theme": f"t{i}"} for i in range(20)])
        got = [e["theme"] for e in state.recent_themes("t19")]
        self.assertEqual(got, ["t18", "t17", "t16", "t15", "t14", "t13"])
        self.assertEqual(len(got), state.HISTORY_CHIPS)

    def test_skips_entries_without_a_theme_and_keeps_the_newest_entry(self):
        write_history([{"theme": "a", "at": "old"}, {}, {"theme": ""}, {"theme": "a", "at": "new"}])
        self.assertEqual(state.recent_themes("z"), [{"theme": "a", "at": "new"}])

    def test_missing_or_corrupt_history(self):
        self.assertEqual(state.recent_themes("x"), [])
        state.HISTORY_FILE.write_text("{not json")
        self.assertEqual(state.recent_themes("x"), [])
        state.HISTORY_FILE.write_text('{"a": 1}')
        self.assertEqual(state.read_history(), [])


class RecordHistory(SandboxCase):
    def test_appends_and_trims(self):
        with mock.patch.object(state, "HISTORY_KEEP", 3):
            for t in "abcd":
                state.record_history(t, "tester")
        hist = state.read_history()
        self.assertEqual([e["theme"] for e in hist], ["b", "c", "d"])
        self.assertEqual(hist[-1]["by"], "tester")
        self.assertRegex(hist[-1]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")


class UsageStats(SandboxCase):
    def test_counts_and_time(self):
        write_history([{"theme": "a", "at": "2026-01-01T00:00:00+00:00"},
                       {"theme": "b", "at": "2026-01-01T01:00:00+00:00"},
                       {"theme": "a", "at": "2026-01-01T01:30:00"}])     # naive = UTC
        st = state.usage_stats()
        self.assertEqual((st["changes"], st["distinct"]), (3, 2))
        self.assertEqual(st["by_count"][0], ("a", 2))
        self.assertEqual(dict(st["by_time"])["b"], 1800.0)

    def test_no_history(self):
        self.assertIsNone(state.usage_stats())


class AppsPinsFavourites(SandboxCase):
    def setUp(self):
        super().setUp()
        state.APPS_FILE.write_text("apps:\n  - name: sonarr\n  - name: forgejo\n    theme_app: gitea\n"
                                   "  - name: authelia\n    host: auth\n  - theme_app: nameless\n")

    def test_load_apps(self):
        self.assertEqual(state.load_apps(), [
            {"name": "sonarr", "theme_app": "sonarr", "host": "sonarr", "addons": []},
            {"name": "forgejo", "theme_app": "gitea", "host": "forgejo", "addons": []},
            {"name": "authelia", "theme_app": "authelia", "host": "auth", "addons": []}])

    def test_overrides_are_filtered(self):
        state.OVERRIDES_FILE.write_text(json.dumps(
            {"sonarr": "nord", "gone": "nord", "forgejo": "x; rm -rf /", "authelia": 5}))
        self.assertEqual(state.read_overrides(), {"sonarr": "nord"})

    def test_set_override_validates_before_touching_the_backend(self):
        self.assertEqual(state.set_override("nope", "nord"), (False, "unknown app 'nope'"))
        self.assertEqual(state.set_override("sonarr", "zzz"), (False, "unknown theme 'zzz'"))
        self.assertEqual(self.backend.pin_writes, 0)
        self.assertTrue(state.set_override("sonarr", "nord")[0])
        self.assertEqual(self.backend.pin_writes, 1)
        self.assertEqual(state.read_overrides(), {"sonarr": "nord"})
        self.assertEqual(state.set_override("sonarr", ""), (True, "sonarr follows the main theme again"))
        self.assertEqual(state.read_overrides(), {})

    def test_backend_failure_is_reported(self):
        self.backend.fail = "generator failed: boom"
        self.assertEqual(state.set_override("sonarr", "nord"), (False, "generator failed: boom"))

    def test_favourites(self):
        self.assertFalse(state.set_favourite("zzz-unknown", True))
        self.assertTrue(state.set_favourite("nord", True))
        self.assertTrue(state.set_favourite("dracula", True))
        self.assertEqual(state.read_favourites(), ["dracula", "nord"])
        self.assertTrue(state.set_favourite("nord", False))
        self.assertEqual(state.read_favourites(), ["dracula"])
        state.FAVS_FILE.write_text(json.dumps(["nord", "../x", 3]))
        self.assertEqual(state.read_favourites(), ["nord"])

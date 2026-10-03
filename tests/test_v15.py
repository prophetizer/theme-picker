"""Ratings, app groups, the ordered rotation playlist and the web app
manifest (2026-10-03)."""

import json
from unittest import mock

from picker import config, render, schedule, state
from tests.support import SandboxCase
from tests.test_handler import ServerCase
from tests.test_schedule import D, FirstPick, ScheduleCase

APPS = "apps:\n" + "".join(f"  - name: {a}\n" for a in ("sonarr", "radarr", "prowlarr", "forgejo"))


class Ratings(SandboxCase):
    def test_set_and_clear(self):
        self.assertTrue(state.set_rating("nord", 1))
        self.assertTrue(state.set_rating("dracula", -1))
        self.assertEqual(state.read_ratings(), {"nord": 1, "dracula": -1})
        self.assertTrue(state.set_rating("nord", 0))
        self.assertEqual(state.read_ratings(), {"dracula": -1})
        self.assertFalse(state.set_rating("not-a-theme", 1))
        self.assertFalse(state.set_rating("nord", 5))

    def test_pick_never_disliked_and_favours_liked(self):
        state.set_rating("dracula", -1)
        state.set_rating("nord", 1)
        seen = {}
        rng = __import__("random").Random(1)
        for _ in range(4000):
            t = state.pick(["nord", "dracula", "gruvbox"], rng)
            seen[t] = seen.get(t, 0) + 1
        self.assertNotIn("dracula", seen)
        self.assertAlmostEqual(seen["nord"] / seen["gruvbox"], 3, delta=0.4)
        self.assertIsNone(state.pick(["dracula"]))

    def test_the_theme_of_the_day_skips_disliked(self):
        state.set_favourite("dracula", True)
        state.set_rating("dracula", -1)
        with mock.patch.object(schedule.apply, "apply_theme") as ap:
            schedule.save_daily({"enabled": True, "at": "08:00", "pool": "favourites"}, now=D(9))
        ap.assert_not_called()


class Groups(SandboxCase):
    def setUp(self):
        super().setUp()
        state.APPS_FILE.write_text(APPS)

    def test_save_pin_and_delete(self):
        ok, msg = state.save_group("Arr apps", ["sonarr", "radarr", "nope"])
        self.assertTrue(ok, msg)
        self.assertEqual(state.read_groups(), {"Arr apps": ["radarr", "sonarr"]})
        ok, msg = state.pin_group("Arr apps", "nord")
        self.assertTrue(ok, msg)
        self.assertEqual(state.read_overrides(), {"radarr": "nord", "sonarr": "nord"})
        self.assertEqual(self.backend.pin_writes, 1)                 # one proxy update for the group
        state.set_override("prowlarr", "dracula")
        ok, _ = state.pin_group("Arr apps", "")
        self.assertTrue(ok)
        self.assertEqual(state.read_overrides(), {"prowlarr": "dracula"})  # only the group's apps cleared
        self.assertTrue(state.delete_group("Arr apps")[0])
        self.assertEqual(state.read_groups(), {})

    def test_refuses_bad_input(self):
        for name, apps in (("", ["sonarr"]), ("a" * 41, ["sonarr"]), ("x/y", ["sonarr"]), ("ok", []),
                           ("ok", ["nope"]), ("ok", "sonarr")):
            with self.subTest(name=name, apps=apps):
                self.assertFalse(state.save_group(name, apps)[0])
        state.save_group("g", ["sonarr"])
        self.assertFalse(state.pin_group("g", "not-a-theme")[0])
        self.assertFalse(state.pin_group("missing", "nord")[0])

    def test_groups_panel(self):
        state.save_group("Arr apps", ["sonarr", "radarr"])
        state.pin_group("Arr apps", "nord")
        page = render.groups_html()
        self.assertIn('data-group="Arr apps"', page)
        self.assertIn('<option value="nord" selected>', page)
        state.set_override("sonarr", "dracula")
        self.assertIn("mixed pins", render.groups_html())


class Playlist(ScheduleCase):
    def rotate(self, now, **over):
        data = {"enabled": True, "every": 24, "pool": "favourites", "mode": "list",
                "list": ["dracula", "catppuccin-latte", "nord"], **over}
        return schedule.save_rotate(data, now=now, rng=FirstPick)

    def test_applies_the_list_in_order_and_wraps(self):
        ok, msg = self.rotate(D(9))
        self.assertTrue(ok, msg)
        self.assertIn("the next theme from your list every 24 hours", msg)
        for day in (24, 25, 26):
            schedule.tick_rotate(D(9, day=day), rng=FirstPick)
        self.assertEqual([t for t, _ in self.applied], ["dracula", "catppuccin-latte", "nord", "dracula"])

    def test_skips_hidden_and_survives_edits(self):
        self.rotate(D(9))                                                 # dracula
        state.set_hidden("catppuccin-latte", True)
        schedule.tick_rotate(D(9, day=24), rng=FirstPick)                 # latte hidden: nord
        self.assertEqual(self.applied[-1][0], "nord")
        self.rotate(D(10, day=24), list=["catppuccin-latte", "dracula", "nord"])
        self.assertEqual(self.applied[-1][0], "dracula")   # a new list starts at its top (latte still hidden)
        state.set_hidden("catppuccin-latte", False)
        schedule.tick_rotate(D(10, day=25), rng=FirstPick)
        self.assertEqual(self.applied[-1][0], "nord")      # then the one after it

    def test_validation(self):
        self.assertFalse(self.rotate(D(9), list=["dracula"])[0])           # one theme is no playlist
        self.assertFalse(self.rotate(D(9), list=["dracula", "nope"])[0])   # unknown ones dropped -> one
        self.assertFalse(self.rotate(D(9), mode="shuffle")[0])
        self.assertFalse(self.rotate(D(9), list=["dracula"] * 201)[0])

    def test_status(self):
        self.rotate(D(9))
        st = schedule.status(D(10))
        self.assertEqual((st["rotate_mode"], st["rotate_list"], st["rotate_pool_size"]),
                         ("list", ["dracula", "catppuccin-latte", "nord"], 3))
        self.assertIn("from your list (3)", render.rotate_summary(st))


class Routes(ServerCase):
    def test_rate_route(self):
        status, _, body = self.post_json("/api/rate", {"theme": "nord", "rating": 1})
        self.assertEqual((status, json.loads(body)["ratings"]), (200, {"nord": 1}))
        self.assertEqual(self.post_json("/api/rate", {"theme": "nord", "rating": "x"})[0], 400)

    def test_group_route(self):
        state.APPS_FILE.write_text(APPS)
        status, _, body = self.post_json("/api/group", {"action": "save", "name": "Arr", "apps": ["sonarr"]})
        self.assertEqual(status, 200, body)
        status, _, body = self.post_json("/api/group", {"action": "pin", "name": "Arr", "theme": "nord"})
        self.assertEqual((status, json.loads(body)["pins"]), (200, {"sonarr": "nord"}))
        self.assertEqual(self.post_json("/api/group", {"action": "explode", "name": "Arr"})[0], 400)

    def test_manifest(self):
        status, headers, body = self.request("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200)
        m = json.loads(body)
        self.assertEqual((m["display"], m["start_url"]), ("standalone", "/#themes"))
        self.assertRegex(m["theme_color"], r"^#[0-9a-f]{6}\Z")
        for icon in m["icons"]:
            with self.subTest(icon=icon["src"]):
                s, h, _ = self.request("GET", icon["src"])
                self.assertEqual(s, 200)
        page = self.request("GET", "/")[2]
        page = page if isinstance(page, str) else page.decode()
        self.assertIn('rel="manifest"', page)
        self.assertIn('name="theme-color"', page)

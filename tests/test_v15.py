"""Ratings, app groups, the ordered rotation playlist and the web app
manifest (2026-10-03)."""

import json
import re
import os
from unittest import mock

from picker import config, render, schedule, shots, state
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


class Hardening(ServerCase):
    def test_rating_must_be_an_integer(self):
        for bad in (True, 1.0, "1", None, [1]):
            with self.subTest(rating=bad):
                self.assertEqual(self.post_json("/api/rate", {"theme": "nord", "rating": bad})[0], 400)
        self.assertEqual(state.read_ratings(), {})

    def test_state_files_are_written_safely(self):
        import os
        target = self.dir / "elsewhere.json"
        target.write_text("{}")
        (state.RATINGS_FILE.parent / "theme-ratings.tmp").symlink_to(target)   # the old fixed temp name
        state.set_rating("nord", 1)
        self.assertEqual(target.read_text(), "{}")                    # the link was not followed
        self.assertEqual(json.loads(state.RATINGS_FILE.read_text()), {"nord": 1})
        self.assertEqual(os.stat(state.RATINGS_FILE).st_mode & 0o777, 0o664)


class Compression(ServerCase):
    def get(self, path, gz):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            conn.request("GET", path, headers={"Accept-Encoding": "gzip, br"} if gz else {})
            r = conn.getresponse()
            return r.getheader("Content-Encoding"), r.getheader("Vary"), r.read()
        finally:
            conn.close()

    def test_page_json_and_static_are_gzipped_when_asked(self):
        import gzip
        for path in ("/", "/static/app.js?v=1", "/api/schedule"):
            with self.subTest(path=path):
                enc, vary, body = self.get(path, True)
                plain_enc, _, plain = self.get(path, False)
                self.assertIsNone(plain_enc)
                if len(plain) > 1024:
                    self.assertEqual((enc, vary), ("gzip", "Accept-Encoding"))
                    self.assertEqual(gzip.decompress(body), plain)

    def test_pngs_are_not_recompressed(self):
        enc, _, body = self.get("/static/icon-512.png", True)
        self.assertIsNone(enc)
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")


class RatingStats(SandboxCase):
    def test_liked_disliked_and_how_random_picks_used_them(self):
        self.assertIsNone(state.rating_stats())
        self.assertIn("No ratings yet", render.ratings_html())
        state.set_rating("nord", 1)
        state.set_rating("dracula", -1)
        state.HISTORY_FILE.write_text(json.dumps([
            {"theme": "nord", "at": "2026-10-01T08:00:00+00:00", "by": "schedule (theme of the day)"},
            {"theme": "catppuccin-latte", "at": "2026-10-01T09:00:00+00:00", "by": "schedule (rotation)"},
            {"theme": "nord", "at": "2026-10-01T10:00:00+00:00", "by": "alex"},
            {"theme": "dracula", "at": "2026-10-01T11:00:00+00:00", "by": "schedule (rotation)"}]))
        rs = state.rating_stats()
        self.assertEqual([r[:2] for r in rs["liked"]], [("nord", 2)])
        self.assertEqual([r[:2] for r in rs["disliked"]], [("dracula", 1)])
        self.assertEqual(rs["picks"], {"liked": 1, "unrated": 1, "disliked": 1})
        page = render.ratings_html()
        self.assertIn("Of 3 random picks", page)
        self.assertIn("1 were made before their theme was disliked", page)


class HiddenPairs(SandboxCase):
    def test_hiding_a_pair_keeps_both_forms_out_of_random_picks(self):
        light = ":root {\n  --main-bg-color: #f5f5f5;\n  --text: #111111;\n}\n"
        dark = ":root {\n  --main-bg-color: #101010;\n  --text: #eeeeee;\n}\n"
        self.add_custom("mine-dark", dark)
        self.add_custom("mine-light", light)
        from picker import themes as th
        pairs = th.variant_pairs()
        lead = next(k for k, v in pairs.items() if {k, v} == {"mine-dark", "mine-light"})
        twin = pairs[lead]
        self.assertTrue(state.set_hidden(twin, True))             # hiding the twin hides the pair
        self.assertEqual(state.read_hidden(), [lead])
        self.assertTrue({"mine-dark", "mine-light"} <= state.hidden_set())
        pool = schedule.pool_themes("all")
        self.assertNotIn("mine-dark", pool)
        self.assertNotIn("mine-light", pool)


class Digest(SandboxCase):
    def test_slot_and_due_once_with_catch_up(self):
        from datetime import datetime
        from picker import digest
        mon9 = datetime(2026, 10, 5, 9, 0)                       # a Monday
        self.assertEqual(digest.slot(datetime(2026, 10, 5, 9, 0), "mon 09:00"), mon9)
        self.assertEqual(digest.slot(datetime(2026, 10, 5, 8, 59), "mon 09:00"), datetime(2026, 9, 28, 9, 0))
        self.assertEqual(digest.slot(datetime(2026, 10, 8, 14, 0), "mon 09:00"), mon9)   # Thursday: Monday's
        self.assertIsNone(digest.slot(mon9, ""))
        sent = []
        with mock.patch.dict(config.SETTINGS, {"ntfy.digest": "mon 09:00"}):
            # switched on mid-week: nothing now, the first goes out Monday
            self.assertIsNone(digest.tick(datetime(2026, 10, 1, 12, 0), send=lambda *a, **k: sent.append(a)))
            self.assertEqual(sent, [])
            self.assertIsNotNone(digest.tick(datetime(2026, 10, 5, 9, 0, 20), send=lambda *a, **k: sent.append(a)))
            self.assertIsNone(digest.tick(datetime(2026, 10, 5, 12, 0), send=lambda *a, **k: sent.append(a)))
            # down over the next Monday 09:00, back on Tuesday: sent once then
            self.assertIsNotNone(digest.tick(datetime(2026, 10, 13, 8, 0), send=lambda *a, **k: sent.append(a)))
            self.assertIsNone(digest.tick(datetime(2026, 10, 13, 8, 1), send=lambda *a, **k: sent.append(a)))
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][0], "Theme picker: your week")

    def test_off_without_a_setting_or_ntfy(self):
        from datetime import datetime
        from picker import digest
        self.assertIsNone(digest.tick(datetime(2026, 10, 5, 9, 1)))      # no digest set, no ntfy

    def test_content(self):
        from datetime import datetime
        from picker import digest
        state.HISTORY_FILE.write_text(json.dumps([
            {"theme": "nord", "at": "2026-09-20T10:00:00+00:00", "by": "alex"},
            {"theme": "dracula", "at": "2026-10-03T10:00:00+00:00", "by": "schedule (night)"},
            {"theme": "catppuccin-latte", "at": "2026-10-04T10:00:00+00:00", "by": "alex"}]))
        state.DATES_FILE.write_text(json.dumps({"woodland": "2026-10-02T12:00:00Z", "old": "2026-01-01T00:00:00Z"}))
        title, body = digest.compose(datetime(2026, 10, 5, 9, 0))
        self.assertIn("2 theme changes this week (1 by the schedule).", body)
        self.assertIn("Most on screen: nord", body)                  # live from the week's start until Oct 3
        self.assertIn("1 new theme: woodland.", body)
        self.assertNotIn("old", body)

    def test_setting_is_validated(self):
        for bad in ("monday 9:00", "mon 25:00", "fri", 5):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                config.resolve({}, {"ntfy": {"digest": bad}})
        self.assertEqual(config.resolve({"NTFY_DIGEST": "Fri 17:00"}, {})["ntfy.digest"], "fri 17:00")


class HiddenForms(SandboxCase):
    def setUp(self):
        super().setUp()
        self.add_custom("mine-dark", ":root {\n  --main-bg-color: #101010;\n  --text: #eeeeee;\n}\n")
        self.add_custom("mine-light", ":root {\n  --main-bg-color: #f5f5f5;\n  --text: #111111;\n}\n")
        self.add_custom("solo", ":root {\n  --main-bg-color: #202020;\n  --text: #eeeeee;\n}\n")

    def test_one_form_hidden_keeps_the_other(self):
        self.assertTrue(state.set_hidden_form("mine-dark", True))
        self.assertEqual(state.read_hidden_forms(), ["mine-dark"])
        self.assertEqual(state.read_hidden(), [])
        pool = schedule.pool_themes("all")
        self.assertNotIn("mine-dark", pool)
        self.assertIn("mine-light", pool)
        self.assertTrue(state.set_hidden_form("mine-dark", False))
        self.assertIn("mine-dark", schedule.pool_themes("all"))

    def test_only_a_paired_theme_has_forms(self):
        self.assertFalse(state.set_hidden_form("solo", True))
        self.assertFalse(state.set_hidden_form("not-a-theme", True))

    def test_tiles_carry_the_flag(self):
        state.set_hidden_form("mine-light", True)
        page = render.render_page()
        self.assertRegex(page, r'data-theme="mine-light"[^>]*data-hidden-form="1"')
        self.assertRegex(page, r'data-theme="mine-dark"[^>]*data-hidden-form="0"')


class DigestPreview(ServerCase):
    def test_preview_composes_without_sending(self):
        with mock.patch("picker.ntfy.send") as send:
            status, _, body = self.request("GET", "/api/digest/preview")
        d = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(d["title"], "Theme picker: your week")
        self.assertIn("themes in all", d["body"])
        self.assertFalse(d["enabled"])
        send.assert_not_called()
        page = self.request("GET", "/")[2]
        self.assertIn(b"digest-preview-btn", page if isinstance(page, bytes) else page.encode())


class Collections(SandboxCase):
    def setUp(self):
        super().setUp()
        from picker import collections
        self.c = collections
        p = mock.patch.object(collections, "COLLECTIONS_FILE", self.dir / "theme-collections.json")
        p.start(); self.addCleanup(p.stop)

    def test_yours_toggle_and_delete(self):
        ok, _ = self.c.toggle("Work", "nord", True)
        self.assertTrue(ok)
        self.c.toggle("Work", "dracula", True)
        self.assertEqual(self.c.members("Work"), ["dracula", "nord"])
        self.c.toggle("Work", "nord", False)
        self.assertEqual(self.c.members("Work"), ["dracula"])
        self.c.toggle("Work", "dracula", False)                     # emptied: it goes
        self.assertIsNone(self.c.members("Work"))
        self.c.toggle("Work", "nord", True)
        self.assertTrue(self.c.delete("Work")[0])
        self.assertFalse(self.c.delete("Work")[0])

    def test_refusals(self):
        self.assertFalse(self.c.toggle("Light", "nord", True)[0])          # built in
        self.assertFalse(self.c.toggle("a/b", "nord", True)[0])
        self.assertFalse(self.c.toggle("ok", "not-a-theme", True)[0])

    def test_builtins_and_seasons(self):
        self.assertIn("Winter", self.c.season("frost-snow", {"family": "pink", "mode": "light"}))
        self.assertIn("Autumn", self.c.season("x", {"family": "orange", "mode": "dark"}))
        self.assertEqual(self.c.season("plain", {"family": "purple", "mode": "dark"}), [])
        self.assertIn("Light", self.c.names())
        self.assertIsNotNone(self.c.members("Dark"))

    def test_a_collection_is_a_pool(self):
        self.c.toggle("Work", "nord", True)
        self.c.toggle("Work", "dracula", True)
        self.assertTrue(schedule.pool_ok("collection:Work"))
        self.assertFalse(schedule.pool_ok("collection:Nope"))
        self.assertEqual(sorted(schedule.pool_themes("collection:Work")), ["dracula"] if
                         schedule.themes.current_theme() == "nord" else ["dracula", "nord"])
        ok, msg = schedule.save_rotate({"enabled": False, "every": 6, "pool": "collection:Work"})
        self.assertTrue(ok, msg)


class CaptureStatus(ServerCase):
    def write(self, **st):
        shots.STATUS_FILE.write_text(json.dumps(st))

    def test_running_with_an_estimate_and_a_banner(self):
        from datetime import datetime, timedelta
        now = datetime.now().astimezone()
        fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.write(running=True, started=fmt(now - timedelta(minutes=30)), updated=fmt(now), themes=80, index=20,
                   theme="nord", restore="dracula", shots=560, done=140)
        st = json.loads(self.request("GET", "/api/capture")[2])
        self.assertTrue(st["running"])
        self.assertEqual(st["minutes_left"], 90)                  # 140 shots in 30 min, 420 to go
        page = self.request("GET", "/")[2]
        page = page.decode() if isinstance(page, bytes) else page
        self.assertRegex(page, r'id="capture-banner" role="status">Screenshot capture running: theme 20 of 80 \(nord\)')

    def test_stale_and_finished(self):
        from datetime import datetime, timedelta
        now = datetime.now().astimezone()
        fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.write(running=True, started=fmt(now - timedelta(hours=2)), updated=fmt(now - timedelta(hours=1)),
                   themes=5, index=2, shots=10, done=3)
        st = shots.capture_status()
        self.assertEqual((st["running"], st.get("stalled")), (False, True))
        self.write(running=False, started=fmt(now), updated=fmt(now), finished=fmt(now), shots=10, done=10)
        self.assertFalse(shots.capture_status()["running"])
        self.assertIn('id="capture-banner" role="status" hidden', render.capture_banner())

    def test_nothing_written_yet(self):
        self.assertEqual(shots.capture_status(), {"running": False})


class CaptureStall(SandboxCase):
    def setUp(self):
        super().setUp()
        from datetime import datetime, timedelta
        from picker import monitor, ntfy
        self.monitor, self.td = monitor, timedelta
        self.now = datetime.now().astimezone()
        p = mock.patch.object(ntfy, "send")
        self.send = p.start()
        self.addCleanup(p.stop)

    def write(self, updated_ago, running=True, started="2026-10-04T04:30:00-0500"):
        t = (self.now - updated_ago).strftime("%Y-%m-%dT%H:%M:%S%z")
        shots.STATUS_FILE.write_text(json.dumps(dict(running=running, started=started, updated=t, themes=88,
                                                     index=40, theme="galaxy", restore="nord", shots=900, done=410)))

    def test_alerts_once_per_run_even_across_restarts(self):
        self.write(self.td(minutes=40))
        self.assertEqual(self.monitor.check_capture(self.now), "stalled")
        title, body = self.send.call_args[0][:2]
        self.assertEqual(title, "Screenshot capture stopped")
        self.assertIn("theme 40 of 88 (galaxy)", body)
        self.assertIn("restore nord", body)
        self.assertIsNone(self.monitor.check_capture(self.now))      # the alert is on disk, not in memory
        self.assertEqual(self.send.call_count, 1)
        self.write(self.td(minutes=40), started="2026-10-05T04:30:00-0500")
        self.assertEqual(self.monitor.check_capture(self.now), "stalled")   # a new run is a new incident

    def test_resumed_once(self):
        self.write(self.td(minutes=40))
        self.monitor.check_capture(self.now)
        self.write(self.td(minutes=1))
        self.assertEqual(self.monitor.check_capture(self.now), "resumed")
        self.assertIsNone(self.monitor.check_capture(self.now))
        self.assertEqual([c[0][0] for c in self.send.call_args_list],
                         ["Screenshot capture stopped", "Screenshot capture resumed"])

    def test_quiet_cases(self):
        self.assertIsNone(self.monitor.check_capture(self.now))     # no status at all
        self.write(self.td(minutes=2))                              # running and progressing
        self.assertIsNone(self.monitor.check_capture(self.now))
        self.write(self.td(minutes=40), running=False)              # finished
        self.assertIsNone(self.monitor.check_capture(self.now))
        self.write(self.td(days=3))                                 # an old leftover
        self.assertIsNone(self.monitor.check_capture(self.now))
        self.send.assert_not_called()


class NewShots(SandboxCase):
    def shoot(self, app, theme, at):
        for sub, ext in (("thumbs", ".jpg"), ("per-app", ".png")):
            f = shots.SHOT_DIR / sub / f"{app}_{theme}{ext}"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
            os.utime(f, (at, at))

    def test_the_last_runs_shots_newest_first(self):
        from datetime import datetime
        now = datetime.now().astimezone()
        t0 = now.timestamp() - 3 * 3600
        fmt = lambda ts: datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        shots.STATUS_FILE.write_text(json.dumps(dict(running=False, started=fmt(t0), finished=fmt(t0 + 3600),
                                                     updated=fmt(t0 + 3600))))
        self.shoot("sonarr", "galaxy", t0 + 600)
        self.shoot("radarr", "galaxy", t0 + 610)
        self.shoot("sonarr", "reef", t0 + 1800)
        self.shoot("sonarr", "nord", t0 - 86400)            # an older run
        items, label = shots.new_shots(now)
        self.assertEqual([t for t, _ in items], ["reef", "galaxy"])
        self.assertEqual(sorted(dict(items)["galaxy"]), ["radarr", "sonarr"])
        self.assertIn("the last capture", label)
        page = render.new_shots_html()
        self.assertIn("2 themes photographed in the last capture", page)
        self.assertIn("data-open='reef'", page)
        self.assertIn("/shots/thumb/sonarr_reef.jpg", page)

    def test_without_a_status_file_the_last_day(self):
        import time
        self.shoot("sonarr", "galaxy", time.time() - 3600)
        self.shoot("sonarr", "reef", time.time() - 3 * 86400)
        items, label = shots.new_shots()
        self.assertEqual(([t for t, _ in items], label), (["galaxy"], "the last 24 hours"))

    def test_nothing_new(self):
        self.assertEqual(render.new_shots_html(), "")            # no capture at all: no section
        import time
        self.shoot("sonarr", "galaxy", time.time() - 3 * 86400)
        self.assertIn("None from the last 24 hours", render.new_shots_html())


class NoShotsBadge(ServerCase):
    def page(self):
        b = self.request("GET", "/")[2]
        return b.decode() if isinstance(b, bytes) else b

    def tile(self, page, theme):
        return re.search(r'<button class="theme-btn[^"]*"[^>]*data-theme="%s".*?</button>' % re.escape(theme),
                         page, re.S).group(0)

    def test_badge_only_where_a_capture_runs(self):
        page = self.page()
        self.assertNotIn('class="tag noshots"', page)          # no screenshots anywhere: no badge
        names = re.findall(r'class="theme-btn[^"]*"[^>]*data-theme="([^"]+)"', page)
        shot, other = names[0], names[1]
        for sub, ext in (("thumbs", ".jpg"), ("per-app", ".png")):
            f = shots.SHOT_DIR / sub / f"sonarr_{shot}{ext}"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
        page = self.page()
        self.assertNotIn("noshots", self.tile(page, shot))
        self.assertIn('class="tag noshots"', self.tile(page, other))
        self.assertIn('id="only-noshots"', page)

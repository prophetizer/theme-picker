import json
from datetime import datetime, timedelta
from unittest import mock

from picker import apply, config, render, schedule, state
from tests.support import SandboxCase

D = lambda hh, mm=0, day=23: datetime(2026, 9, day, hh, mm)


class ScheduleCase(SandboxCase):
    def setUp(self):
        super().setUp()
        self.applied = []
        self.fail_status = None
        p = mock.patch.object(apply, "apply_theme", side_effect=self.fake_apply)
        p.start()
        self.addCleanup(p.stop)
        self.set_live("nord")

    def set_live(self, theme):
        config.CONFIG_FILE.write_text(f"CURRENT_THEME={theme}\n")

    def fake_apply(self, theme, by):
        if self.fail_status:
            return False, "boom", self.fail_status
        self.applied.append((theme, by))
        self.set_live(theme)
        return True, f"Theme set to '{theme}'.", 200

    def enable(self, now, **over):
        data = {"enabled": True, "day": "catppuccin-latte", "night": "dracula",
                "day_at": "07:00", "night_at": "19:00", **over}
        return schedule.save(data, now=now)


class Slots(ScheduleCase):
    SCH = {"day_at": "07:00", "night_at": "19:00"}

    def test_current_slot(self):
        for now, want in ((D(12), "day"), (D(7), "day"), (D(6, 59), "night"),
                          (D(20), "night"), (D(3), "night")):
            with self.subTest(now=now):
                self.assertEqual(schedule.current_slot(self.SCH, now)[1], want)
        self.assertEqual(schedule.current_slot(self.SCH, D(3))[0], D(19, day=22))    # yesterday's switch

    def test_next_switch(self):
        self.assertEqual(schedule.next_switch(self.SCH, D(12)), (D(19), "night"))
        self.assertEqual(schedule.next_switch(self.SCH, D(20)), (D(7, day=24), "day"))

    def test_day_after_night_on_the_clock(self):
        sch = {"day_at": "22:00", "night_at": "06:00"}
        self.assertEqual(schedule.current_slot(sch, D(23))[1], "day")
        self.assertEqual(schedule.current_slot(sch, D(12))[1], "night")


class Behaviour(ScheduleCase):
    def test_disabled_does_nothing(self):
        self.assertIsNone(schedule.tick(D(12)))
        self.assertEqual(self.applied, [])

    def test_enabling_applies_the_current_slot_now(self):
        ok, msg = self.enable(D(12))
        self.assertTrue(ok)
        self.assertEqual(self.applied, [("catppuccin-latte", "schedule (day)")])
        self.assertIn("Next switch: dracula at 19:00", msg)
        self.assertIn("Applied catppuccin-latte (day) now", msg)

    def test_manual_pick_holds_until_the_next_switch(self):
        self.enable(D(8))
        self.set_live("nord")                                  # picked by hand at noon
        for now in (D(12), D(15), D(18, 59)):
            self.assertIsNone(schedule.tick(now))
        self.assertEqual(schedule.tick(D(19)), ("night", "dracula", True, "Theme set to 'dracula'."))
        self.assertIsNone(schedule.tick(D(19, 1)))              # handled once
        self.assertEqual([t for t, _ in self.applied], ["catppuccin-latte", "dracula"])

    def test_catches_up_after_downtime(self):
        self.enable(D(20))                                     # night applied at 20:00
        self.assertEqual(schedule.tick(D(9, day=24))[1], "catppuccin-latte")

    def test_already_live_is_not_reapplied(self):
        self.set_live("catppuccin-latte")
        self.enable(D(12))
        self.assertEqual(self.applied, [])
        self.assertIsNone(schedule.tick(D(12, 1)))              # but the switch counts as handled

    def test_failed_apply_retries_but_unknown_theme_is_skipped(self):
        self.fail_status = 500
        self.enable(D(12))
        self.assertIsNotNone(schedule.tick(D(12, 1)))           # still pending: tries again
        self.fail_status = 400
        schedule.tick(D(12, 2))
        self.assertIsNone(schedule.tick(D(12, 3)))              # skipped, not retried forever

class RealApply(SandboxCase):
    def test_goes_through_apply_theme_and_is_recorded_as_scheduled(self):
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")
        schedule.save({"enabled": True, "day": "catppuccin-latte", "night": "dracula",
                       "day_at": "07:00", "night_at": "19:00"}, now=D(12))
        self.assertEqual(self.backend.applied, ["catppuccin-latte"])
        last = state.read_history()[-1]
        self.assertEqual((last["theme"], last["by"]), ("catppuccin-latte", "schedule (day)"))


class Validation(ScheduleCase):
    def test_rejections(self):
        for over, msg in (({"day_at": "7:00"}, "Day time"), ({"night_at": "24:00"}, "Night time"),
                          ({"night_at": "07:00"}, "different switch times"),
                          ({"day": "zzz-nope"}, "Pick a day theme"), ({"night": ""}, "Pick a night theme")):
            with self.subTest(over=over):
                ok, m = self.enable(D(12), **over)
                self.assertFalse(ok)
                self.assertIn(msg, m)
        self.assertEqual(self.applied, [])
        self.assertFalse(schedule.SCHEDULE_FILE.exists())

    def test_turning_off_keeps_the_choices(self):
        self.enable(D(12))
        ok, msg = schedule.save({"enabled": False, "day": "catppuccin-latte", "night": "dracula",
                                 "day_at": "07:00", "night_at": "19:00"}, now=D(13))
        self.assertEqual((ok, msg), (True, "Schedule off."))
        st = schedule.status(D(13))
        self.assertEqual((st["enabled"], st["day"], st["night"]), (False, "catppuccin-latte", "dracula"))
        self.assertIsNone(schedule.tick(D(19)))

    def test_corrupt_file_reads_as_defaults(self):
        schedule.SCHEDULE_FILE.write_text(json.dumps({"enabled": "yes", "day": 5}))
        self.assertEqual(schedule.read(), schedule.DEFAULTS)


class Panel(ScheduleCase):
    def test_status_and_summary(self):
        self.assertEqual(render.schedule_summary(schedule.status(D(12))), "off")
        self.enable(D(12))
        st = schedule.status(D(12))
        self.assertEqual(render.schedule_summary(st),
                         "on · now day (catppuccin-latte) · next: dracula at 19:00")

    def test_panel_preselects_the_saved_schedule(self):
        self.enable(D(12))
        html = render.schedule_html()
        self.assertIn('id="sch-enabled" checked', html)
        self.assertIn('<option value="dracula" selected>', html)
        self.assertIn('value="19:00"', html)


class FirstPick:
    """A stand-in for random: always the first candidate, so tests are exact."""
    @staticmethod
    def choice(seq):
        return seq[0]

    @staticmethod
    def choices(seq, weights=None):
        return [seq[0]]


class ThemeOfTheDay(ScheduleCase):
    def setUp(self):
        super().setUp()
        for t in ("dracula", "catppuccin-latte", "nord"):
            state.set_favourite(t, True)

    def daily(self, now, **over):
        data = {"enabled": True, "at": "08:00", "pool": "favourites", **over}
        return schedule.save_daily(data, now=now, rng=FirstPick)

    def test_enabling_picks_now_from_favourites_never_the_live_one(self):
        ok, msg = self.daily(D(9))
        self.assertTrue(ok, msg)
        self.assertEqual(self.applied, [("catppuccin-latte", "schedule (theme of the day)")])  # nord is live
        self.assertIn("Today's: catppuccin-latte", msg)

    def test_once_a_day_at_the_set_time(self):
        self.daily(D(9))
        schedule.tick_daily(D(23), rng=FirstPick)                     # same day: nothing
        schedule.tick_daily(D(7, day=24), rng=FirstPick)              # before 08:00 next day: nothing
        self.assertEqual(len(self.applied), 1)
        schedule.tick_daily(D(8, 1, day=24), rng=FirstPick)           # due
        self.assertEqual([t for t, _ in self.applied], ["catppuccin-latte", "dracula"])

    def test_hidden_themes_are_never_picked(self):
        state.set_hidden("catppuccin-latte", True)
        self.daily(D(9))
        self.assertEqual(self.applied[0][0], "dracula")

    def test_nothing_to_pick_from(self):
        for t in ("dracula", "catppuccin-latte", "nord"):
            state.set_favourite(t, False)
        ok, msg = self.daily(D(9))
        self.assertTrue(ok)
        self.assertIn("nothing to pick from", msg)
        self.assertEqual(self.applied, [])

    def test_all_themes_pool(self):
        for t in ("dracula", "catppuccin-latte", "nord"):
            state.set_favourite(t, False)
        self.daily(D(9), pool="all")
        self.assertEqual(len(self.applied), 1)
        self.assertNotEqual(self.applied[0][0], "nord")

    def test_exclusive_with_day_night(self):
        self.enable(D(9))
        self.assertTrue(schedule.read()["enabled"])
        self.daily(D(10))
        self.assertTrue(schedule.read()["daily_enabled"])
        self.assertFalse(schedule.read()["enabled"])                  # day/night turned off
        self.enable(D(11))
        self.assertFalse(schedule.read()["daily_enabled"])            # and the other way round

    def test_rejections_and_off(self):
        self.assertFalse(self.daily(D(9), at="25:00")[0])
        self.assertFalse(self.daily(D(9), pool="everything")[0])
        self.assertEqual(self.daily(D(9), enabled=False), (True, "Theme of the day off."))
        self.assertEqual(self.applied, [])

    def test_status_and_panel(self):
        self.daily(D(9))
        st = schedule.status(now=D(10))
        self.assertTrue(st["daily_enabled"])
        self.assertEqual(st["daily_pool_size"], 2)                     # favourites minus the live one
        self.assertIn("next pick", render.daily_summary(st))


class LocalTZ:
    """Run with the process's local time zone set to `tz`."""
    def __init__(self, tz):
        self.tz = tz

    def __enter__(self):
        import os, time
        self.old = os.environ.get("TZ")
        os.environ["TZ"] = self.tz
        time.tzset()

    def __exit__(self, *exc):
        import os, time
        if self.old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old
        time.tzset()


class SunMode(ScheduleCase):
    LONDON = {"sun": True, "lat": "51.5072", "lon": "-0.1276"}

    def test_sun_times_match_published_tables(self):
        from datetime import date
        rise, sset = schedule.sun_times(date(2026, 6, 21), 51.51, -0.13)
        self.assertEqual((rise.strftime("%H:%M"), sset.strftime("%H:%M")), ("03:43", "20:21"))   # UTC
        rise, sset = schedule.sun_times(date(2026, 1, 1), -33.87, 151.21)                        # Sydney
        self.assertEqual((rise.strftime("%d %H:%M"), sset.strftime("%d %H:%M")), ("31 18:47", "01 09:09"))
        self.assertEqual(schedule.sun_times(date(2026, 6, 21), 69.65, 18.96), "up")             # Tromsø
        self.assertEqual(schedule.sun_times(date(2026, 12, 21), 69.65, 18.96), "down")

    def test_switches_at_local_sunrise_and_sunset_with_offsets(self):
        with LocalTZ("Europe/London"):
            ok, msg = self.enable(D(12, day=23), **self.LONDON, day_offset="-30", night_offset="15")
            self.assertTrue(ok, msg)
            sch = schedule.read()
            self.assertEqual((sch["lat"], sch["lon"]), (51.51, -0.13))        # rounded, about 1 km
            t = schedule.slot_times(sch, D(0).date())
            rise, sset = (schedule._local(x) for x in schedule.sun_times(D(0).date(), 51.51, -0.13))
            self.assertEqual((rise.hour, sset.hour), (6, 18))                  # BST, not UTC
            self.assertEqual((t["day"], t["night"]),
                             (rise - timedelta(minutes=30), sset + timedelta(minutes=15)))
            self.assertIn(f"from sunrise ({t['day']:%H:%M} today)", msg)
            self.assertEqual(schedule.current_slot(sch, t["night"] - timedelta(minutes=1))[1], "day")
            self.assertEqual(schedule.current_slot(sch, t["night"])[1], "night")

    def test_polar_days_fall_back_to_the_clock(self):
        with LocalTZ("Europe/Oslo"):
            sch = dict(schedule.read(), sun=True, lat=69.65, lon=18.96, day_at="08:00", night_at="20:00")
            t = schedule.slot_times(sch, datetime(2026, 6, 21).date())
            self.assertEqual((t["day"].hour, t["night"].hour), (8, 20))

    def test_bad_coordinates(self):
        for over in ({"lat": "north"}, {"lat": "91"}, {"lon": "-181"}, {"lat": "nan"}, {"lat": ""},
                     {"day_offset": "200"}, {"night_offset": "x"}):
            with self.subTest(over=over):
                ok, _ = self.enable(D(12), **dict(self.LONDON, **over))
                self.assertFalse(ok)

    def test_status_says_when_the_sun_rises(self):
        with LocalTZ("Europe/London"):
            self.enable(D(12), **self.LONDON)
            st = schedule.status(D(12))
        self.assertRegex(st["sun_today"], r"^sunrise 06:[0-9]{2}, sunset 18:[0-9]{2} today\Z")
        self.assertIn("by the sun", render.schedule_summary(st))


class Rotation(ScheduleCase):
    def setUp(self):
        super().setUp()
        for t in ("dracula", "catppuccin-latte", "nord"):
            state.set_favourite(t, True)

    def rotate(self, now, **over):
        data = {"enabled": True, "every": 6, "pool": "favourites", **over}
        return schedule.save_rotate(data, now=now, rng=FirstPick)

    def test_enabling_picks_now_then_every_n_hours(self):
        ok, msg = self.rotate(D(9))
        self.assertTrue(ok, msg)
        self.assertIn("every 6 hours", msg)
        self.assertEqual(self.applied, [("catppuccin-latte", "schedule (rotation)")])
        schedule.tick_rotate(D(14, 59), rng=FirstPick)                     # not yet
        self.assertEqual(len(self.applied), 1)
        schedule.tick_rotate(D(15), rng=FirstPick)                         # 6 hours on
        self.assertEqual([t for t, _ in self.applied], ["catppuccin-latte", "dracula"])
        self.assertEqual(schedule.status(D(15, 30))["rotate_next"], "Wed 21:00")

    def test_one_schedule_at_a_time(self):
        self.enable(D(9))
        self.rotate(D(10))
        sch = schedule.read()
        self.assertEqual((sch["enabled"], sch["daily_enabled"], sch["rotate_enabled"]), (False, False, True))
        schedule.save_daily({"enabled": True, "at": "08:00", "pool": "favourites"}, now=D(11), rng=FirstPick)
        self.assertFalse(schedule.read()["rotate_enabled"])
        self.rotate(D(12))
        self.enable(D(13))
        self.assertFalse(schedule.read()["rotate_enabled"])

    def test_bad_input(self):
        for over in ({"every": 0}, {"every": 169}, {"every": "x"}, {"pool": "mine"}):
            with self.subTest(over=over):
                self.assertFalse(self.rotate(D(9), **over)[0])

    def test_off(self):
        self.rotate(D(9))
        ok, msg = self.rotate(D(10), enabled=False)
        self.assertEqual((ok, msg), (True, "Rotation off."))
        schedule.tick_rotate(D(23), rng=FirstPick)
        self.assertEqual(len(self.applied), 1)

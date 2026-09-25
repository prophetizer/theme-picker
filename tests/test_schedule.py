import json
from datetime import datetime
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

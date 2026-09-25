import unittest
from unittest import mock

from picker import config, monitor, ntfy, prom
from tests.support import SandboxCase


def result(theme="nord", **states):
    rows = [{"app": a, "url": f"https://{a}.example.test/", "expected": theme, "pinned": False,
             "state": s, "detail": "" if s == "ok" else "HTTP 200, no theme stylesheet in page"}
            for a, s in states.items()]
    return {"theme": theme, "checked": "", "ok": sum(r["state"] == "ok" for r in rows),
            "total": len(rows), "results": rows}


class MonitorCase(SandboxCase):
    def setUp(self):
        super().setUp()
        for name, value in (("_LAST", {}), ("_STREAK", {}), ("_ALERTED", set())):
            p = mock.patch.object(monitor, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ntfy, "send")
        self.send = p.start()
        self.addCleanup(p.stop)
        config.CONFIG_FILE.write_text("CURRENT_THEME=nord\n")

    def run_check(self, res):
        return monitor.run_once(check=lambda: res)


class Alerts(MonitorCase):
    def test_one_failure_does_not_alert(self):
        self.assertEqual(self.run_check(result(sonarr="missing", radarr="ok")), ([], []))
        self.send.assert_not_called()

    def test_two_in_a_row_alert_once_then_recover(self):
        bad = result(sonarr="missing", radarr="ok")
        self.run_check(bad)
        self.assertEqual(self.run_check(bad), (["sonarr"], []))
        title, body = self.send.call_args.args
        self.assertEqual(title, "Theme coverage: 1 app not themed")
        self.assertIn("sonarr: missing (HTTP 200, no theme stylesheet in page), expected nord", body)
        self.assertIn("1 of 2 apps OK.", body)
        self.assertEqual(self.send.call_args.kwargs["priority"], "high")

        self.assertEqual(self.run_check(bad), ([], []))                   # no repeat
        self.assertEqual(self.send.call_count, 1)

        self.assertEqual(self.run_check(result(sonarr="ok", radarr="ok")), ([], ["sonarr"]))
        self.assertEqual(self.send.call_args.args[0], "Theme coverage recovered")
        self.assertEqual(self.send.call_count, 2)

    def test_flapping_app_does_not_alert(self):
        for states in ({"sonarr": "wrong"}, {"sonarr": "ok"}, {"sonarr": "wrong"}, {"sonarr": "ok"}):
            self.run_check(result(**states))
        self.send.assert_not_called()

    def test_several_apps_in_one_message(self):
        bad = result(sonarr="missing", radarr="error", emby="ok")
        self.run_check(bad)
        self.run_check(bad)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.send.call_args.args[0], "Theme coverage: 2 apps not themed")

    def test_theme_change_mid_check_is_discarded(self):
        def check():
            config.CONFIG_FILE.write_text("CURRENT_THEME=dracula\n")      # e.g. the nightly capture
            return result(sonarr="wrong")
        self.assertIsNone(monitor.run_once(check=check))
        self.assertEqual((monitor._STREAK, monitor.last()), ({}, {}))

    def test_result_for_another_theme_is_discarded(self):
        self.assertIsNone(self.run_check(result(theme="dracula", sonarr="wrong")))


class NtfyDisabled(unittest.TestCase):
    def test_send_is_a_no_op_without_configuration(self):
        self.assertFalse(ntfy.enabled())                 # tests/__init__ clears NTFY_*
        with mock.patch.object(ntfy.urllib.request, "urlopen") as urlopen:
            ntfy.send("t", "b", priority="high")
        urlopen.assert_not_called()

    def test_send_headers(self):
        with mock.patch.object(ntfy, "enabled", return_value=True), \
             mock.patch.object(ntfy, "NTFY_URL", "http://ntfy.test"), \
             mock.patch.object(ntfy, "NTFY_TOPIC", "topic"), \
             mock.patch.object(ntfy, "_ntfy_token", return_value="tok"), \
             mock.patch.object(ntfy.urllib.request, "urlopen") as urlopen:
            ntfy.send("Title", "body", tags="warning", priority="high")
        req = urlopen.call_args.args[0]
        self.assertEqual((req.get_method(), req.full_url), ("POST", "http://ntfy.test/topic"))
        self.assertEqual(req.data, b"body")
        self.assertEqual({k.lower(): v for k, v in req.header_items()},
                         {"authorization": "Bearer tok", "title": "Title", "tags": "warning",
                          "priority": "high"})


class Metrics(MonitorCase):
    def test_before_any_check(self):
        text = prom.render_metrics()
        self.assertIn('theme_picker_theme_info{theme="nord",section="official",mode="unknown"} 1', text)
        self.assertIn('theme_picker_themes{section="official"} 11', text)
        self.assertNotIn("coverage", text)
        self.assertTrue(text.endswith("\n"))

    def test_after_a_check(self):
        self.run_check(result(sonarr="missing", radarr="ok"))
        text = prom.render_metrics()
        self.assertIn('theme_picker_coverage_app_ok{app="sonarr"} 0', text)
        self.assertIn('theme_picker_coverage_app_ok{app="radarr"} 1', text)
        self.assertIn("theme_picker_coverage_apps_ok 1", text)
        self.assertIn("theme_picker_coverage_apps_total 2", text)
        self.assertRegex(text, r"theme_picker_coverage_last_check_timestamp_seconds \d{10}\n")
        for line in text.splitlines():                 # every sample has HELP/TYPE above it
            if not line.startswith("#"):
                name = line.split("{")[0].split(" ")[0]
                self.assertIn(f"# TYPE {name} gauge", text)

    def test_change_time_only_for_the_live_theme(self):
        from picker import state
        state.record_history("dracula", "x")
        self.assertNotIn("changed_timestamp", prom.render_metrics())
        state.record_history("nord", "x")
        self.assertRegex(prom.render_metrics(), r"theme_picker_theme_changed_timestamp_seconds \d{10}\n")

    def test_label_escaping(self):
        self.assertEqual(prom._esc('a"b\\c\nd'), 'a\\"b\\\\c\\nd')

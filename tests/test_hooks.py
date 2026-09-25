import json
from unittest import mock

from picker import config, hooks, state
from tests.test_handler import ServerCase


class Hook(ServerCase):
    TOKEN = "s3cret-token-for-tests"

    def setUp(self):
        super().setUp()
        tok = self.dir / "hook-token"
        tok.write_text(self.TOKEN + "\n")
        p = mock.patch.dict(config.SETTINGS, {"hooks.token_file": str(tok)})
        p.start(); self.addCleanup(p.stop)
        config.CONFIG_FILE.write_text("CURRENT_THEME=dracula\n")

    def hook(self, body, token=TOKEN, extra=None):
        headers = {"Content-Type": "application/json", **(extra or {})}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        status, _, raw = self.request("POST", "/api/hook/theme", json.dumps(body).encode(), headers)
        return status, json.loads(raw)

    def test_sets_a_theme_and_records_the_source(self):
        status, body = self.hook({"theme": "nord", "source": "movie night"})
        self.assertEqual((status, body["ok"], body["theme"]), (200, True, "nord"))
        self.assertEqual(self.backend.applied, ["nord"])
        self.assertEqual(state.read_history()[-1]["by"], "automation (movie night)")

    def test_refuses_without_the_right_token(self):
        for token in (None, "", "wrong", self.TOKEN + "x", self.TOKEN[:-1]):
            with self.subTest(token=token):
                self.assertEqual(self.hook({"theme": "nord"}, token=token)[0], 401)
        status, _, _ = self.request("POST", "/api/hook/theme", b'{"theme": "nord"}',
                                    {"Content-Type": "application/json", "Authorization": f"Basic {self.TOKEN}"})
        self.assertEqual(status, 401)
        self.assertEqual(self.backend.applied, [])

    def test_still_behind_the_allowlist_and_csrf_guards(self):
        self.assertEqual(self.hook({"theme": "nord; rm -rf /"})[0], 400)
        self.assertEqual(self.hook({"theme": "nord"}, extra={"Origin": "https://evil.example"})[0], 403)
        status, _, _ = self.request("POST", "/api/hook/theme", b'{"theme": "nord"}',
                                    {"Content-Type": "text/plain", "Authorization": f"Bearer {self.TOKEN}"})
        self.assertEqual(status, 415)
        self.assertEqual(self.backend.applied, [])

    def test_off_without_a_token_file(self):
        with mock.patch.dict(config.SETTINGS, {"hooks.token_file": ""}):
            self.assertEqual(self.hook({"theme": "nord"})[0], 404)
        with mock.patch.dict(config.SETTINGS, {"hooks.token_file": str(self.dir / "missing")}):
            self.assertEqual(self.hook({"theme": "nord"})[0], 404)
        (self.dir / "hook-token").write_text("  \n")                 # empty token never matches
        self.assertEqual(self.hook({"theme": "nord"}, token="")[0], 404)

    def test_random_favourite_never_picks_the_live_theme(self):
        self.assertEqual(self.hook({"theme": "random-favourite"})[0], 400)          # none starred
        state.set_favourite("dracula", True)
        self.assertEqual(self.hook({"theme": "random-favourite"})[0], 400)          # only the live one
        state.set_favourite("nord", True)
        status, body = self.hook({"theme": "random-favourite"})
        self.assertEqual((status, body["theme"]), (200, "nord"))

    def test_bad_source_is_not_recorded_verbatim(self):
        self.hook({"theme": "nord", "source": "<script>x</script>"})
        self.assertEqual(state.read_history()[-1]["by"], "automation")

    def test_notify_only_when_asked(self):
        from picker import ntfy
        with mock.patch.object(ntfy, "schedule_notify") as notify:
            self.hook({"theme": "nord"})
            notify.assert_not_called()
            self.hook({"theme": "nord", "notify": True})
            notify.assert_called_once()

import json
import re

from picker import editor
from tests.support import SandboxCase

SPINNER = "invert(52%) sepia(61%) saturate(512%) hue-rotate(186deg) brightness(92%) contrast(88%)"


def payload(**over):
    p = {"name": "my-theme", "title": "My Theme", "base": "nord",
         "page_bg": "#101418", "panel_bg": "#1a2026", "button": "#3366cc",
         "button_hover": "#4477dd", "button_text": "#ffffff", "link": "#88aaff",
         "link_hover": "#aaccff", "text": "#e8e8e8", "text_hover": "#ffffff",
         "muted": "#b0b0b0", "queue": "#22aa66", "gradient": False, "angle": 160,
         "spinner": SPINNER}
    p.update(over)
    return p


class Save(SandboxCase):
    def saved(self, name="my-theme"):
        return (editor.QUEUE_DIR / f"{name}.css").read_text()

    def test_valid_submission_is_queued(self):
        ok, msg = editor.editor_save(payload())
        self.assertTrue(ok, msg)
        css = self.saved()
        self.assertIn("theme.park custom theme: My Theme", css)
        self.assertIn(editor.EDITOR_MARKER, css[:600])
        self.assertIn("starting from 'nord'", css)
        status = json.loads(editor.EDITOR_STATUS.read_text())
        self.assertEqual(status["my-theme"]["state"], "queued")
        self.assertEqual(editor.editor_status("my-theme")["state"], "queued")
        self.assertEqual(editor.editor_status("nope"), {"state": "unknown"})
        self.assertEqual(list(editor.QUEUE_DIR.glob(".*.tmp")), [])

    def test_exactly_22_variables_one_per_line(self):
        editor.editor_save(payload(gradient=True, page_bg2="#000000", angle=45))
        css = self.saved()
        root = css[css.index(":root {") + len(":root {"):css.rindex("}")]
        lines = [l for l in root.splitlines() if l.strip()]
        self.assertEqual(len(lines), 22)
        for line in lines:
            self.assertRegex(line, r"^  --[\w-]+: [^;\n]+;$")
        self.assertEqual(len(re.findall(r"--[\w-]+\s*:", css)), 22)
        self.assertIn("--main-bg-color: linear-gradient(45deg, #101418 0%, #000000 100%) "
                      "center center/cover no-repeat fixed;", css)
        self.assertIn("--accent-color: 51, 102, 204;", css)      # bare R, G, B, not hex

    def test_rejects_anything_but_rrggbb(self):
        for bad in ("#fff", "red", "#12345g", "#1234567", "#123456;}", "", "rgb(1,2,3)",
                    "#123456\n--x: url(evil)"):
            for field in ("page_bg", "text", "queue"):
                with self.subTest(field=field, value=bad):
                    ok, msg = editor.editor_save(payload(**{field: bad}))
                    self.assertFalse(ok)
                    self.assertIn(field, msg)
        self.assertFalse((editor.QUEUE_DIR / "my-theme.css").exists())

    def test_gradient_needs_a_valid_second_colour(self):
        ok, msg = editor.editor_save(payload(gradient=True, page_bg2="black"))
        self.assertFalse(ok)
        self.assertIn("Second gradient colour", msg)

    def test_rejects_bad_names(self):
        for bad in ("a", "My-Theme", "-lead", "has space", "x" * 41, "../x", "a/b", "a.b", "", "nord;"):
            with self.subTest(name=bad):
                ok, msg = editor.editor_save(payload(name=bad))
                self.assertFalse(ok)
                self.assertTrue(msg.startswith("Name:"))

    def test_rejects_bad_titles(self):
        for bad in ("", "x" * 41, "*/ :root { --text: red; } /*", "a<b>", "semi;colon"):
            with self.subTest(title=bad):
                ok, msg = editor.editor_save(payload(title=bad))
                self.assertFalse(ok)
                self.assertTrue(msg.startswith("Title:"))

    def test_refuses_theme_park_names(self):
        for name in ("nord", "dracula", "catppuccin-mocha", "blackberry-abyss"):
            with self.subTest(name=name):
                ok, msg = editor.editor_save(payload(name=name))
                self.assertFalse(ok)
                self.assertIn("theme.park's own themes", msg)

    def test_refuses_to_overwrite_a_hand_authored_theme(self):
        self.add_custom("my-theme", "/* theme.park custom theme: Hand made */\n:root {}\n")
        ok, msg = editor.editor_save(payload())
        self.assertFalse(ok)
        self.assertIn("hand-authored", msg)

    def test_may_overwrite_its_own_earlier_save(self):
        self.add_custom("my-theme", f"/*\n * {editor.EDITOR_MARKER} on 2026-01-01\n */\n:root {{}}\n")
        ok, msg = editor.editor_save(payload())
        self.assertTrue(ok, msg)

    def test_refuses_orange_or_yellow_queue_colour(self):
        for bad in ("#ff9900", "#ffcc00", "#e69a2e", "#d4b400"):
            with self.subTest(queue=bad):
                ok, msg = editor.editor_save(payload(queue=bad))
                self.assertFalse(ok)
                self.assertIn("orange/yellow", msg)
        for good in ("#22aa66", "#1e90ff", "#998877"):          # the last is too grey to clash
            with self.subTest(queue=good):
                ok, msg = editor.editor_save(payload(queue=good))
                self.assertTrue(ok, msg)

    def test_refuses_a_malformed_spinner(self):
        for bad in ("", "invert(52%)", SPINNER + ";", SPINNER + " url(x)", "; } body { display:none",
                    SPINNER.replace("186deg", "186"), SPINNER.replace("52%", "5200%")):
            with self.subTest(spinner=bad):
                ok, msg = editor.editor_save(payload(spinner=bad))
                self.assertFalse(ok)
                self.assertIn("Spinner", msg)

    def test_unknown_base_and_bad_angle_are_defaulted(self):
        ok, _ = editor.editor_save(payload(base="*/ evil", gradient=True, page_bg2="#000000",
                                           angle="ninety"))
        self.assertTrue(ok)
        css = self.saved()
        self.assertIn("starting from 'scratch'", css)
        self.assertIn("linear-gradient(160deg,", css)


class ThemeVars(SandboxCase):
    def test_flattens_a_theme_to_rrggbb(self):
        from tests.support import fixture
        self.add_custom("hc", fixture("high_contrast.css"))
        v = editor.theme_vars("hc")
        self.assertEqual(v["page_bg"], "#000000")
        self.assertEqual(v["page_bg2"], "")
        self.assertEqual(v["text"], "#ffffff")
        self.assertEqual(v["queue"], "#4fb87a")                  # not in the sheet: default
        for k, val in v.items():
            if k != "page_bg2":
                self.assertRegex(val, r"^#[0-9a-f]{6}$", k)

    def test_gradient_gives_a_second_colour(self):
        from tests.support import fixture
        self.add_custom("bb", fixture("blackberry_like.css"))
        v = editor.theme_vars("bb")
        self.assertRegex(v["page_bg2"], r"^#[0-9a-f]{6}$")
        self.assertNotEqual(v["page_bg"], v["page_bg2"])


class VerifyQueued(SandboxCase):
    """theme-worker.sh's check: only a file the editor could have built."""

    def saved(self, **over):
        ok, msg = editor.editor_save(payload(**over))
        self.assertTrue(ok, msg)
        return (editor.QUEUE_DIR / f"{over.get('name', 'my-theme')}.css").read_text()

    def test_real_saves_verify(self):
        self.assertIsNone(editor.verify_queued("my-theme", self.saved()))
        self.assertIsNone(editor.verify_queued("grad", self.saved(name="grad", gradient=True,
                                                                  page_bg2="#000000", angle=45)))

    def test_tampered_files_are_refused(self):
        css = self.saved()
        cases = {
            "extra declaration": css.replace("  --text-muted:", "  --x: url(https://evil/?a);\n  --text-muted:"),
            "url in a value": css.replace("--text: #e8e8e8;", "--text: #e8e8e8 url(//evil);"),
            "rule after :root": css + "input[value^=a] { background: url(https://evil/a); }\n",
            "rule before :root": css.replace(":root {", "body{display:none}\n:root {"),
            "non-hex colour": css.replace("--button-text: #ffffff;", "--button-text: red;"),
            "spinner": css.replace("contrast(88%)", "contrast(88%) url(x)"),
            "header": css.replace(editor.EDITOR_MARKER, "Created by hand"),
            "comment breakout in title": css.replace("custom theme: My Theme", "custom theme: */ body{} /*"),
            "trailing junk": css + "/* */",
            "empty": "",
        }
        for why, bad in cases.items():
            with self.subTest(why):
                self.assertIsNotNone(editor.verify_queued("my-theme", bad))

    def test_bad_name(self):
        self.assertEqual(editor.verify_queued("../evil", self.saved()), "bad name")

    def test_command_line(self):
        import subprocess, sys
        from picker import config
        good = editor.QUEUE_DIR / "my-theme.css"
        self.saved()
        run = lambda *a: subprocess.run([sys.executable, "-m", "picker.editor", *a], cwd=config.REPO_DIR,
                                        capture_output=True, text=True)
        self.assertEqual(run("--verify", "my-theme", str(good)).returncode, 0)
        good.write_text(good.read_text() + "a{}\n")
        r = run("--verify", "my-theme", str(good))
        self.assertEqual((r.returncode, r.stderr.strip()), (1, "content differs from what the editor builds"))

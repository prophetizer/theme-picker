"""The page's scripts must at least parse: a syntax error stops all of
app.js, the page falls back to its no-JavaScript form, and a click on a
tile then submits it -- applying the theme instead of opening a preview
(2026-10-02: a second `const ANSI`). Needs node; skipped without it."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted(ROOT.glob("picker/web/*.js")) + sorted(ROOT.glob("tools/demo/*.js"))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Syntax(unittest.TestCase):
    def test_every_script_parses(self):
        self.assertTrue(SCRIPTS)
        for js in SCRIPTS:
            with self.subTest(script=js.name):
                r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-500:])

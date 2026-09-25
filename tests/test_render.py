import json

from picker import render, state
from tests.support import SandboxCase


class Undo(SandboxCase):
    def test_points_at_the_previous_distinct_theme(self):
        state.HISTORY_FILE.write_text(json.dumps([{"theme": "dracula"}, {"theme": "nord"}]))
        html = render.undo_html("nord")
        self.assertIn('data-theme="dracula"', html)
        self.assertIn("Undo: <span>dracula</span>", html)
        self.assertNotIn(" hidden", html)

    def test_hidden_without_history(self):
        self.assertIn(" hidden>", render.undo_html("nord"))

    def test_on_the_page(self):
        state.HISTORY_FILE.write_text(json.dumps([{"theme": "dracula"}]))
        self.assertIn('id="undo" data-theme="dracula"', render.render_page())

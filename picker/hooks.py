"""Automation hook: let Home Assistant (or any script) set the theme.

  POST /api/hook/theme
  Authorization: Bearer <token>
  Content-Type: application/json
  {"theme": "nord"}                      a theme by name
  {"theme": "random-favourite"}          one of the starred themes, not the live one
  optional: "source": "movie night"      shown in the history as "automation (movie night)"
            "notify": true               also send the ntfy theme-change notice

Off unless hooks.token_file (HOOK_TOKEN_FILE) names a file holding the token;
the token is compared in constant time and never logged. The request goes
through the same apply path as a click (allowlist, backend, history), and a
theme set this way holds until the schedule's next switch, like a manual pick.
"""

import hmac
import random
import re
from pathlib import Path

from . import apply, config, ntfy, state, themes

_SOURCE = re.compile(r"^[\w .'-]{1,40}\Z")
RANDOM_FAVOURITE = "random-favourite"


def _token():
    path = config.SETTINGS.get("hooks.token_file") or ""
    if not path:
        return ""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def enabled():
    return bool(_token())


def authorised(header):
    """True if the Authorization header carries the configured token."""
    token = _token()
    if not token or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer "):].strip().encode(), token.encode())


def set_theme(data):
    """(ok, message, status, theme) for an authorised hook request."""
    theme = str(data.get("theme", ""))
    if theme == RANDOM_FAVOURITE:
        live = themes.current_theme()
        pool = [t for t in state.read_favourites() if t != live and t in themes.allowed_themes()]
        if not pool:
            return False, "no favourite themes to pick from (star some in the picker)", 400, ""
        theme = random.choice(pool)
    source = str(data.get("source", "")).strip()
    by = f"automation ({source})" if _SOURCE.match(source) else "automation"
    ok, message, status = apply.apply_theme(theme, by)
    if ok and data.get("notify") is True:
        ntfy.schedule_notify(theme, by, config.picker_url())
    return ok, message, status, theme if ok else ""

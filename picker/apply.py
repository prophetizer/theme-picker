"""Applying a theme to every app: the one path both a person (the handler)
and the day/night schedule go through.

Security: a theme name reaches the backend only after an exact match against
themes.allowed_themes(). (The script backend then calls subprocess with an
argument list, never shell=True.)

How the theme is actually applied is the configured backend's business
(backend.py): traefik-file writes Traefik's config itself, script runs
theme-switcher's set-theme.sh.
"""

import sys

from . import backend, state, themes


def apply_theme(theme, by):
    """(ok, message, status). Records history on success; does not notify."""
    if theme not in themes.allowed_themes():
        return False, f"Rejected: '{theme}' is not a known theme.", 400
    try:
        backend.get().apply(theme)
    except backend.ApplyError as e:
        return False, str(e), 500
    try:
        state.record_history(theme, by)
    except OSError as e:
        print(f"could not record history: {e}", file=sys.stderr, flush=True)
    return True, f"Theme set to '{theme}'.", 200

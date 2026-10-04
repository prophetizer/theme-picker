"""Collections: named sets of themes, to filter the grid and to be the pool
for the theme of the day and rotation.

Built in (worked out from each theme, nothing stored):
  Light, Dark       its mode
  High contrast     every text role at 7:1 (the picker's AAA badge)
  Spring, Summer,   a suggestion from its accent family, mode and name
  Autumn, Winter    (see season()) -- rules, not hand-curated

Your own: theme-collections.json in state_dir, {name: [themes]}, built from a
theme's preview ("Add to collection").
"""

import re

from . import config, state, themes
from .metrics import theme_metrics

COLLECTIONS_FILE = config.STATE_DIR / "theme-collections.json"
SEASONS = ("Spring", "Summer", "Autumn", "Winter")
BUILTIN = ("Light", "Dark", "High contrast") + SEASONS
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}\Z")
MAX_COLLECTIONS, MAX_THEMES = 50, 500

_WORDS = {
    "Spring": r"spring|sakura|cherry|blossom|leaf|meadow|bloom|sage|grass|mint|peach",
    "Summer": r"summer|sun(?!set)|mango|beach|lagoon|ocean|sea\b|tropic|citrus|lemon",
    "Autumn": r"autumn|fall\b|ember|woodland|forest|earth|terracotta|harvest|pumpkin|maple|moss|sunset|dusk",
    "Winter": r"winter|frost|snow|ice|icy|glacier|arctic|nord|boreal|polar|cool",
}


def season(theme, m=None):
    """The seasons a theme suggests (possibly none, possibly two)."""
    m = m or theme_metrics(theme)
    fam, mode = m.get("family"), m.get("mode")
    named = [s for s, words in _WORDS.items() if re.search(words, theme)]
    if named:                                    # a name that says its season wins
        return [s for s in SEASONS if s in named]
    out = []
    if fam in ("green", "pink") and mode == "light":
        out.append("Spring")
    if fam in ("yellow", "orange", "cyan") and mode == "light":
        out.append("Summer")
    if fam in ("orange", "red", "yellow") and mode == "dark":
        out.append("Autumn")
    if fam in ("blue", "neutral") and mode == "dark" and m.get("lum", 1) < 0.02:
        out.append("Winter")
    return [s for s in SEASONS if s in out]


def builtin_members(name):
    out = []
    for t in themes.allowed_themes():
        m = theme_metrics(t)
        if (name == "Light" and m.get("mode") == "light") or (name == "Dark" and m.get("mode") == "dark") \
                or (name == "High contrast" and m.get("high_contrast")) or (name in SEASONS and name in season(t, m)):
            out.append(t)
    return out


def read_user():
    raw = state.read_json(COLLECTIONS_FILE, {})
    if not isinstance(raw, dict):
        return {}
    allowed = set(themes.allowed_themes())
    return {n: [t for t in v if isinstance(t, str) and t in allowed] for n, v in raw.items()
            if isinstance(n, str) and NAME.match(n) and n not in BUILTIN and isinstance(v, list)}


def members(name):
    """The themes in a collection, or None if there is no such collection."""
    if name in BUILTIN:
        return builtin_members(name)
    return read_user().get(name)


def names():
    return list(BUILTIN) + sorted(read_user())


def toggle(name, theme, on):
    """Add a theme to (or take it out of) one of your collections, creating it
    on first add. Returns (ok, message)."""
    name = str(name).strip()
    if name in BUILTIN:
        return False, f"'{name}' is built in and follows the themes themselves."
    if not NAME.match(name):
        return False, "A collection name is 1-40 letters, digits, spaces, - or _."
    if theme not in themes.allowed_themes():
        return False, f"unknown theme '{theme}'"
    with state.STATE_LOCK:
        cols = read_user()
        if name not in cols and len(cols) >= MAX_COLLECTIONS:
            return False, f"{MAX_COLLECTIONS} collections is the limit."
        cur = [t for t in cols.get(name, []) if t != theme]
        if on:
            if len(cur) >= MAX_THEMES:
                return False, f"A collection holds up to {MAX_THEMES} themes."
            cur.append(theme)
        if cur:
            cols[name] = sorted(cur)
        else:
            cols.pop(name, None)                 # an emptied collection goes
        state.write_json(COLLECTIONS_FILE, cols)
    return True, (f"Added {theme} to {name}." if on else f"Took {theme} out of {name}.")


def delete(name):
    with state.STATE_LOCK:
        cols = read_user()
        if cols.pop(str(name), None) is None:
            return False, "No such collection of yours."
        state.write_json(COLLECTIONS_FILE, cols)
    return True, f"Collection '{name}' deleted."

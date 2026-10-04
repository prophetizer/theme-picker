"""The picker's own state files in the theme-switcher directory: applied-theme
history, per-app pins, favourites, custom-theme dates, and the apps list."""

import json
import random
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml  # installed into /tmp/pylibs at container start (see compose file)

from . import backend, config, themes
from .config import SAFE_NAME

APPS_FILE = config.apps_file()
OVERRIDES_FILE = config.STATE_DIR / "theme-overrides.json"
FAVS_FILE = config.STATE_DIR / "theme-favourites.json"
# Themes the viewer never wants offered: left out of the grid (unless "Show
# hidden" is on), Surprise me and the theme of the day.
HIDDEN_FILE = config.STATE_DIR / "theme-hidden.json"
# Single forms hidden on their own (one side of a light/dark pair, the
# other kept): theme names, exact.
HIDDEN_FORMS_FILE = config.STATE_DIR / "theme-hidden-forms.json"
# Thumbs up/down per theme: {theme: 1 | -1}. Random picks (Surprise me, theme
# of the day, rotation, the hook's random-favourite) take a liked theme three
# times as often and never a disliked one; the grid still shows both.
RATINGS_FILE = config.STATE_DIR / "theme-ratings.json"
LIKE_WEIGHT = 3
# App groups: {group name: [app, ...]}, to pin several apps at once.
GROUPS_FILE = config.STATE_DIR / "theme-groups.json"
GROUP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}\Z")
STATE_LOCK = threading.Lock()

# When each custom theme first landed in the themes repo -- written by
# sync-themes.sh from git history (the container has no git). Drives the
# "new" badge. Upstream themes are absent from it and are never "new".
DATES_FILE = config.THEME_DIR / "theme-dates.json"

# Applied-theme history for the "recent" chips. Only the picker writes it:
# set-theme.sh run by hand, and the screenshot capture cycling through every
# theme, do not -- otherwise one capture run would bury the real history.
HISTORY_FILE = config.STATE_DIR / "theme-history.json"
HISTORY_KEEP, HISTORY_CHIPS = 5000, 6
_HISTORY_LOCK = threading.Lock()


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Through backend._atomic_write: a fresh temp file (never a fixed,
    followable name), its mode set (0664: the renderer and the host's jobs,
    other users, read these), then os.replace."""
    backend._atomic_write(path, json.dumps(data, indent=1, sort_keys=True) + "\n")


def theme_dates():
    try:
        return json.loads(DATES_FILE.read_text())
    except (OSError, ValueError):
        return {}


# --- history ---------------------------------------------------------------
def read_history():
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def record_history(theme, by):
    with _HISTORY_LOCK:
        hist = read_history()
        hist.append({"theme": theme, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                     "by": by})
        backend._atomic_write(HISTORY_FILE, json.dumps(hist[-HISTORY_KEEP:], indent=1) + "\n")


def recent_themes(active):
    """Most recent distinct themes, newest first, excluding the live one."""
    seen, out = {active}, []
    for e in reversed(read_history()):
        t = e.get("theme", "")
        if t and t not in seen:
            seen.add(t)
            out.append(e)
        if len(out) >= HISTORY_CHIPS:
            break
    return out


# --- apps, overrides, favourites -----------------------------------------
def load_apps():
    """Themed apps: picker.yml's `apps` if set, else apps.yml. Each gets its
    theme_app (default: name), host (default: name) and, if given, a full
    url (dropped unless http(s)). apps.yml can be writable by the picker's
    container, so names are checked again where they become middleware names
    (renderer._apps) and hosts where they become requests (coverage)."""
    apps = config.SETTINGS["apps"]
    if apps is None:
        try:
            apps = (yaml.safe_load(APPS_FILE.read_text()) or {}).get("apps", [])
        except (OSError, yaml.YAMLError, AttributeError):
            return []
    out = []
    for a in apps if isinstance(apps, list) else []:
        if not isinstance(a, dict) or "name" not in a:
            continue
        app = {"name": a["name"], "theme_app": a.get("theme_app", a["name"]),
               "host": a.get("host", a["name"]), "url": a.get("url") or "",
               "addons": [x for x in (a.get("addons") or []) if isinstance(x, str)]}
        if app["url"] and not (isinstance(app["url"], str) and config._URL.match(app["url"])):
            app["url"] = ""
        out.append(app)
    return out


def read_overrides():
    names = {a["name"] for a in load_apps()}
    raw = read_json(OVERRIDES_FILE, {})
    return {k: v for k, v in raw.items()
            if k in names and isinstance(v, str) and SAFE_NAME.match(v)}


def set_override(app, theme):
    ok, msg = set_overrides([app], theme)
    if not ok:
        return ok, msg
    return True, (f"{app} pinned to {theme}" if theme else f"{app} follows the main theme again")


def set_overrides(apps, theme):
    """Pin every app in `apps` to `theme` ("" = follow the live theme again),
    in one write and one proxy update. Returns (ok, message)."""
    known = {a["name"] for a in load_apps()}
    unknown = [a for a in apps if a not in known]
    if unknown or not apps:
        return False, f"unknown app '{unknown[0]}'" if unknown else "no apps given"
    if theme and theme not in themes.allowed_themes():
        return False, f"unknown theme '{theme}'"
    with STATE_LOCK:
        cur = read_overrides()
        for app in apps:
            if theme:
                cur[app] = theme
            else:
                cur.pop(app, None)
        write_json(OVERRIDES_FILE, cur)
        try:
            backend.get().set_pins()
        except backend.ApplyError as e:
            return False, str(e)
    n = len(apps)
    return True, (f"{n} app{'s' if n != 1 else ''} pinned to {theme}" if theme
                  else f"{n} app{'s' if n != 1 else ''} follow the main theme again")


# --- app groups --------------------------------------------------------------
def read_groups():
    """{name: [apps]}: only valid names and apps that still exist."""
    known = {a["name"] for a in load_apps()}
    raw = read_json(GROUPS_FILE, {})
    if not isinstance(raw, dict):
        return {}
    return {n: [a for a in v if a in known] for n, v in raw.items()
            if isinstance(n, str) and GROUP_NAME.match(n) and isinstance(v, list)}


def save_group(name, apps):
    name = str(name).strip()
    if not GROUP_NAME.match(name):
        return False, "A group name is 1-40 letters, digits, spaces, - or _."
    known = {a["name"] for a in load_apps()}
    apps = sorted({str(a) for a in apps if str(a) in known}) if isinstance(apps, list) else []
    if not apps:
        return False, "Pick at least one app for the group."
    with STATE_LOCK:
        groups = read_groups()
        if name not in groups and len(groups) >= 50:
            return False, "50 groups is the limit."
        groups[name] = apps
        write_json(GROUPS_FILE, groups)
    return True, f"Group '{name}' saved: {', '.join(apps)}."


def delete_group(name):
    with STATE_LOCK:
        groups = read_groups()
        if groups.pop(str(name), None) is None:
            return False, "No such group."
        write_json(GROUPS_FILE, groups)
    return True, f"Group '{name}' deleted (its apps keep their pins)."


def pin_group(name, theme):
    apps = read_groups().get(str(name))
    if not apps:
        return False, "No such group, or it has no apps left."
    return set_overrides(apps, theme)


# --- ratings -------------------------------------------------------------------
def read_ratings():
    raw = read_json(RATINGS_FILE, {})
    if not isinstance(raw, dict):
        return {}
    return {t: r for t, r in raw.items() if isinstance(t, str) and SAFE_NAME.match(t) and r in (1, -1)}


def set_rating(theme, rating):
    if theme not in themes.allowed_themes() or rating not in (-1, 0, 1):
        return False
    with STATE_LOCK:
        cur = read_ratings()
        if rating:
            cur[theme] = rating
        else:
            cur.pop(theme, None)
        write_json(RATINGS_FILE, cur)
    return True


def pick(pool, rng=random):
    """A random theme from `pool`: liked ones LIKE_WEIGHT times as likely,
    disliked ones never. None if nothing is left."""
    ratings = read_ratings()
    pool = [t for t in pool if ratings.get(t) != -1]
    if not pool:
        return None
    return rng.choices(pool, weights=[LIKE_WEIGHT if ratings.get(t) == 1 else 1 for t in pool])[0]


def read_favourites():
    return [t for t in read_json(FAVS_FILE, []) if isinstance(t, str) and SAFE_NAME.match(t)]


def set_favourite(theme, on):
    if theme not in themes.allowed_themes():
        return False
    with STATE_LOCK:
        favs = [t for t in read_favourites() if t != theme]
        if on:
            favs.append(theme)
        write_json(FAVS_FILE, sorted(favs))
    return True


def read_hidden():
    return [t for t in read_json(HIDDEN_FILE, []) if isinstance(t, str) and SAFE_NAME.match(t)]


def _lead(theme):
    """The theme a light/dark pair is filed under (the tile that carries it)."""
    for lead, twin in themes.variant_pairs().items():
        if twin == theme:
            return lead
    return theme


def hidden_set():
    """Every theme hidden, both forms of each pair: hiding is per pair (the
    grid hides a tile and its twin together), so the random picks must skip
    the twin too -- they used to skip only the exact name, and could still
    land on dracula-light after Dracula was hidden."""
    pairs = themes.variant_pairs()
    out = set(read_hidden_forms())
    for t in read_hidden():
        out.add(t)
        lead = _lead(t)
        out.add(lead)
        if lead in pairs:
            out.add(pairs[lead])
    return out


def read_hidden_forms():
    return [t for t in read_json(HIDDEN_FORMS_FILE, []) if isinstance(t, str) and SAFE_NAME.match(t)]


def set_hidden_form(theme, on):
    """Hide (or show again) one form of a pair only -- e.g. edge-dark, keeping
    edge-light. Only a theme that is part of a pair can be hidden this way;
    a single theme is hidden with set_hidden()."""
    pairs = themes.variant_pairs()
    if theme not in themes.allowed_themes() or theme not in set(pairs) | set(pairs.values()):
        return False
    with STATE_LOCK:
        forms = [t for t in read_hidden_forms() if t != theme]
        if on:
            forms.append(theme)
        write_json(HIDDEN_FORMS_FILE, sorted(forms))
    return True


def set_hidden(theme, on):
    if theme not in themes.allowed_themes():
        return False
    theme = _lead(theme)                        # a twin is hidden with its pair
    with STATE_LOCK:
        hidden = [t for t in read_hidden() if t != theme]
        if on:
            hidden.append(theme)
        write_json(HIDDEN_FILE, sorted(hidden))
    return True


# --- usage stats -------------------------------------------------------------
def _parse_at(s):
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:            # early entries were naive UTC (no TZ set)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def usage_stats():
    """Applies and time-on-screen per theme, from the picker's history.
    Only picker changes are logged, so a screenshot run's cycling is not
    counted -- the theme picked before it keeps accruing time through it."""
    hist = [(e.get("theme"), _parse_at(e.get("at"))) for e in read_history()]
    hist = [(t, at) for t, at in hist if t and at]
    if not hist:
        return None
    applies, secs = Counter(t for t, _ in hist), Counter()
    now = datetime.now().astimezone()
    for i, (t, start) in enumerate(hist):
        end = hist[i + 1][1] if i + 1 < len(hist) else now
        secs[t] += max(0.0, (end - start).total_seconds())
    return {"since": hist[0][1].strftime("%Y-%m-%d %H:%M"), "changes": len(hist),
            "distinct": len(applies), "by_time": secs.most_common(10),
            "by_count": applies.most_common(10), "applies": applies, "secs": secs}


RANDOM_PICKS = ("schedule (theme of the day)", "schedule (rotation)")


def rating_stats():
    """Liked and disliked themes with how often each was applied, and how the
    random picks (theme of the day, rotation) split between liked and
    unrated themes since ratings exist."""
    ratings = read_ratings()
    if not ratings:
        return None
    use = usage_stats() or {"applies": Counter(), "secs": Counter()}
    rows = lambda r: sorted(((t, use["applies"].get(t, 0), use["secs"].get(t, 0.0))
                             for t, v in ratings.items() if v == r), key=lambda x: (-x[1], x[0]))
    picks = Counter()
    for e in read_history():
        if e.get("by") in RANDOM_PICKS and isinstance(e.get("theme"), str):
            picks[{1: "liked", -1: "disliked"}.get(ratings.get(e["theme"]), "unrated")] += 1
    return {"liked": rows(1), "disliked": rows(-1), "picks": dict(picks)}

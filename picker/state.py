"""The picker's own state files in the theme-switcher directory: applied-theme
history, per-app pins, favourites, custom-theme dates, and the apps list."""

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml  # installed into /tmp/pylibs at container start (see compose file)

from . import backend, config, themes
from .config import SAFE_NAME

APPS_FILE = config.apps_file()
OVERRIDES_FILE = config.THEME_DIR / "theme-overrides.json"
FAVS_FILE = config.THEME_DIR / "theme-favourites.json"
STATE_LOCK = threading.Lock()

# When each custom theme first landed in homelab-themes -- written by
# sync-themes.sh from git history (the container has no git). Drives the
# "new" badge. Upstream themes are absent from it and are never "new".
DATES_FILE = config.THEME_DIR / "theme-dates.json"

# Applied-theme history for the "recent" chips. Only the picker writes it:
# set-theme.sh run by hand, and the screenshot capture cycling through every
# theme, do not -- otherwise one capture run would bury the real history.
HISTORY_FILE = config.THEME_DIR / "theme-history.json"
HISTORY_KEEP, HISTORY_CHIPS = 5000, 6
_HISTORY_LOCK = threading.Lock()


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


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
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist[-HISTORY_KEEP:], indent=1) + "\n")
        tmp.replace(HISTORY_FILE)


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
    """Themed apps from apps.yml, with the public hostname each lives at."""
    try:
        apps = (yaml.safe_load(APPS_FILE.read_text()) or {}).get("apps", [])
    except (OSError, yaml.YAMLError):
        return []
    return [{"name": a["name"], "theme_app": a.get("theme_app", a["name"]),
             "host": a.get("host", a["name"]),
             "addons": [x for x in (a.get("addons") or []) if isinstance(x, str)]}
            for a in apps if "name" in a]


def read_overrides():
    names = {a["name"] for a in load_apps()}
    raw = read_json(OVERRIDES_FILE, {})
    return {k: v for k, v in raw.items()
            if k in names and isinstance(v, str) and SAFE_NAME.match(v)}


def set_override(app, theme):
    if app not in {a["name"] for a in load_apps()}:
        return False, f"unknown app '{app}'"
    if theme and theme not in themes.allowed_themes():
        return False, f"unknown theme '{theme}'"
    with STATE_LOCK:
        cur = read_overrides()
        if theme:
            cur[app] = theme
        else:
            cur.pop(app, None)
        write_json(OVERRIDES_FILE, cur)
        try:
            backend.get().set_pins()
        except backend.ApplyError as e:
            return False, str(e)
    return True, (f"{app} pinned to {theme}" if theme else f"{app} follows the main theme again")


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
            "by_count": applies.most_common(10)}

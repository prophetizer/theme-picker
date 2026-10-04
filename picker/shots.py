"""Real screenshots of each theme across the apps, written by
capture-theme-screenshots.sh: per-app/<app>_<theme>.png full size and
thumbs/<app>_<theme>.jpg for the lightbox grid. Gitignored, regenerable."""

import os
import re

from . import config, state

SHOT_DIR = config.THEME_DIR / "screenshots"
SHOT_NAME = re.compile(r"^([a-z0-9-]+)_([a-z0-9.-]+)\Z")


def screenshot_apps():
    """The apps screenshots are taken of, in lightbox order: picker.yml's
    screenshots.apps, or every themed app when that is empty."""
    return list(config.SCREENSHOT_APPS) or [a["name"] for a in state.load_apps()]


KINDS = {"thumb": ("thumbs", ".jpg", "image/jpeg"),
         "full": ("per-app", ".png", "image/png")}


_INDEX = {}


def _names(d, suffix):
    try:
        with os.scandir(d) as it:
            return {e.name[:-len(suffix)] for e in it if e.name.endswith(suffix) and e.is_file()}
    except OSError:
        return set()


def screenshot_index():
    """{theme: [apps...]} for every theme that has lightbox thumbnails.
    Two directory scans, kept until either directory changes (the capture
    saves by rename, which updates the directory's mtime): globbing and
    checking ~4,000 files took 0.4 s of every page render."""
    thumbs, full = SHOT_DIR / "thumbs", SHOT_DIR / "per-app"
    apps = tuple(screenshot_apps())
    try:
        key = (str(SHOT_DIR), thumbs.stat().st_mtime_ns, full.stat().st_mtime_ns, apps)
    except OSError:
        return {}
    if _INDEX.get("key") == key:
        return _INDEX["value"]
    idx = {}
    for stem in _names(thumbs, ".jpg") & _names(full, ".png"):
        m = SHOT_NAME.match(stem)
        if m:
            idx.setdefault(m.group(2), []).append(m.group(1))
    rank = {a: i for i, a in enumerate(apps)}
    value = {t: sorted(a, key=lambda x: (rank.get(x, 99), x)) for t, a in idx.items()}
    _INDEX.clear()
    _INDEX.update(key=key, value=value)
    return value


def shot_file(path):
    """(file, content type) for a /shots/ URL path, or None to refuse it.

    Only /shots/thumb/<app>_<theme>.jpg and /shots/full/<app>_<theme>.png,
    the name must match SHOT_NAME, and the resolved file must sit directly
    inside its directory -- so no path in the URL can reach anything but a
    capture output."""
    parts = path.split("/")
    if len(parts) != 4 or parts[2] not in KINDS:
        return None
    sub, ext, ctype = KINDS[parts[2]]
    name = parts[3]
    if not name.endswith(ext) or not SHOT_NAME.match(name[:-len(ext)]):
        return None
    folder = (SHOT_DIR / sub).resolve()
    f = (folder / name).resolve()
    if f.parent != folder or not f.is_file():
        return None
    return f, ctype


# --- the screenshot capture's progress ------------------------------------------
STATUS_FILE = config.STATE_DIR / "capture-status.json"
STALE_MINUTES = 15


def capture_status(now=None):
    """The capture's last status (written by capture_theme_screenshots.py),
    with minutes left estimated from its pace. A 'running' status not updated
    for STALE_MINUTES is reported as stopped: the run died without saying."""
    from datetime import datetime
    st = state.read_json(STATUS_FILE, {})
    if not isinstance(st, dict) or not st:
        return {"running": False}
    now = now or datetime.now().astimezone()
    try:
        updated = datetime.strptime(st.get("updated", ""), "%Y-%m-%dT%H:%M:%S%z")
        started = datetime.strptime(st.get("started", ""), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return {"running": False}
    out = {k: st.get(k) for k in ("running", "themes", "index", "theme", "restore", "shots", "done",
                                  "finished", "failed", "skipped", "minutes")}
    if st.get("running") and (now - updated).total_seconds() > STALE_MINUTES * 60:
        out.update(running=False, stalled=True)
    if out.get("running"):
        done, shots = st.get("done") or 0, st.get("shots") or 0
        elapsed = (now - started).total_seconds()
        out["minutes_left"] = round(elapsed / done * (shots - done) / 60) if done else None
    return out


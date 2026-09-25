"""Real screenshots of each theme across the apps, written by
capture-theme-screenshots.sh: per-app/<app>_<theme>.png full size and
thumbs/<app>_<theme>.jpg for the lightbox grid. Gitignored, regenerable."""

import re

from . import config

SHOT_DIR = config.THEME_DIR / "screenshots"
SHOT_NAME = re.compile(r"^([a-z0-9-]+)_([a-z0-9.-]+)$")
# Screenshot apps, in lightbox order: picker.yml's screenshots.apps.
APP_ORDER = config.SCREENSHOT_APPS
KINDS = {"thumb": ("thumbs", ".jpg", "image/jpeg"),
         "full": ("per-app", ".png", "image/png")}


def screenshot_index():
    """{theme: [apps...]} for every theme that has lightbox thumbnails."""
    idx = {}
    for p in (SHOT_DIR / "thumbs").glob("*.jpg"):
        m = SHOT_NAME.match(p.stem)
        if m and (SHOT_DIR / "per-app" / f"{p.stem}.png").is_file():
            idx.setdefault(m.group(2), []).append(m.group(1))
    rank = {a: i for i, a in enumerate(APP_ORDER)}
    return {t: sorted(apps, key=lambda a: (rank.get(a, 99), a)) for t, apps in idx.items()}


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

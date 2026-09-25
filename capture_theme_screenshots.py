#!/usr/bin/env python3
"""Capture real screenshots of themed apps, one set per theme, for the picker.

For each theme: switch the live theme with set-theme.sh, give Traefik's file
provider time to reload, then load each app in headless Chrome and screenshot
it. The theme picker shows these in its lightbox.

THIS CHANGES THE LIVE THEME while it runs -- every themed app in the homelab
restyles once per theme. The theme that was live at the start is restored on
exit, including Ctrl-C and SIGTERM.

Usage (run through the wrapper so the pinned venv is used):
    ./capture-theme-screenshots.sh                  # every theme
    ./capture-theme-screenshots.sh aurora ember     # just these
    DRY_RUN=1 ./capture-theme-screenshots.sh        # print the plan
    FORCE=1 ./capture-theme-screenshots.sh          # re-shoot existing files
    APPS="dozzle forgejo" ./capture-theme-screenshots.sh

The domain, theme-park URL, app list and theme-switcher directory come from
picker.yml (see picker.example.yml), the same file the picker reads.

Resumable: a shot that already exists is skipped unless FORCE=1, so an
interrupted run picks up where it stopped.

Why Playwright rather than `google-chrome --screenshot`: that CLI can either
wait for the page to go idle (--virtual-time-budget) or shoot at the load
event (--timeout). Dozzle streams container logs over a connection that never
closes, so it never goes idle -- the first mode hung until killed on every
theme. The second shot a skeleton page before data or the stylesheet arrived.
"Load, wait a few seconds, shoot" is what every app here actually needs, and
the CLI cannot express it.
"""
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

from picker import backend, config
from playwright.sync_api import sync_playwright

# The theme-switcher directory holding set-theme.sh, current-theme.env,
# themes-src/ and screenshots/: theme_switcher_dir in picker.yml, or
# THEME_SWITCHER_DIR, else the parent of this repo's checkout.
THEME_DIR = config.THEME_DIR
OUT_DIR = Path(os.environ.get("OUT_DIR", THEME_DIR / "screenshots"))
SHOTS, THUMBS = OUT_DIR / "per-app", OUT_DIR / "thumbs"
DOMAIN = config.DOMAIN
THEME_PARK = config.base_url()
if not (DOMAIN and THEME_PARK):
    sys.exit("capture: set `domain` (and `theme_park_url`, or BASE_URL in config.env) "
             "in picker.yml -- see picker.example.yml")
WIDTH, HEIGHT = 1920, 1010
THUMB_W = 480
SETTLE_MS = int(os.environ.get("SETTLE_MS", "4000"))
RELOAD_WAIT = 4        # seconds; Traefik's file provider picks up themes.yml in ~1-2s

# Apps that render a themed page without a login wall. Probed with
# `Accept: text/html` -- the traefik-themepark plugin only injects its <link>
# for HTML requests, so a probe without that header reports every app as
# unthemed and looks exactly like theming being broken.
APPS = config.SCREENSHOT_APPS          # screenshots.apps in picker.yml, or APPS


def all_themes():
    """Every theme theme-park serves -- official, community and ours."""
    with urllib.request.urlopen(f"{THEME_PARK}/themes.json", timeout=15) as r:
        data = json.load(r)
    # Names become file names and a set-theme.sh argument: plain names only.
    names = {e["url"].rsplit("/", 1)[-1].split(".css")[0] for e in data["all-themes"].values()}
    return sorted(n for n in names if config.SAFE_NAME.match(n) and ".." not in n)


def current_theme():
    return backend.read_current(config.CONFIG_FILE)


def set_theme(name, ignore_overrides=True):
    """Switch the live theme through the picker's configured backend (the
    same one the picker uses). While capturing, per-app pins are ignored so a
    pinned app still cycles through every theme; the final restore re-applies
    them. Raises backend.ApplyError on failure."""
    backend.get().apply(name, ignore_pins=ignore_overrides)


CUSTOM_DIR = THEME_DIR / "themes-src" / "themes"


def needs_shot(app, theme, force=False):
    """Missing, or older than the theme's own file -- so a custom theme that is
    edited (or saved again from the picker's editor) gets re-shot by the
    nightly run instead of showing its old colours forever. Upstream themes
    have no local file to compare against; they only change with the image."""
    shot = SHOTS / f"{app}_{theme}.png"
    if force or not shot.exists():
        return True
    src = CUSTOM_DIR / f"{theme}.css"
    return src.exists() and src.stat().st_mtime > shot.stat().st_mtime


def make_thumb(src, dst):
    im = Image.open(src).convert("RGB")
    im.resize((THUMB_W, round(im.height * THUMB_W / im.width)), Image.LANCZOS).save(
        dst, "JPEG", quality=82, optimize=True)


def main():
    themes = sys.argv[1:] or all_themes()
    force = os.environ.get("FORCE") == "1"
    todo = [(t, a) for t in themes for a in APPS if needs_shot(a, t, force)]
    print(f"==> {len(themes)} themes x {len(APPS)} apps; {len(todo)} shots to take "
          f"({len(themes) * len(APPS) - len(todo)} already exist)")
    if os.environ.get("DRY_RUN") == "1":
        print("    themes:", " ".join(themes))
        print("    apps:  ", " ".join(APPS))
        print("    out:   ", OUT_DIR)
        return 0

    original = current_theme()
    if not original:
        sys.exit("could not read the current theme; refusing to run")
    print(f"==> Live theme is '{original}'; it will be restored when this finishes.")

    def on_signal(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, on_signal)

    SHOTS.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    failed, mismatched = [], []
    # Someone may use the picker while this runs -- it happened on the first
    # full run, and at the end the script restored the theme from its own
    # start, silently discarding the choice they had just made. So before
    # every switch, and before the final restore, check the live theme is
    # still the one this script last set. If not, a person changed it, and
    # THAT is what gets restored. (Their clicks cannot pollute the gallery:
    # each shot is checked against the intended theme's stylesheet.)
    restore_to = {"theme": original, "last_set": None}

    def note_human_change():
        live = current_theme()
        if restore_to["last_set"] and live and live != restore_to["last_set"]:
            print(f"==> Live theme was changed to '{live}' by someone else; "
                  f"will restore that instead of '{restore_to['theme']}'.", flush=True)
            restore_to["theme"] = live
    started = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
            for i, theme in enumerate(themes, 1):
                pending = [a for a in APPS if needs_shot(a, theme, force)]
                if not pending:
                    continue
                elapsed = time.time() - started
                print(f"==> [{i}/{len(themes)}] {theme}  ({elapsed/60:.0f} min elapsed)", flush=True)
                note_human_change()
                set_theme(theme)
                restore_to["last_set"] = theme
                time.sleep(RELOAD_WAIT)
                # A FRESH context per theme, i.e. an empty HTTP cache. One
                # shared context served Guacamole's cached HTML -- carrying the
                # FIRST theme's injected stylesheet link -- for every theme
                # after it. The theme check below caught it and refused the
                # shots, but only a clean cache actually gets them.
                ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
                for app in pending:
                    out = SHOTS / f"{app}_{theme}.png"
                    page = ctx.new_page()
                    try:
                        # domcontentloaded, NOT networkidle: Dozzle never goes idle.
                        page.goto(f"https://{app}.{DOMAIN}/", wait_until="domcontentloaded",
                                  timeout=30000)
                        page.wait_for_timeout(SETTLE_MS)
                        # Refuse to record a shot of the WRONG theme. If Traefik
                        # had not reloaded yet the page carries the previous
                        # theme's stylesheet, and the lightbox would lie.
                        href = page.evaluate(
                            "() => (document.querySelector('link[href*=\"theme-park\"]') || {}).href || ''")
                        if f"/{theme}.css" not in href:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                            page.wait_for_timeout(SETTLE_MS)
                            href = page.evaluate(
                                "() => (document.querySelector('link[href*=\"theme-park\"]') || {}).href || ''")
                        if f"/{theme}.css" not in href:
                            mismatched.append(f"{app}_{theme}")
                            print(f"    {app:11} SKIPPED (page has {href.rsplit('/', 1)[-1] or 'no theme link'})")
                            continue
                        page.screenshot(path=str(out))
                        make_thumb(out, THUMBS / f"{app}_{theme}.jpg")
                        print(f"    {app:11} ok")
                    except Exception as e:
                        failed.append(f"{app}_{theme}")
                        detail = (str(e).splitlines() or [""])[0][:140]
                        print(f"    {app:11} FAILED ({type(e).__name__}: {detail})")
                        out.unlink(missing_ok=True)
                    finally:
                        page.close()
                ctx.close()
            browser.close()
    except KeyboardInterrupt as e:
        print(f"\n==> Interrupted ({e}); re-run to resume.")
    finally:
        note_human_change()
        target = restore_to["theme"]
        print(f"==> Restoring '{target}'")
        try:
            set_theme(target, ignore_overrides=False)
        except Exception:
            print(f"!! RESTORE FAILED -- run: {THEME_DIR / 'set-theme.sh'} {target}", file=sys.stderr)

    # Thumbnails for any full-size shot that predates thumbnailing.
    for png in SHOTS.glob("*.png"):
        jpg = THUMBS / (png.stem + ".jpg")
        if not jpg.exists():
            make_thumb(png, jpg)

    print(f"==> Done in {(time.time() - started)/60:.0f} min. "
          f"{len(list(SHOTS.glob('*.png')))} shots on disk.")
    if failed:
        print(f"    failed ({len(failed)}):", " ".join(failed))
    if mismatched:
        print(f"    wrong theme on page, not saved ({len(mismatched)}):", " ".join(mismatched))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

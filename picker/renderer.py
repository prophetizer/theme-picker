"""Writes Traefik's themes.yml from the picker's state.

    python3 -m picker.renderer          # watch, re-render on every change
    python3 -m picker.renderer --once   # render once and exit

For `backend.type: state`. The picker then only records what it wants (the
live theme, IGNORE_PINS, per-app pins) in state_dir, and this -- run as its
own container with no network, the picker's state mounted read-only, and
write access to Traefik's dynamic config -- is the one thing that writes
proxy config. So the container people can reach (the picker) can no longer
define routers, drop an auth middleware or point a host somewhere else: the
most it can do is choose theme names, which are checked here again.

What it reads, and who can write it:
  state_dir/current-theme.env, theme-overrides.json   the picker
  apps.yml, config.env (BASE_URL, OUTPUT_FILE)        the host only

It polls those files once a second and writes only when the output would
change, through the same atomic write as the traefik-file backend.
"""

import argparse
import re
import sys
import time

from . import backend, config, state

POLL_SECONDS = 1.0
_APP = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\Z")


def _apps():
    """apps.yml's apps, refusing any name that isn't a plain id: they become
    middleware names and theme.park paths in a file Traefik loads."""
    out = []
    for a in state.load_apps():
        if _APP.match(str(a["name"])) and _APP.match(str(a["theme_app"])) \
                and all(_APP.match(x) for x in a["addons"]):
            out.append(a)
        else:
            print(f"renderer: skipping app {a['name']!r}: not a plain name", file=sys.stderr, flush=True)
    return out


def writer():
    return backend.TraefikFile(output_file=config.output_file(), state_file=config.CONFIG_FILE,
                               default_theme=config.SETTINGS["backend.default_theme"],
                               apps=_apps, pins=state.read_overrides, base_url=config.base_url)


def render():
    """Write themes.yml if it differs from what the state asks for.
    Returns True if the file was written."""
    w = writer()
    theme = backend.read_current(config.CONFIG_FILE) or w.default_theme
    if not config.SAFE_NAME.match(theme):
        raise backend.ApplyError(f"refusing theme {theme!r}: not a plain name")
    text = w.text(theme, backend.read_ignore_pins(config.CONFIG_FILE))
    try:
        if w.output_file.read_text() == text:
            return False
    except OSError:
        pass
    w._write(theme, backend.read_ignore_pins(config.CONFIG_FILE))
    return True


def _signature():
    sig = []
    for p in (config.CONFIG_FILE, state.OVERRIDES_FILE, state.APPS_FILE, config.SETTINGS_FILE):
        try:
            st = p.stat()
            sig.append((st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append(None)
    return tuple(sig)


def watch():
    last = None
    while True:
        sig = _signature()
        if sig != last:
            try:
                if render():
                    print(f"renderer: wrote {config.output_file()} for "
                          f"{backend.read_current(config.CONFIG_FILE) or 'the default theme'}", flush=True)
                last = sig
            except (backend.ApplyError, ValueError, OSError) as e:
                print(f"renderer: {e}", file=sys.stderr, flush=True)
                last = sig                         # wait for the next change, don't spin
        time.sleep(POLL_SECONDS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--once", action="store_true", help="render once and exit")
    args = ap.parse_args(argv)
    if args.once:
        try:
            print("wrote" if render() else "unchanged", config.output_file())
        except (backend.ApplyError, ValueError, OSError) as e:
            sys.exit(f"renderer: {e}")
        return
    print(f"renderer: watching {config.STATE_DIR} -> {config.output_file()}", flush=True)
    watch()


if __name__ == "__main__":
    main()

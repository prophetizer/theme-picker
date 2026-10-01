"""How a theme actually gets applied: the one seam between the picker and the
reverse proxy.

A backend does two things: make a theme the live one (apply), and rewrite the
proxy's config for the current theme plus per-app pins (set_pins). Everything
else -- the allowlist, history, the schedule, the page -- is the same whichever
backend is configured (`backend.type` in picker.yml).

traefik-file (the default) needs nothing but this package: it records the live
theme in current-theme.env and writes one traefik-themepark middleware per app
into a file Traefik's file provider watches -- the same files, format and
atomic write that theme-switcher's set-theme.sh + generate-themes-yml.py
produce, so the two can be used side by side.

script delegates to those two scripts instead, for a setup that wants its own
hooks around a change.

state only records the change -- the live theme and whether pins are ignored,
in current-theme.env -- and leaves the proxy config to picker.renderer, run
in a separate container that alone can write Traefik's dynamic config. The
picker's own container then cannot write proxy config at all: a compromised
picker can pick theme names, nothing more.

Callers validate the theme against the allowlist first; backends re-check
that it is a plain name anyway, since the name ends up in a file Traefik
loads.
"""

import os
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import yaml

from . import config

_LOCK = threading.Lock()


class ApplyError(Exception):
    """Applying failed; the message is safe to show to the person who asked."""


def _plain(theme):
    if not isinstance(theme, str) or not config.SAFE_NAME.match(theme):
        raise ApplyError(f"not a plain theme name: {theme!r}")
    return theme


def _atomic_write(path, text, mode=0o664):
    """Write via a temp file in the same directory + os.replace(): a watcher
    (Traefik's file provider) only ever sees the old or the new file, never a
    truncated one -- a plain open(path, "w") briefly 502'd every themed
    router when this was done by the generator.

    mkstemp() makes the file 0600, so it is widened to `mode` first: the
    state file is written by the picker and read by the renderer (another
    user), and 0600 left the renderer falling back to the default theme."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


STATE_MAX = 64 * 1024


def _read_state(path):
    """The state file's text, or None if it is missing or not a plain file.

    The file sits in a directory the picker's container can write, and the
    nightly capture calls write_current() on the HOST. A plain read followed
    a symlink planted there, and write_current() then wrote the target's
    content back as a regular file the container could read -- a copy of any
    host file (a secret, ~/.ssh/...). O_NOFOLLOW refuses a link, O_NONBLOCK
    keeps a FIFO from hanging the job, and the size cap bounds the read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:                                  # ELOOP: a symlink
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        return f.read(STATE_MAX).decode("utf-8", "replace")


def _read_key(state_file, key):
    for line in (_read_state(state_file) or "").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def read_current(state_file):
    """CURRENT_THEME from the state file, or "" if absent."""
    return _read_key(state_file, "CURRENT_THEME")


def read_ignore_pins(state_file):
    """IGNORE_PINS=1 in the state file: the screenshot capture's "every app
    shows this theme, pinned or not", for the renderer to honour."""
    return _read_key(state_file, "IGNORE_PINS") == "1"


def write_current(state_file, theme, ignore_pins=None):
    """Set CURRENT_THEME (and IGNORE_PINS when given), keeping any other lines
    (comments) as they are -- what set-theme.sh does with sed."""
    path = Path(state_file)
    lines = (_read_state(path) or "").splitlines()
    want = {"CURRENT_THEME": theme}
    if ignore_pins is not None:
        want["IGNORE_PINS"] = "1" if ignore_pins else "0"
    for key, value in want.items():
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    _atomic_write(path, "\n".join(lines) + "\n")


HEADER = (
    "# AUTO-GENERATED by the theme picker's traefik-file backend -- do not edit\n"
    "# by hand. Change the theme in the picker (or theme-switcher's set-theme.sh,\n"
    "# which writes the same file); change which apps are themed in apps.yml.\n"
    "#\n"
    "# Each app's OTHER middlewares (auth, CSP headers, etc.) live in that\n"
    "# app's own router config, chained alongside <name>-theme@file in its\n"
    "# router's middlewares -- this file only defines the theme-park plugin\n"
    "# blocks themselves.\n"
)


def render_middlewares(apps, theme, pins, base_url):
    """The Traefik dynamic config, as a dict: one themepark middleware per
    app, the pinned theme where there is one, else `theme`."""
    middlewares = {}
    for app in apps:
        cfg = {"app": app["theme_app"], "theme": pins.get(app["name"], theme), "baseUrl": base_url}
        if app.get("addons"):
            cfg["addons"] = list(app["addons"])
        middlewares[f"{app['name']}-theme"] = {"plugin": {"themepark": cfg}}
    return {"http": {"middlewares": middlewares}}


class TraefikFile:
    name = "traefik-file"

    def __init__(self, output_file, state_file, default_theme, apps, pins, base_url):
        # apps, pins and base_url are callables, read at each write: apps.yml,
        # the pins file and config.env can all change while the picker runs.
        self.output_file, self.state_file = Path(output_file), Path(state_file)
        self.default_theme = default_theme
        self._apps, self._pins, self._base_url = apps, pins, base_url

    def apply(self, theme, ignore_pins=False):
        theme = _plain(theme)
        with _LOCK:
            self._write(theme, ignore_pins)          # proxy first: a failure leaves state alone
            write_current(self.state_file, theme)

    def set_pins(self):
        with _LOCK:
            self._write(read_current(self.state_file) or self.default_theme, False)

    def text(self, theme, ignore_pins):
        """The whole themes.yml for this theme and the current pins."""
        base = self._base_url()
        if not base:
            raise ApplyError("no theme-park URL (theme_park_url in picker.yml, or BASE_URL in config.env)")
        apps = self._apps()
        if not apps:
            raise ApplyError("no themed apps defined (apps.yml)")
        pins = {} if ignore_pins else {k: _plain(v) for k, v in self._pins().items()}
        body = yaml.safe_dump(render_middlewares(apps, theme, pins, base),
                              default_flow_style=False, sort_keys=False)
        return HEADER + body

    def _write(self, theme, ignore_pins):
        text = self.text(theme, ignore_pins)
        try:
            _atomic_write(self.output_file, text, mode=0o644)
        except OSError as e:
            raise ApplyError(f"could not write {self.output_file.name}: {e.strerror or e}")


class Script:
    name = "script"

    def __init__(self, set_theme, generator, cwd):
        self.set_theme, self.generator, self.cwd = Path(set_theme), Path(generator), Path(cwd)

    def _run(self, argv, what, ignore_pins=False):
        env = dict(os.environ, THEME_IGNORE_OVERRIDES="1" if ignore_pins else "0")
        r = subprocess.run(argv, cwd=self.cwd, env=env, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            # The detail goes to the container log, not to the browser: script
            # errors can carry host paths and environment details.
            print(f"{what} failed (exit {r.returncode}): {r.stderr.strip()[-2000:]}", file=sys.stderr, flush=True)
            raise ApplyError(f"{what} failed (exit {r.returncode}); the details are in the picker's log")

    def apply(self, theme, ignore_pins=False):
        # An argument list, never shell=True: the name cannot become a command.
        self._run(["/bin/bash", str(self.set_theme), _plain(theme)], "set-theme.sh", ignore_pins)

    def set_pins(self):
        self._run([sys.executable, str(self.generator)], "generator")


class StateOnly:
    """Records the change for picker.renderer to apply; writes no proxy config."""
    name = "state"

    def __init__(self, state_file):
        self.state_file = Path(state_file)

    def apply(self, theme, ignore_pins=False):
        theme = _plain(theme)
        with _LOCK:
            write_current(self.state_file, theme, ignore_pins=ignore_pins)

    def set_pins(self):
        pass                    # the pins file IS the state; the renderer watches it


def get():
    """The configured backend, built from current settings."""
    from . import state                            # state imports this module
    s = config.SETTINGS
    if s["backend.type"] == "state":
        return StateOnly(config.CONFIG_FILE)
    if s["backend.type"] == "script":
        return Script(config.SET_THEME_SCRIPT, config.THEME_DIR / "generate-themes-yml.py", config.THEME_DIR)
    try:
        output_file = config.output_file()
    except ValueError as e:                        # refused, e.g. not a .yml file
        raise ApplyError(str(e)) from None
    return TraefikFile(output_file=output_file, state_file=config.CONFIG_FILE,
                       default_theme=s["backend.default_theme"], apps=state.load_apps,
                       pins=state.read_overrides, base_url=config.base_url)

"""Settings: environment variables, then picker.yml, then defaults.

picker.yml sits in this checkout (gitignored; picker.example.yml documents
every key) or wherever PICKER_CONFIG points. Every key is optional and no
file at all is valid -- the defaults are what the author's setup ran on before
the file existed. Environment variables win so a compose file can still override
anything. The capture script reads the same file, so the domain and the
screenshot app list live in one place.

A malformed file stops the picker at start with the reason, rather than
running on half-read settings.
"""

import os
import re
import sys
from pathlib import Path

from urllib.parse import urlsplit

import yaml  # installed into /tmp/pylibs at container start (see compose file)

REPO_DIR = Path(__file__).resolve().parent.parent

# Defensive: only plain theme names ever reach the allowlist, so a stray
# filename in that directory can't become an odd subprocess argument.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_APP = re.compile(r"^[a-z0-9-]+\Z")
_URL = re.compile(r"^https?://[^\s/]+(/\S*)?\Z")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}\Z")
_DIGEST = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun) ([01][0-9]|2[0-3]):([0-5][0-9])\Z")

# Empty: every themed app (shots.screenshot_apps()).
DEFAULT_SCREENSHOT_APPS = []

# file key path -> (env var, default)
KEYS = {
    ("theme_switcher_dir",): ("THEME_SWITCHER_DIR", None),
    ("state_dir",): ("STATE_DIR", None),
    ("theme_park_url",): ("THEME_PARK_URL", None),
    ("domain",): ("DOMAIN", ""),
    ("picker_url",): ("PICKER_URL", None),
    ("allowed_hosts",): ("ALLOWED_HOSTS", []),
    ("listen", "host"): ("LISTEN_HOST", "0.0.0.0"),
    ("listen", "port"): ("LISTEN_PORT", 8090),
    ("screenshots", "apps"): ("APPS", DEFAULT_SCREENSHOT_APPS),
    ("screenshots", "browser"): ("CAPTURE_BROWSER", "chrome"),
    ("screenshots", "sandbox"): ("CAPTURE_SANDBOX", True),
    ("coverage", "interval"): ("COVERAGE_INTERVAL", 900),
    ("ntfy", "url"): ("NTFY_URL", ""),
    ("ntfy", "topic"): ("NTFY_TOPIC", ""),
    ("ntfy", "token_file"): ("NTFY_TOKEN_FILE", ""),
    ("ntfy", "digest"): ("NTFY_DIGEST", ""),
    ("backend", "type"): ("THEME_BACKEND", "traefik-file"),
    ("backend", "output_file"): ("THEME_OUTPUT_FILE", None),
    ("backend", "apps_file"): ("THEME_APPS_FILE", None),
    ("backend", "default_theme"): ("THEME_DEFAULT", "dark"),
    ("hooks", "token_file"): ("HOOK_TOKEN_FILE", ""),
    ("custom_themes", "dir"): ("CUSTOM_THEMES_DIR", None),
    ("custom_themes", "theme_park_www"): ("THEME_PARK_WWW", None),
    ("custom_themes", "twins"): ("CUSTOM_THEMES_TWINS", True),
    ("apps",): ("THEME_APPS", None),
}
BACKENDS = ("traefik-file", "script", "state")


class ConfigError(Exception):
    pass


def read_file(path):
    """The parsed file as a dict, {} if it does not exist."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise ConfigError(f"{path}: {e}")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping of settings at the top level")
    return data


def _unknown_keys(data, prefix=()):
    known_sections = {k[0] for k in KEYS if len(k) > 1}
    out = []
    for k, v in data.items():
        path = prefix + (k,)
        if path in KEYS:
            continue
        if not prefix and k in known_sections and isinstance(v, dict):
            out += _unknown_keys(v, path)
        else:
            out.append(".".join(map(str, path)))
    return out


def resolve(env, data, repo_dir=REPO_DIR):
    """Merge env > file > defaults and validate. Returns a flat dict keyed by
    dotted name ("listen.port"). Unknown file keys are reported, not fatal."""
    for key in _unknown_keys(data):
        print(f"picker.yml: ignoring unknown setting '{key}'", file=sys.stderr, flush=True)
    out = {}
    for path, (var, default) in KEYS.items():
        name = ".".join(path)
        node = data
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
        if env.get(var):
            value = env[var]
        elif node is not None:
            value = node
        else:
            value = default
        out[name] = value

    def fail(name, why):
        raise ConfigError(f"{name}: {why} (got {out[name]!r})")

    for name in ("domain", "listen.host", "ntfy.url", "ntfy.topic", "ntfy.token_file", "hooks.token_file"):
        if not isinstance(out[name], str):
            fail(name, "expected a string")
    out["ntfy.url"] = out["ntfy.url"].rstrip("/")
    d = out["ntfy.digest"]
    if not isinstance(d, str) or (d.strip() and not _DIGEST.match(d.strip().lower())):
        fail("ntfy.digest", "expected a day and a time, e.g. \"mon 09:00\", or empty for none")
    out["ntfy.digest"] = d.strip().lower()
    if out["domain"] and not _HOST.match(out["domain"]):
        fail("domain", "expected a bare domain like example.com")
    for name in ("theme_park_url", "picker_url"):
        if out[name] is not None:
            if not isinstance(out[name], str) or not _URL.match(out[name]):
                fail(name, "expected an http(s) URL")
    if out["ntfy.url"] and not _URL.match(out["ntfy.url"]):
        fail("ntfy.url", "expected an http(s) URL")
    for name, lo, hi in (("listen.port", 1, 65535), ("coverage.interval", 0, 7 * 86400)):
        try:
            out[name] = int(out[name])
        except (TypeError, ValueError):
            fail(name, "expected a whole number")
        if not lo <= out[name] <= hi:
            fail(name, f"expected {lo}-{hi}")
    hosts = out["allowed_hosts"]
    if isinstance(hosts, str):
        hosts = hosts.replace(",", " ").split()
    if not isinstance(hosts, list) or not all(isinstance(h, str) and _HOST.match(h) for h in hosts):
        fail("allowed_hosts", "expected a list of host names (no scheme, port or path)")
    out["allowed_hosts"] = [h.lower().rstrip(".") for h in hosts]
    apps = out["screenshots.apps"]
    if isinstance(apps, str):
        apps = apps.split()
    if not isinstance(apps, list) or not all(isinstance(a, str) and _APP.match(a) for a in apps):
        fail("screenshots.apps", "expected a list of app names (lowercase letters, digits, hyphens)")
    out["screenshots.apps"] = apps
    if out["apps"] is not None:
        out["apps"] = _apps_setting(out["apps"], fail)
    for name in ("custom_themes.twins", "screenshots.sandbox"):
        flag = out[name]
        if isinstance(flag, str) and flag.strip().lower() in ("1", "true", "yes", "on", "0", "false", "no", "off"):
            flag = flag.strip().lower() in ("1", "true", "yes", "on")
        if not isinstance(flag, bool):
            fail(name, "expected true or false")
        out[name] = flag
    if out["screenshots.browser"] not in ("chrome", "chromium"):
        fail("screenshots.browser", "expected chrome or chromium")
    tsd = out["theme_switcher_dir"]
    out["theme_switcher_dir"] = (Path(repo_dir) / tsd).resolve() if tsd else Path(repo_dir).parent
    if out["backend.type"] not in BACKENDS:
        fail("backend.type", f"expected one of: {', '.join(BACKENDS)}")
    if not isinstance(out["backend.default_theme"], str) or not SAFE_NAME.match(out["backend.default_theme"]):
        fail("backend.default_theme", "expected a plain theme name")
    for name in ("custom_themes.dir", "custom_themes.theme_park_www", "state_dir"):
        if out[name] == "":                          # the example file's "unset"
            out[name] = None
    for name in ("backend.output_file", "backend.apps_file", "custom_themes.dir", "custom_themes.theme_park_www", "state_dir"):
        if out[name] is not None:
            if not isinstance(out[name], str) or not out[name].strip():
                fail(name, "expected a file path")
            # Relative paths are relative to the theme-switcher (state) directory.
            out[name] = (out["theme_switcher_dir"] / out[name]).resolve()
    return out


APP_KEYS = ("name", "theme_app", "host", "url", "addons")


def _apps_setting(value, fail):
    """The `apps` setting as a list of dicts. Each item is a name ("sonarr"),
    "name:theme_app" ("jellyseerr:overseerr"), or a mapping with name and
    optional theme_app, host, url, addons. The env var THEME_APPS takes the
    string forms, separated by spaces or commas."""
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, list):
        fail("apps", "expected a list of apps")
    out = []
    for item in value:
        if isinstance(item, str):
            name, _, theme_app = item.partition(":")
            item = {"name": name, **({"theme_app": theme_app} if theme_app else {})}
        if not isinstance(item, dict) or set(item) - set(APP_KEYS) or "name" not in item:
            fail("apps", f"each app is a name or a mapping of {', '.join(APP_KEYS)} with a name")
        for k in ("name", "theme_app"):
            if k in item and not (isinstance(item[k], str) and _APP.match(item[k])):
                fail("apps", f"{k} must be lowercase letters, digits and hyphens")
        if "host" in item and not (isinstance(item["host"], str) and _HOST.match(item["host"])):
            fail("apps", "host must be a plain host name")
        if "url" in item and not (isinstance(item["url"], str) and _URL.match(item["url"])):
            fail("apps", "url must be an http(s) URL")
        if not isinstance(item.get("addons", []), list):
            fail("apps", "addons must be a list")
        out.append(item)
    return out


CONFIG_PATH = Path(os.environ.get("PICKER_CONFIG") or REPO_DIR / "picker.yml")
SETTINGS = resolve(os.environ, read_file(CONFIG_PATH))

# The theme-switcher directory whose scripts and state this drives
# (set-theme.sh, apps.yml, themes-src/, screenshots/, the *.json state files).
# Defaults to the parent of this repo's checkout, which is where the author's
# setup clones it; relative paths in picker.yml are relative to this checkout.
THEME_DIR = SETTINGS["theme_switcher_dir"]
SETTINGS_FILE = THEME_DIR / "config.env"


def _state_dir():
    """Where the picker keeps what it writes: the live theme, history,
    favourites, pins, the schedule and the editor queue. state_dir in
    picker.yml (or STATE_DIR), else STATE_DIR in config.env -- which the
    theme-switcher scripts read too -- else the theme-switcher directory
    itself. A separate directory lets theme-switcher/ be mounted read-only
    into the picker's container, so the container cannot touch the scripts
    the host runs."""
    raw = SETTINGS["state_dir"]
    if not raw:
        try:
            for line in SETTINGS_FILE.read_text().splitlines():
                if line.startswith("STATE_DIR="):
                    raw = line.split("=", 1)[1].strip() or None
        except OSError:
            pass
    if not raw:
        return THEME_DIR
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (THEME_DIR / path).resolve()


STATE_DIR = _state_dir()
# The active theme lives in its own gitignored file, not config.env --
# see the note in config.env. May legitimately not exist yet.
CONFIG_FILE = STATE_DIR / "current-theme.env"

SET_THEME_SCRIPT = THEME_DIR / "set-theme.sh"

# Custom themes: one <name>.css per theme. Default: themes-src/themes in the
# theme-switcher directory. Anyone else can point this at a checkout of theme-park-themes.
CUSTOM_DIR = SETTINGS["custom_themes.dir"] or THEME_DIR / "themes-src" / "themes"
# theme.park's served www/ directory (its container's /config/www), mounted
# into the picker. Set, the picker deploys CUSTOM_DIR into it itself (see
# deploy.py) and the editor saves straight to CUSTOM_DIR. Unset, deploying is
# someone else's job -- in the author's setup, sync-themes.sh and theme-worker.sh.
THEME_PARK_WWW = SETTINGS["custom_themes.theme_park_www"]
# Portable mode also makes every theme's light/dark twin (picker/twins.py).
MAKE_TWINS = SETTINGS["custom_themes.twins"]

DOMAIN = SETTINGS["domain"]
THEME_PARK_URL = SETTINGS["theme_park_url"]
PICKER_URL = SETTINGS["picker_url"]
SCREENSHOT_APPS = SETTINGS["screenshots.apps"]


def base_url():
    """theme.park base URL, so the picker can dress itself in the live theme.
    picker.yml's theme_park_url if set, else BASE_URL from config.env, which
    set-theme.sh and the generator read too."""
    if THEME_PARK_URL:
        return THEME_PARK_URL.rstrip("/")
    try:
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BASE_URL="):
                url = line.split("=", 1)[1].strip().rstrip("/")
                return url if _URL.match(url) else ""     # never file:// or similar
    except OSError:
        pass
    return ""


def config_env():
    """KEY=VALUE pairs from config.env in the theme-switcher directory (shared
    with set-theme.sh and the generator), {} if absent."""
    out = {}
    try:
        for line in SETTINGS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def output_file():
    """Where the traefik-file backend writes: backend.output_file, else
    OUTPUT_FILE from config.env (where the generator writes), else
    dynamic/themes.yml in the theme-switcher directory."""
    if SETTINGS["backend.output_file"]:
        out = Path(SETTINGS["backend.output_file"])
    else:
        env = config_env().get("OUTPUT_FILE")
        out = Path(env).expanduser() if env else THEME_DIR / "dynamic" / "themes.yml"
    # config.env is writable from the picker's container and the nightly
    # capture writes this file on the HOST: never let it name a shell rc or
    # a cron file. Traefik's file provider only reads .yml/.yaml/.toml anyway.
    if out.suffix not in (".yml", ".yaml"):
        raise ValueError(f"the theme output file must be a .yml file, not {out}")
    return out


def apps_file():
    return SETTINGS["backend.apps_file"] or THEME_DIR / "apps.yml"


def app_url(app):
    """Where an app lives: its `url` if it has one, else <host>.<domain> with
    the scheme and port of the picker's own address (https and 443 normally,
    http://...:8088 in the starter stack)."""
    if app.get("url"):
        return app["url"]
    own = urlsplit(picker_url() or "https://x/")
    port = f":{own.port}" if own.port else ""
    return f"{own.scheme or 'https'}://{app['host']}.{DOMAIN}{port}/"


def picker_url():
    """The picker's own public URL, for dashboard widgets; "" if unknown."""
    if PICKER_URL:
        return PICKER_URL
    return f"https://theme-picker.{DOMAIN}/" if DOMAIN else ""

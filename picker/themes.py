"""Which themes exist, which one is live, and each theme's stylesheet.

Security note: the allowlist allowed_themes() returns is what stands between a
request and subprocess -- a theme name is only ever passed on after an exact
match against it. The custom half is read from the themes-src checkout and
filtered through SAFE_NAME, so only plain theme names can ever get through.
"""

import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from . import config
from .config import SAFE_NAME, base_url

# theme.park publishes /themes.json, generated inside the container at init
# from whatever theme files are actually present. It is the authoritative
# split between official ("themes") and community ("community-themes"), and
# each entry carries a ?sha= cache-buster keyed to the file's contents -- so
# using it also means the picker stops serving a stale stylesheet after a
# theme is edited and redeployed.
#
# The two lists below are now only a FALLBACK for when the manifest cannot be
# fetched. They were the primary source until 2026-09-21 and carried a "update
# this if theme.park changes upstream" comment, which is exactly the kind of
# instruction that gets missed. They are kept rather than deleted because the
# picker is how you recover from a bad theme -- it should still list something
# if theme-park is down.
FALLBACK_OFFICIAL = [
    "dark", "dracula", "nord", "aquamarine", "hotpink", "hotline",
    "maroon", "organizr", "overseerr", "plex", "space-gray",
]
FALLBACK_COMMUNITY = [
    "blackberry-abyss", "blackberry-amethyst", "blackberry-carol",
    "blackberry-dreamscape", "blackberry-flamingo", "blackberry-hearth",
    "blackberry-martian", "blackberry-pumpkin", "blackberry-royal",
    "blackberry-shadow", "blackberry-solar", "blackberry-vanta",
    "catppuccin-frappe", "catppuccin-latte", "catppuccin-macchiato",
    "catppuccin-mocha", "hotline-old", "ibracorp", "mind", "onedark",
    "pine-shadow", "power", "reality", "rose-pine-dawn", "rose-pine-moon",
    "rose-pine", "soul", "space", "time", "trueblack",
]

# Custom themes live in the homelab-themes repo, cloned at
# theme-switcher/themes-src/ and deployed into the theme-park container by
# sync-themes.sh. Discovered from that directory at request time rather
# than listed here, so adding a theme to that repo is enough -- this list
# can't drift from what's actually deployed.
CUSTOM_THEMES_DIR = config.CUSTOM_DIR

# Re-fetched every MANIFEST_TTL seconds. It changes when sync-themes.sh
# deploys a theme or theme-park restarts, and its ?sha= cache-busters are what
# tells the caches below that a theme-park stylesheet changed. It used to be
# fetched once per process, so a redeployed theme kept its old swatches and
# badges -- and a theme-park that was down when the picker started stayed
# "down" -- until someone restarted the picker. A failed fetch is cached as
# None too, so a down theme-park costs one timeout per TTL, not one per render.
MANIFEST_TTL = 600
_MANIFEST = {}
_MANIFEST_LOCK = threading.Lock()


def manifest():
    base = base_url()
    with _MANIFEST_LOCK:
        now = time.monotonic()
        if "data" not in _MANIFEST or now - _MANIFEST.get("at", now) > MANIFEST_TTL:
            data = None
            if base:
                try:
                    with urllib.request.urlopen(f"{base}/themes.json", timeout=6) as r:
                        data = json.loads(r.read().decode("utf-8"))
                except Exception:
                    data = None
            _MANIFEST["data"], _MANIFEST["at"] = data, now
        return _MANIFEST["data"]


def _manifest_paths(key):
    """{slug: path+query} for one manifest key, or None if unavailable.

    Only the PATH is taken from the manifest, never the host. Those URLs are
    built from the container's TP_DOMAIN, which was unset until 2026-09-21 and
    had every one of them reading "https://None.theme-park.dev/..." -- the
    picker should not inherit that if it regresses.
    """
    data = manifest()
    # Parsed once per fetched manifest: every cache lookup builds a theme's URL
    # through here, and re-parsing ~116 entries each time doubled render time.
    memo = _MANIFEST.setdefault("paths", {})
    if key in memo and memo[key][0] is data:
        return memo[key][1]
    memo[key] = (data, _parse_manifest_paths(data, key))
    return memo[key][1]


def _parse_manifest_paths(data, key):
    if not data or key not in data:
        return None
    out = {}
    for entry in data[key].values():
        url = entry.get("url", "") if isinstance(entry, dict) else ""
        slug = url.rsplit("/", 1)[-1].split(".css")[0]
        if not SAFE_NAME.match(slug):
            continue
        parts = urlsplit(url)
        out[slug] = parts.path + (f"?{parts.query}" if parts.query else "")
    return out or None


def official_themes():
    """theme.park's own themes: the manifest's "themes" key minus our customs,
    which deploy into that same css/theme-options/ directory and so land in it.
    """
    paths = _manifest_paths("themes")
    if paths is None:
        return list(FALLBACK_OFFICIAL)
    return sorted(set(paths) - set(custom_themes()))


def community_themes():
    paths = _manifest_paths("community-themes")
    return list(FALLBACK_COMMUNITY) if paths is None else sorted(paths)


def custom_themes():
    if not CUSTOM_THEMES_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in CUSTOM_THEMES_DIR.glob("*.css") if SAFE_NAME.match(p.stem)
    )


# Written into the header of every theme homelab-themes' tools/make_variants.py
# generates (a light version of each dark theme and vice versa). They are
# custom themes like any other, listed in a section of their own.
VARIANT_MARK = "Generated variant:"


def variant_themes():
    """Generated light/dark variants, found by their header -- no list to keep."""
    return [t for t in custom_themes() if VARIANT_MARK in theme_css(t)[:1200]]


def variant_pairs():
    """{theme: its generated twin} -- "nord" -> "nord-light". The picker shows
    each pair as one tile with a light/dark switch."""
    own = set(custom_themes()) - set(variant_themes())
    sources = set(official_themes()) | set(community_themes()) | own
    out = {}
    for v in variant_themes():
        for suffix in ("-light", "-dark"):
            if v.endswith(suffix) and v[:-len(suffix)] in sources:
                out[v[:-len(suffix)]] = v
    return out


def own_themes():
    """Custom themes that were made by hand or in the editor, not generated."""
    variants = set(variant_themes())
    return [t for t in custom_themes() if t not in variants]


def section_of(theme):
    if theme in custom_themes():
        return "variants" if theme in variant_themes() else "custom"
    return "community" if theme in community_themes() else "official"


def allowed_themes():
    return official_themes() + community_themes() + custom_themes()


def current_theme():
    if not config.CONFIG_FILE.exists():
        return "unknown"
    for line in config.CONFIG_FILE.read_text().splitlines():
        if line.startswith("CURRENT_THEME="):
            # Re-checked here because the value is echoed into pages, JSON and
            # the unauthenticated /dashboards/ stylesheets (inside a CSS
            # comment, where a "*/" would end it).
            name = line.split("=", 1)[1].strip()
            return name if SAFE_NAME.match(name) else "unknown"
    return "unknown"


def theme_css_url(theme):
    """Stylesheet URL for a theme, or "" if we cannot place it.

    theme.park splits its themes across TWO directories and the picker has to
    pick the right one: official and our own custom themes live under
    css/theme-options/, community themes under css/community-theme-options/.
    Getting this wrong 404s silently -- the page still renders, just unthemed,
    which is exactly how the community themes were broken on first release.
    The manifest settles it per theme instead of by list membership.
    """
    base = base_url()
    if not base or theme == "unknown":
        return ""
    for key in ("themes", "community-themes"):
        paths = _manifest_paths(key)
        if paths and theme in paths:
            return base + paths[theme]
    folder = "community-theme-options" if theme in community_themes() else "theme-options"
    return f"{base}/css/{folder}/{theme}.css"


def css_signature(theme):
    """What a theme's stylesheet -- and so everything derived from it -- depends
    on: a custom theme's file modification time (sync-themes.sh pulls a new
    version into themes-src/), or a theme-park theme's URL, whose ?sha= changes
    with the file's contents."""
    try:
        return ("file", (CUSTOM_THEMES_DIR / f"{theme}.css").stat().st_mtime_ns)
    except OSError:
        return ("url", theme_css_url(theme))


def cached(cache, theme, compute):
    """compute(theme), kept in `cache` until the theme's css_signature() changes.
    Fetching 116 stylesheets on every render is not an option, but keeping
    them for the process lifetime showed an edited theme's old colours and
    contrast badges until a restart."""
    sig = css_signature(theme)
    hit = cache.get(theme)
    if hit is None or hit[0] != sig:
        hit = cache[theme] = (sig, compute(theme))
    return hit[1]


_CSS_CACHE = {}


def theme_css(theme):
    """Raw stylesheet text for one theme, cached until it changes."""
    return cached(_CSS_CACHE, theme, _load_css)


def _load_css(theme):
    css = ""
    local = CUSTOM_THEMES_DIR / f"{theme}.css"
    if local.is_file():
        try:
            css = local.read_text()
        except OSError:
            css = ""
    if not css:
        url = theme_css_url(theme)
        if url:
            try:
                with urllib.request.urlopen(url, timeout=4) as r:
                    css = r.read().decode("utf-8", "replace")
            except Exception:
                css = ""
    return css


# Swatch colours per theme, parsed once per version of its stylesheet.
_PALETTE_CACHE = {}
SWATCH_VARS = ("--main-bg-color", "--modal-bg-color", "--button-color",
               "--link-color", "--text")


def parse_palette(css):
    """Pull the swatch variables out of a theme sheet as CSS background values.

    Deliberately NOT hex-only. theme.park's own themes rarely use plain hex for
    the surfaces: `dark` and every `blackberry-*` set --main-bg-color to a
    multi-stop gradient, others use rgb()/hsla(), and several point one
    variable at another with var(). A hex-only parser rendered one or two
    bands for most official and community themes and five only for ours,
    which made the previews misleading in exactly the comparison they exist
    for. These values are valid `background` shorthands as they stand, so
    they are passed through and var() references are resolved against the
    same file.
    """
    decls = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+);", css))

    def resolve(val, depth=0):
        if depth > 5:
            return ""
        m = re.fullmatch(r"\s*var\(\s*(--[\w-]+)\s*(?:,([^)]*))?\)\s*", val)
        if not m:
            return val.strip()
        target = decls.get(m.group(1))
        if target is not None:
            return resolve(target, depth + 1)
        return (m.group(2) or "").strip()

    out = {}
    for var in SWATCH_VARS:
        if var in decls:
            val = resolve(decls[var])
            # Drop url() layers rather than the whole value: several
            # community themes layer a noise/blur PNG over the gradient that
            # actually carries the colour, and skipping the declaration
            # outright cost those themes their main background band -- the
            # most informative one. A background shorthand stays valid with
            # one comma layer removed. `@` would mean an at-rule leaked into
            # the match, which is not a colour.
            val = re.sub(r"url\([^)]*\)", "", val)
            val = re.sub(r",\s*,", ",", val).strip().strip(",").strip()
            val = re.sub(r"\bfixed\b", "scroll", val)
            if val and "@" not in val:
                out[var] = val
    return out


def theme_palette(theme):
    """Swatch colours for one theme, or {} if it cannot be read."""
    return cached(_PALETTE_CACHE, theme, lambda t: parse_palette(theme_css(t)))


def warm_palette_cache(themes):
    """Populate the cache in parallel so a load after a change is not serial."""
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(theme_palette, themes))


def is_gradient(theme):
    """True when the theme paints its page with a gradient rather than a flat
    colour. Read from the theme's own --main-bg-color, so it cannot drift from
    a hand-kept list. Eighteen of ours qualify, but at swatch size a gradient
    band is indistinguishable from a flat one -- hence the label."""
    return "gradient(" in theme_palette(theme).get("--main-bg-color", "")

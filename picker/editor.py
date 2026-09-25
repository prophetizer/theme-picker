"""The in-browser theme editor: a theme's colours as a starting point, and
turning a submission into a theme file queued for deployment.

The picker cannot deploy a theme itself: its container has no git and no
Docker access. A saved theme is written to editor-queue/, and
theme-worker.sh -- run every minute from the host's crontab -- commits it to
homelab-themes, pushes, and deploys with sync-themes.sh, recording the
outcome in editor-status.json.

Security: the theme file is served to every themed app, so it is built here
ONLY from validated primitives -- #rrggbb colours, an integer angle, and a
spinner filter matching one exact shape. No submitted string is ever
written into the CSS as-is.
"""

import colorsys
import re
from datetime import date, datetime

from . import deploy, colour as c, config, state, themes

QUEUE_DIR = config.THEME_DIR / "editor-queue"
EDITOR_STATUS = config.THEME_DIR / "editor-status.json"
EDITOR_MARKER = "Created in the theme picker's editor"
HEX6 = re.compile(r"^#[0-9a-fA-F]{6}\Z")
NEWNAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}\Z")
TITLE = re.compile(r"^[A-Za-z0-9 ._'()&+-]{1,40}\Z")
SPINNER = re.compile(r"^invert\([0-9]{1,3}%\) sepia\([0-9]{1,3}%\) saturate\([0-9]{1,4}%\) "
                     r"hue-rotate\([0-9]{1,3}deg\) brightness\([0-9]{1,3}%\) contrast\([0-9]{1,3}%\)\Z")
EDITOR_FIELDS = ("page_bg", "panel_bg", "button", "button_hover", "button_text",
                 "link", "link_hover", "text", "text_hover", "muted", "queue")


def theme_vars(theme):
    """A theme's colours flattened to #rrggbb, as a starting point for editing."""
    d = c.decls(themes.theme_css(theme))

    def one(var, fallback):
        st = c.surface(d.get(var)) or c.stops(d.get(var))
        if not st:
            return fallback
        return c.to_hex([sum(s[i] for s in st) / len(st) for i in range(3)])
    page = c.surface(d.get("--main-bg-color"))
    out = {"page_bg": c.to_hex(page[0]) if page else "#1e1e1e",
           "page_bg2": c.to_hex(page[-1]) if len(page) > 1 else "",
           "panel_bg": one("--modal-bg-color", "#2a2a2a"), "button": one("--button-color", "#5b8dd6"),
           "button_hover": one("--button-color-hover", "#7aa8e8"),
           "button_text": one("--button-text", "#ffffff"), "link": one("--link-color", "#6fa0e0"),
           "link_hover": one("--link-color-hover", "#9ac0f0"), "text": one("--text", "#dddddd"),
           "text_hover": one("--text-hover", "#ffffff"), "muted": one("--text-muted", "#999999"),
           "queue": one("--arr-queue-color", "#4fb87a")}
    return out


def build_theme_css(name, title, base, f, gradient, angle, spinner, on=None):
    r, g, b = c.hex_rgb(f["button"])
    pr, pg, pb = c.hex_rgb(f["page_bg"])
    fixed = "center center/cover no-repeat fixed"
    main = (f"linear-gradient({angle}deg, {f['page_bg']} 0%, {f['page_bg2']} 100%) {fixed}"
            if gradient else f["page_bg"])
    return f"""/*
 * theme.park custom theme: {title}
 *
 * {EDITOR_MARKER} on {(on or date.today()).isoformat()}, starting from '{base}'.
 * Colours were chosen by hand in the editor; there is no upstream palette.
 *
 * --accent-color and --gitea-color-primary-dark-4 are bare "R, G, B" on
 * purpose: theme.park's base CSS wraps them in rgb()/rgba() itself, and a
 * hex here silently kills accents across every app.
 * --petio-spinner was computed in the browser with the same filter-solving
 * algorithm as tools/css_filter_solver.py, for '{f['button']}'.
 */
:root {{
  --main-bg-color: {main};
  --modal-bg-color: {f['panel_bg']};
  --modal-header-color: {f['panel_bg']};
  --modal-footer-color: {f['panel_bg']};
  --drop-down-menu-bg: {f['panel_bg']};
  --button-color: {f['button']};
  --button-color-hover: {f['button_hover']};
  --button-text: {f['button_text']};
  --button-text-hover: {f['button_text']};
  --accent-color: {r}, {g}, {b};
  --accent-color-hover: rgb(var(--accent-color),.8);
  --link-color: {f['link']};
  --link-color-hover: {f['link_hover']};
  --label-text-color: {f['button_text']};
  --text: {f['text']};
  --text-hover: {f['text_hover']};
  --text-muted: {f['muted']};
  --arr-queue-color: {f['queue']};
  --plex-poster-unwatched: {f['button']};
  --petio-spinner: {spinner};
  --gitea-color-primary-dark-4: {r}, {g}, {b};
  --overseerr-gradient: linear-gradient(180deg, rgba({pr}, {pg}, {pb}, 0.17) 0%, rgba({pr}, {pg}, {pb}) 100%);
}}
"""


def editor_save(data):
    name, title = str(data.get("name", "")), str(data.get("title", "")).strip()
    base = str(data.get("base", ""))
    if not NEWNAME.match(name):
        return False, "Name: lowercase letters, digits and hyphens, 2-40 characters."
    if not TITLE.match(title):
        return False, "Title: 1-40 letters, digits, spaces and . _ ' ( ) & + -"
    if base not in themes.allowed_themes():
        base = "scratch"
    if name in themes.official_themes() or name in themes.community_themes():
        return False, f"'{name}' is one of theme.park's own themes."
    existing = themes.CUSTOM_THEMES_DIR / f"{name}.css"
    if existing.exists() and EDITOR_MARKER not in existing.read_text()[:600]:
        return False, f"'{name}' is an existing hand-authored theme; pick another name."
    fields = {k: str(data.get(k, "")) for k in EDITOR_FIELDS}
    bad = [k for k, v in fields.items() if not HEX6.match(v)]
    if bad:
        return False, f"Not a #rrggbb colour: {', '.join(bad)}"
    gradient = bool(data.get("gradient"))
    if gradient:
        fields["page_bg2"] = str(data.get("page_bg2", ""))
        if not HEX6.match(fields["page_bg2"]):
            return False, "Second gradient colour is not #rrggbb."
    try:
        angle = int(data.get("angle", 160)) % 360
    except (TypeError, ValueError):
        angle = 160
    spinner = str(data.get("spinner", ""))
    if not SPINNER.match(spinner):
        return False, "Spinner filter was not computed; try saving again."
    h, l, sat = colorsys.rgb_to_hls(*(v / 255 for v in c.hex_rgb(fields["queue"])))
    if 20 <= h * 360 <= 70 and sat > 0.25:
        return False, ("Queue colour is orange/yellow, which collides with the *arr "
                       "queue-error colour. Pick a green, teal or blue.")
    css = build_theme_css(name, title, base, fields, gradient, angle, spinner)
    if deploy.enabled():
        return _save_and_deploy(name, title, css)
    QUEUE_DIR.mkdir(exist_ok=True)
    tmp = QUEUE_DIR / f".{name}.tmp"
    tmp.write_text(css)
    tmp.replace(QUEUE_DIR / f"{name}.css")
    with state.STATE_LOCK:
        st = state.read_json(EDITOR_STATUS, {})
        st[name] = {"state": "queued", "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "detail": "waiting for the deploy job (runs every minute)"}
        state.write_json(EDITOR_STATUS, st)
    return True, f"Saved '{title}' as {name}. Deploying within a minute..."


def _save_and_deploy(name, title, css):
    """Portable mode (custom_themes.theme_park_www set): no queue and no host
    job. The CSS was built from validated primitives just above, so it goes
    straight into the custom themes directory and is deployed now."""
    dst = themes.CUSTOM_THEMES_DIR / f"{name}.css"
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{name}.tmp"
    tmp.write_text(css)
    tmp.replace(dst)
    result = deploy.deploy()
    ok = result["ok"] and name not in result["refused"]
    detail = "saved and deployed" if ok else f"saved, but deploy failed: {result['error'] or 'refused'}"
    with state.STATE_LOCK:
        st = state.read_json(EDITOR_STATUS, {})
        st[name] = {"state": "deployed" if ok else "failed", "detail": detail,
                    "at": datetime.now().astimezone().isoformat(timespec="seconds")}
        state.write_json(EDITOR_STATUS, st)
    return ok, (f"Saved '{title}' as {name} and deployed it." if ok else f"Saved '{title}' as {name}; {detail}.")


def editor_status(name):
    return state.read_json(EDITOR_STATUS, {}).get(name, {"state": "unknown"})


# --- verifying a queued file (run by theme-worker.sh on the host) -----------
_HEAD = re.compile(r"^/\*\n \* theme\.park custom theme: (?P<title>[^\n]*)\n \*\n \* "
                   + re.escape(EDITOR_MARKER)
                   + r" on (?P<on>\d{4}-\d\d-\d\d), starting from '(?P<base>[A-Za-z0-9._-]{1,64})'\.\n")
_GRADIENT = re.compile(r"^linear-gradient\((?P<angle>\d{1,3})deg, (?P<a>#[0-9a-fA-F]{6}) 0%, "
                       r"(?P<b>#[0-9a-fA-F]{6}) 100%\) center center/cover no-repeat fixed$")
_FIELD_VARS = {"panel_bg": "--modal-bg-color", "button": "--button-color",
               "button_hover": "--button-color-hover", "button_text": "--button-text",
               "link": "--link-color", "link_hover": "--link-color-hover", "text": "--text",
               "text_hover": "--text-hover", "muted": "--text-muted", "queue": "--arr-queue-color"}


def verify_queued(name, css):
    """None if `css` is exactly what the editor builds for some valid input,
    else the reason it is not.

    theme-worker.sh runs on the host with push access and deploys the file to
    every themed app, but editor-queue/ is writable from inside the picker's
    container. So the worker does not trust the file's content: it is parsed
    back into the editor's inputs, each checked against the same rules as a
    save, rebuilt with build_theme_css(), and must come out byte-identical.
    Anything the editor could not have produced -- an extra declaration, a
    url(), a rule outside :root -- fails."""
    if not NEWNAME.match(name):
        return "bad name"
    m = _HEAD.match(css)
    if not m:
        return "header is not the editor's"
    if not TITLE.match(m["title"]):
        return "bad title"
    decls = dict(re.findall(r"^  (--[\w-]+): ([^;\n]*);$", css, re.M))
    f = {k: decls.get(v, "") for k, v in _FIELD_VARS.items()}
    main = decls.get("--main-bg-color", "")
    g = _GRADIENT.match(main)
    if g:
        f["page_bg"], f["page_bg2"], angle, gradient = g["a"], g["b"], int(g["angle"]), True
        if angle >= 360:
            return "bad gradient angle"
    else:
        f["page_bg"], angle, gradient = main, 160, False
    bad = [k for k, v in f.items() if not HEX6.match(v)]
    if bad:
        return f"not #rrggbb: {', '.join(sorted(bad))}"
    spinner = decls.get("--petio-spinner", "")
    if not SPINNER.match(spinner):
        return "bad spinner filter"
    try:
        on = date.fromisoformat(m["on"])
    except ValueError:
        return "bad date"
    if build_theme_css(name, m["title"], m["base"], f, gradient, angle, spinner, on=on) != css:
        return "content differs from what the editor builds"
    return None


if __name__ == "__main__":
    # python3 -m picker.editor --verify NAME FILE  -> exit 0 if valid, 1 with the reason
    import sys
    if len(sys.argv) != 4 or sys.argv[1] != "--verify":
        sys.exit("usage: python3 -m picker.editor --verify NAME FILE")
    try:
        text = open(sys.argv[3], encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"unreadable: {e}")
    reason = verify_queued(sys.argv[2], text)
    if reason:
        sys.exit(reason)

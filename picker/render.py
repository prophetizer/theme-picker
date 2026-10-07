"""The picker page: theme tiles, panels, and the template they fill."""

import hashlib
import json
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import collections, config, deploy, schedule, shots, state, themes
from . import colour
from .colour import FAMILIES
from .editor import EDITOR_MARKER
from .metrics import theme_metrics

NEW_DAYS = 14

# Applying a theme used to be an ordinary form POST whose response was a
# freshly rendered page, so the browser scrolled back to the top every time.
# It posts in the background instead and patches what changes (active tile,
# heading, stylesheet href, recent-theme chips), so the picker re-dresses
# itself in the new theme without moving. With JavaScript off none of this
# runs: the tiles are plain form buttons, POST, full re-render.
#
# Everything else here is client-side over tiles already in the page -- the
# theme's metrics ride along as data-* attributes -- so filtering, sorting
# and keyboard movement never touch the server.
#
# The stylesheet and script are served as files (/static/), not inlined, so
# the Content-Security-Policy can allow scripts from this origin only -- an
# injected <script> in the page would not run. Each URL carries a hash of the
# file's contents, so browsers may cache them and still never run a stale one.
WEB_DIR = Path(__file__).resolve().parent / "web"
PAGE_TEMPLATE = (WEB_DIR / "page.html").read_text()
STATIC = {name: (WEB_DIR / name).read_bytes()
          for name in ("style.css", "app.js", "early.js", "icon.svg",
                       "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")}
STATIC_TYPES = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                "early.js": "text/javascript; charset=utf-8",
                "icon.svg": "image/svg+xml", "icon-192.png": "image/png", "icon-512.png": "image/png",
                "icon-maskable-512.png": "image/png", "apple-touch-icon.png": "image/png"}
VERSION = {name: hashlib.sha256(data).hexdigest()[:12] for name, data in STATIC.items()}


def swatch_colours(theme):
    """The swatch's colours as #rrggbb (page, panels, button, link, text --
    the first stop of a gradient), for find-by-colour and similar themes."""
    pal = themes.theme_palette(theme)
    out = []
    for v in themes.SWATCH_VARS:
        st = colour.stops(pal.get(v, ""))
        if st:
            out.append(colour.to_hex(st[0]))
    return " ".join(out)


def swatch_html(theme):
    pal = themes.theme_palette(theme)
    if not pal:
        return ""
    cells = "".join(
        f'<i style="background:{html.escape(pal[v], quote=True)}"></i>'
        for v in themes.SWATCH_VARS if v in pal
    )
    return f'<span class="swatch">{cells}</span>' if cells else ""


def added_day(added):
    """The local calendar day of a theme-dates.json value ("" if none): a UTC
    timestamp committed at 21:00 local on the 29th is the 29th here, not the
    30th."""
    if "T" in added:
        try:
            return datetime.fromisoformat(added.replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            return ""
    return added[:10]


def tile_html(t, section, active, shot_idx, dates, today, favs=frozenset(), twin="", twin_of="", hidden=frozenset(),
              ratings=None, hidden_forms=frozenset()):
    """One theme tile. A theme with a light/dark twin carries data-twin; the
    twin itself data-twin-of, and sits right after it in the same section.
    The page shows one form of each pair at a time (the sun/moon switch, or
    the sidebar's "show every theme as"); without JavaScript both show."""
    m = theme_metrics(t)
    grad = themes.is_gradient(t)
    # theme-dates.json holds when each theme was first committed: a UTC
    # timestamp ("2026-09-29T02:05:11Z", so Newest orders themes added the
    # same day) or, from older sync-themes.sh runs, just the day. The badge
    # and tooltips use the day; data-added keeps it all for sorting.
    added = str(dates.get(t, ""))
    day = added_day(added)
    try:
        # Generated variants arrive a hundred at a time; badging them "new"
        # would bury the themes that really are.
        fresh = not twin_of and section != "variants" and bool(day) and (today - date.fromisoformat(day)).days <= NEW_DAYS
    except ValueError:
        fresh = False
    apps = shot_idx.get(t, [])
    warn = "; ".join(m["warnings"])
    e = lambda s: html.escape(str(s), quote=True)

    fav = t in favs
    star = (f'<span class="star{" on" if fav else ""}" title="Favourite (F)">'
            f'{"&#9733;" if fav else "&#9734;"}</span>')
    tags = []
    if warn:
        tags.append(f'<span class="tag warn" title="{e(warn)}">low contrast</span>')
    if m["high_contrast"]:
        r = m["ratios"]
        tags.append(f'<span class="tag hc" title="WCAG AAA for every text role. Text {r["--text"]}:1, muted {r["--text-muted"]}:1, '
                    f'links {r["--link-color"]}:1, buttons {r["--button-text"]}:1">high contrast</span>')
    if fresh:
        tags.append(f'<span class="tag new" title="Added {e(day)}">new</span>')
    if grad:
        tags.append('<span class="tag grad">gradient</span>')
    # Only where a capture runs at all (some theme has shots): elsewhere every
    # tile would carry it and say nothing.
    if shot_idx and not apps:
        tags.append('<span class="tag noshots" title="No screenshots yet: the next capture takes them">no shots</span>')
    # Every tile: the preview also holds export, colour vision, "looks like"
    # and "edit a copy", not only the screenshots.
    peek = (f'<span class="peek" title="Preview: {len(apps)} screenshot{"s" if len(apps) != 1 else ""}, '
            f'export, colour vision (P)" aria-label="Preview">&#9635;</span>')
    light = m["mode"] == "light"
    pair_attrs = (f' data-twin="{e(twin)}"' if twin else "") + (f' data-twin-of="{e(twin_of)}"' if twin_of else "")
    if twin or twin_of:
        forms = (f'<span class="forms" title="Light or dark version (L)">'
                 f'<span class="form{" on" if light else ""}" data-form="light" aria-label="Light version">&#9728;</span>'
                 f'<span class="form{" on" if m["mode"] == "dark" else ""}" data-form="dark" aria-label="Dark version">&#9790;</span></span>')
    elif m["mode"]:
        forms = f'<span class="tag mode" title="{m["mode"]} background">{"&#9728;" if light else "&#9790;"}</span>'
    else:
        forms = ""

    return (
        f'<button class="theme-btn{" active" if t == active else ""}" '
        f'formaction="/set-theme" name="theme" value="{e(t)}" data-theme="{e(t)}" '
        f'data-section="{section}" data-gradient="{int(grad)}" data-mode="{m["mode"]}" '
        f'data-lum="{m["lum"]}" data-hue="{m["hue"]}" data-family="{m["family"]}" '
        f'data-added="{e(added)}" data-new="{int(fresh)}" '
        f'data-contrast="{"low" if warn else "ok"}" data-warn="{e(warn)}" '
        f'data-hc="{int(m["high_contrast"])}" data-season="{" ".join(collections.season(t, m))}" '
        f'data-shots="{e(" ".join(apps))}" data-fav="{int(fav)}" data-hidden="{int(t in hidden)}" '
        f'data-rating="{(ratings or {}).get(t, 0)}" data-hidden-form="{int(t in hidden_forms)}" '
        f'data-colors="{e(swatch_colours(t))}"{pair_attrs}>'
        f'<span class="tile-top"><span class="name" title="{e(t)}">{e(t)}</span>{star}</span>'
        f'{swatch_html(t)}'
        f'<span class="tile-foot"><span class="tags">{"".join(tags)}</span>{peek}{forms}</span></button>'
    )


def theme_grid(names, section, active, shot_idx, dates, today, favs=frozenset(), pairs=None, hidden=frozenset(),
               ratings=None, hidden_forms=frozenset()):
    """Tiles for a section; with `pairs`, each theme's twin follows it (and a
    twin in `names` is skipped where it stands)."""
    pairs = pairs or {}
    twins = set(pairs.values())
    entries = []
    for t in names:
        if t in twins:
            continue
        entries.append((t, pairs.get(t, ""), ""))
        if t in pairs:
            entries.append((pairs[t], "", t))
    every = [t for t, _, _ in entries]
    themes.warm_palette_cache(every)
    with ThreadPoolExecutor(max_workers=8) as ex:     # metrics read the same cache
        list(ex.map(theme_metrics, every))
    return "\n".join(tile_html(t, section, active, shot_idx, dates, today, favs, twin=tw, twin_of=of, hidden=hidden,
                               ratings=ratings, hidden_forms=hidden_forms)
                     for t, tw, of in entries)


# The hand-made themes, split so 130-odd tiles aren't one wall: made in the
# editor, gradients, then by the mode each was designed in. A pair's twin is
# not listed here: theme_grid() places it right after its lead.
CUSTOM_GROUPS = ("custom-dark", "custom-light", "custom-gradient", "custom-editor")


def custom_groups(pairs):
    twins = set(pairs.values())
    out = {g: [] for g in CUSTOM_GROUPS}
    for t in themes.own_themes():
        if t in twins:
            continue
        if EDITOR_MARKER in themes.theme_css(t)[:600]:
            out["custom-editor"].append(t)
        elif themes.is_gradient(t):
            out["custom-gradient"].append(t)
        elif theme_metrics(t)["mode"] == "light":
            out["custom-light"].append(t)
        else:
            out["custom-dark"].append(t)
    return out


def groups_html():
    """App groups: pin several apps at once. Each group's select shows the
    pin its apps share, or "mixed"."""
    e = lambda s: html.escape(str(s), quote=True)
    groups, pins, apps = state.read_groups(), state.read_overrides(), [a["name"] for a in state.load_apps()]
    rows = []
    for g, members in sorted(groups.items()):
        shared = {pins.get(a, "") for a in members}
        cur = shared.pop() if len(shared) == 1 else None
        opts = ('<option value="" disabled selected>mixed pins</option>' if cur is None else "") + \
            f'<option value=""{" selected" if cur == "" else ""}>follow the live theme</option>' + \
            current_opt(cur or "")
        rows.append(f'<div class="group" data-group="{e(g)}" data-apps="{e(" ".join(members))}"><b>{e(g)}</b>'
                    f'<span class="count">{e(", ".join(members))}</span>'
                    f'<select class="group-pin" data-themes data-group="{e(g)}" aria-label="Theme for the {e(g)} group">{opts}</select>'
                    f'<button type="button" class="group-edit" data-group="{e(g)}">Edit</button>'
                    f'<button type="button" class="group-del" data-group="{e(g)}">Delete</button></div>')
    boxes = "".join(f'<label><input type="checkbox" class="grp-app" value="{e(a)}"> {e(a)}</label>' for a in apps)
    return (f'<details class="groups-box" id="groups"{" open" if groups else ""}><summary>App groups '
            f'<span class="count">({len(groups)})</span></summary>'
            f'<p class="count">Pin several apps to one theme at once, e.g. every *arr app. A group only '
            f'sets its apps\' pins; each app can still be changed on its own below.</p>'
            + "".join(rows) +
            f'<div class="group-form"><input type="text" id="grp-name" maxlength="40" placeholder="Group name">'
            f'<div class="grp-apps">{boxes}</div>'
            f'<button type="button" id="grp-save">Save group</button><span id="grp-status" class="count"></span></div>'
            f'</details>')


def theme_label(t):
    mode = theme_metrics(t)["mode"]
    return f'{t}{" · " + mode if mode else ""}'


def current_opt(t):
    """The one theme option a select is sent with: its current value. The
    rest come from the page's <template id="theme-opts"> when the select is
    first used (app.js fillThemes) -- 29 selects each listing every theme
    were half of the page (15,000 options, 850 KB)."""
    if not t or t not in themes.allowed_themes():
        return ""
    return f'<option value="{html.escape(t, quote=True)}" selected>{html.escape(theme_label(t))}</option>'


def theme_opts_template():
    return ('<template id="theme-opts">' + "".join(
        f'<option value="{html.escape(t, quote=True)}">{html.escape(theme_label(t))}</option>'
        for t in sorted(themes.allowed_themes())) + '</template>')


def apps_html(active):
    """One card per themed app: where it is, a pin control, and what it is served."""
    pinned = state.read_overrides()
    cards = []
    for a in state.load_apps():
        n = html.escape(a["name"])
        cur = pinned.get(a["name"], "")
        cards.append(
            f'<div class="app-card" data-app="{n}">'
            f'<a href="{html.escape(config.app_url(a))}" '
            f'target="_blank" rel="noopener">{n}</a>'
            f'<select class="pin" data-themes data-app="{n}" data-current="{html.escape(cur)}" aria-label="Theme for {n}">'
            f'<option value="">follows the live theme</option>{current_opt(cur)}</select>'
            f'<span class="cov" data-app="{n}"><span class="none">not checked</span></span></div>')
    return "".join(cards)


def history_html(active):
    chips = "".join(
        f'<button type="button" class="chip" data-theme="{html.escape(h["theme"], quote=True)}" '
        f'title="Applied {html.escape(h.get("at", ""), quote=True)} by '
        f'{html.escape(h.get("by", "?"), quote=True)}">{html.escape(h["theme"])}</button>'
        for h in state.recent_themes(active))
    return chips or '<span class="none">none yet</span>'


def undo_html(active):
    """One-click return to the theme that was live before this one. The page's
    script keeps it pointing at the previous theme after every change."""
    recent = state.recent_themes(active)
    t = html.escape(recent[0]["theme"], quote=True) if recent else ""
    return (f'<button type="button" id="undo" data-theme="{t}" title="Back to {t} (U)"'
            f'{"" if t else " hidden"}>&#8630; Undo: <span>{t}</span></button>')


def schedule_html():
    """The day/night schedule panel, filled with the saved schedule."""
    st = schedule.status()
    e = lambda s: html.escape(str(s), quote=True)

    def opts(sel):
        out = ['<option value="">choose a theme...</option>', current_opt(sel)]
        return "".join(out)
    return (
        f'<div class="sched" id="schedule-panel"><h2 class="tab-title">Day/night schedule '
        f'<span id="sch-state" class="count">{e(schedule_summary(st))}</span></h2>'
        f'<div class="ed-row"><label><input type="checkbox" id="sch-enabled"'
        f'{" checked" if st["enabled"] else ""}> Switch themes by time of day</label></div>'
        f'<div class="ed-row"><label>Day <select id="sch-day" data-themes>{opts(st["day"])}</select></label>'
        f'<label>from <input type="time" id="sch-day-at" value="{e(st["day_at"])}"></label></div>'
        f'<div class="ed-row"><label>Night <select id="sch-night" data-themes>{opts(st["night"])}</select></label>'
        f'<label>from <input type="time" id="sch-night-at" value="{e(st["night_at"])}"></label></div>'
        f'<div class="ed-row"><label><input type="checkbox" id="sch-sun"{" checked" if st["sun"] else ""}> '
        f'Follow sunrise and sunset instead</label>'
        f'<span id="sch-sun-today" class="count">{e(st.get("sun_today", ""))}</span></div>'
        f'<div class="ed-row sun-row"><label>Latitude <input type="number" id="sch-lat" step="0.01" min="-90" max="90" '
        f'value="{e(st["lat"]) if st["sun"] else ""}" placeholder="51.51"></label>'
        f'<label>Longitude <input type="number" id="sch-lon" step="0.01" min="-180" max="180" '
        f'value="{e(st["lon"]) if st["sun"] else ""}" placeholder="-0.13"></label></div>'
        f'<div class="ed-row sun-row"><label>Day starts <input type="number" id="sch-day-off" step="5" min="-180" max="180" '
        f'value="{e(st["day_offset"])}"> min after sunrise</label>'
        f'<label>Night starts <input type="number" id="sch-night-off" step="5" min="-180" max="180" '
        f'value="{e(st["night_offset"])}"> min after sunset</label></div>'
        f'<div class="ed-row"><button type="button" id="sch-save">Save</button>'
        f'<span id="sch-status" class="count"></span></div>'
        f'<p class="count">A theme picked by hand stays until the next switch time; then the '
        f'schedule takes over again. Scheduled switches are not announced on ntfy. Sunrise and '
        f'sunset are worked out here, from the coordinates (kept to 2 decimals, about 1 km); '
        f'nothing is looked up online. Use a negative offset for earlier.</p>'
        f'<h2 class="tab-title">Theme of the day '
        f'<span id="daily-state" class="count">{e(daily_summary(st))}</span></h2>'
        f'<div class="ed-row"><label><input type="checkbox" id="daily-enabled"'
        f'{" checked" if st["daily_enabled"] else ""}> Pick a new theme every day</label>'
        f'<label>at <input type="time" id="daily-at" value="{e(st["daily_at"])}"></label>'
        f'<label>from <select id="daily-pool">{pool_opts(st["daily_pool"])}</select></label></div>'
        f'<div class="ed-row"><button type="button" id="daily-save">Save</button>'
        f'<span id="daily-status" class="count"></span></div>'
        f'<p class="count">Never picks a hidden theme or the one already live.</p>'
        f'<h2 class="tab-title">Rotation '
        f'<span id="rotate-state" class="count">{e(rotate_summary(st))}</span></h2>'
        f'<div class="ed-row"><label><input type="checkbox" id="rotate-enabled"'
        f'{" checked" if st["rotate_enabled"] else ""}> Change theme every</label>'
        f'<label><input type="number" id="rotate-every" min="1" max="168" step="1" value="{e(st["rotate_every"])}"> hours</label>'
        f'<label>from <select id="rotate-pool">{pool_opts(st["rotate_pool"])}</select></label>'
        f'<label>order <select id="rotate-mode">'
        f'<option value="random"{" selected" if st["rotate_mode"] == "random" else ""}>random</option>'
        f'<option value="list"{" selected" if st["rotate_mode"] == "list" else ""}>my list, in order</option>'
        f'</select></label></div>'
        f'<div class="rotate-list-box" id="rotate-list-box"{" hidden" if st["rotate_mode"] != "list" else ""}>'
        f'<ol id="rotate-list">' + "".join(
            f'<li data-theme="{e(t)}"><span>{e(t)}</span>'
            f'<button type="button" data-move="up" aria-label="Move {e(t)} up">&uarr;</button>'
            f'<button type="button" data-move="down" aria-label="Move {e(t)} down">&darr;</button>'
            f'<button type="button" data-move="del" aria-label="Remove {e(t)}">&times;</button></li>'
            for t in st["rotate_list"]) + '</ol>'
        f'<div class="ed-row"><select id="rotate-add" data-themes>{opts("")}</select>'
        f'<button type="button" id="rotate-add-btn">Add to the list</button></div>'
        f'<p class="count">Applied top to bottom, then from the top again. E.g. seven themes every 24 hours '
        f'is one theme per weekday.</p></div>'
        f'<div class="ed-row"><button type="button" id="rotate-save">Save</button>'
        f'<span id="rotate-status" class="count"></span></div>'
        f'<p class="count">A random pick each time, never a hidden theme or the one already live. '
        f'Day/night, theme of the day and rotation take turns: turning one on turns the others off.</p></div>')


def pool_opts(cur):
    """The pool choices: favourites, all themes, then every collection."""
    e = lambda s: html.escape(str(s), quote=True)
    opt = lambda v, label: f'<option value="{e(v)}"{" selected" if v == cur else ""}>{e(label)}</option>'
    return (opt("favourites", "my favourites") + opt("all", "all themes")
            + '<optgroup label="Collections">' + "".join(opt(f"collection:{n}", n) for n in collections.names())
            + '</optgroup>')


def capture_banner():
    """A note while the nightly capture is cycling the live theme."""
    st = shots.capture_status()
    hidden = "" if st.get("running") else " hidden"
    return f'<p class="capture-banner" id="capture-banner" role="status"{hidden}>{html.escape(capture_text(st))}</p>'


def capture_text(st):
    if not st.get("running"):
        return ""
    left = st.get("minutes_left")
    return (f"Screenshot capture running: theme {st.get('index', 0)} of {st.get('themes', 0)}"
            + (f" ({st['theme']})" if st.get("theme") else "")
            + (f", about {left} min left" if left is not None else "")
            + f". The live theme changes every few seconds until it finishes, then goes back to "
            + f"{st.get('restore') or 'the one before'}.")


def collection_opts():
    e = lambda s: html.escape(str(s), quote=True)
    user = collections.read_user()
    return ('<option value="">All themes</option><optgroup label="Built in">'
            + "".join(f'<option value="{e(n)}">{e(n)}</option>' for n in collections.BUILTIN) + '</optgroup>'
            + ('<optgroup label="Yours">' + "".join(f'<option value="{e(n)}">{e(n)} ({len(v)})</option>'
                                                    for n, v in sorted(user.items())) + '</optgroup>' if user else ""))


def collections_json():
    """Your collections for app.js, as a JSON data block (not a script:
    the CSP allows no inline script, and this is never executed)."""
    data = json.dumps(collections.read_user()).replace("</", "<\\/")
    return f'<script type="application/json" id="collections-data">{data}</script>'


def rotate_summary(st):
    if not st["rotate_enabled"]:
        return "off"
    pool = ("your list" if st.get("rotate_mode") == "list" else schedule.pool_label(st["rotate_pool"]))
    every = st["rotate_every"]
    return (f"on · every {every} hour{'s' if every != 1 else ''} from {pool} ({st.get('rotate_pool_size', 0)})"
            + (f" · next {st['rotate_next']}" if st.get("rotate_next") else ""))


def daily_summary(st):
    if not st["daily_enabled"]:
        return "off"
    pool = schedule.pool_label(st["daily_pool"])
    return f"on · from {pool} ({st.get('daily_pool_size', 0)}) · next pick {st.get('daily_next', '')}"


def schedule_summary(st):
    if not st["enabled"]:
        return "off"
    if "slot" not in st:
        return "on, but a theme is missing"
    return (f"on{' · by the sun' if st.get('sun') else ''} · now {st['slot']} ({st[st['slot']]}) · "
            f"next: {st['next_theme']} at {st['next_at']}")


def _dur(sec):
    sec = int(sec)
    if sec >= 86400:
        return f"{sec // 86400}d {sec % 86400 // 3600}h"
    if sec >= 3600:
        return f"{sec // 3600}h {sec % 3600 // 60}m"
    return f"{sec // 60}m" if sec >= 60 else f"{sec}s"


def stats_html():
    return new_shots_html() + capture_history_html() + _usage_html()


def _usage_html():
    st = state.usage_stats()
    if not st:
        return ("<p class='none'>No history yet -- apply a theme from here and it starts counting.</p>"
                + ratings_html() + digest_html())
    e = html.escape
    rows_t = "".join(f"<li><b>{e(t)}</b> <span>{_dur(s)}</span></li>" for t, s in st["by_time"])
    rows_c = "".join(f"<li><b>{e(t)}</b> <span>{c}&times;</span></li>" for t, c in st["by_count"])
    return (f"<p class='count'>{st['changes']} changes across {st['distinct']} themes since "
            f"{e(st['since'])}. Only changes made in the picker are counted.</p>"
            f"<div class='stats'><div><h3>Most time on screen</h3><ol>{rows_t}</ol></div>"
            f"<div><h3>Most applied</h3><ol>{rows_c}</ol></div></div>" + ratings_html() + digest_html())


NEW_SHOTS_SHOWN = 300


def new_shots_html():
    """Themes the last capture photographed: a strip of thumbnails at the top
    of Stats, each opening that theme's preview."""
    if not shots.screenshot_index():
        return ""                       # no capture here: nothing to report, not even "none"
    items, label = shots.new_shots()
    e = html.escape
    if not items:
        return (f"<h3 class='tab-sub'>New screenshots</h3><p class='count'>None from {e(label)}.</p>")
    cards = "".join(
        f"<button type='button' class='new-shot' data-open='{e(t)}' title='Preview {e(t)}'>"
        f"<img src='/shots/thumb/{e(apps[0])}_{e(t)}.jpg' alt='' loading='lazy' width='160' height='100'>"
        f"<span>{e(t)}</span></button>" for t, apps in items[:NEW_SHOTS_SHOWN])
    more = (f" Showing the newest {NEW_SHOTS_SHOWN}." if len(items) > NEW_SHOTS_SHOWN else "")
    return (f"<h3 class='tab-sub'>New screenshots</h3><p class='count'>{len(items)} "
            f"theme{'s' if len(items) != 1 else ''} photographed in {e(label)}.{more}</p>"
            f"<div class='new-shots'>{cards}</div>")


def capture_history_html():
    """The last runs of the capture: when, how long (with a bar), how much."""
    runs = shots.capture_history()
    if not runs:
        return ""
    e = html.escape
    longest = max((r.get("minutes") or 0) for r in runs) or 1
    rows = []
    for r in runs:
        try:
            when = datetime.strptime(r["started"], "%Y-%m-%dT%H:%M:%S%z").strftime("%a %d %b, %H:%M")
        except (TypeError, ValueError):
            when = str(r.get("started", ""))
        mins = r.get("minutes") or 0
        bad_cls = " class='bad'" if (r.get("failed") or 0) + (r.get("skipped") or 0) else ""
        rows.append(
            f"<tr><td>{e(when)}</td>"
            f"<td><span class='bar' style='width:{max(2, round(100 * mins / longest))}%'></span> {mins} min</td>"
            f"<td>{r.get('done') or 0} of {r.get('shots') or 0}</td>"
            f"<td{bad_cls}>{r.get('failed') or 0} failed, {r.get('skipped') or 0} skipped</td></tr>")
    return ("<h3 class='tab-sub'>Capture runs</h3>"
            "<table class='cap-hist'><thead><tr><th>Started</th><th>Duration</th><th>Shots</th><th>Problems</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def digest_html():
    """The weekly digest: when it goes out, and a preview button."""
    at = config.SETTINGS["ntfy.digest"]
    when = (f"Sent every {at.split()[0].capitalize()} at {at.split()[1]} on the ntfy topic." if at
            else "Off: set ntfy.digest (e.g. \"mon 09:00\") to get it on ntfy every week.")
    return (f"<h3 class='tab-sub'>Weekly digest</h3><p class='count'>{html.escape(when)}</p>"
            "<p><button type='button' id='digest-preview-btn'>Preview this week's digest</button></p>"
            "<pre id='digest-preview' class='digest-preview' hidden></pre>")


def ratings_html():
    """Liked and disliked themes, and how the random picks used them."""
    rs = state.rating_stats()
    if not rs:
        return ("<h3 class='tab-sub'>Ratings</h3><p class='count'>No ratings yet: like or dislike a theme in "
                "its preview, and random picks favour or skip it.</p>")
    e = html.escape
    row = lambda t, n, s: f"<li><b>{e(t)}</b> <span>{n}&times; · {_dur(s) if s else 'never on'}</span></li>"
    p = rs["picks"]
    total = sum(p.values())
    picks = (f"Of {total} random pick{'s' if total != 1 else ''} (theme of the day, rotation), "
             f"{p.get('liked', 0)} were liked themes and {p.get('unrated', 0)} unrated"
             + (f"; {p['disliked']} were made before their theme was disliked." if p.get("disliked") else ".")
             if total else "No random picks yet (theme of the day, rotation).")
    return (f"<h3 class='tab-sub'>Ratings</h3><p class='count'>{e(picks)} Liked themes come up three "
            f"times as often; disliked ones never.</p>"
            f"<div class='stats'><div><h3>&#128077; Liked ({len(rs['liked'])})</h3><ol>"
            + "".join(row(*r) for r in rs["liked"]) + "</ol></div>"
            f"<div><h3>&#128078; Disliked ({len(rs['disliked'])})</h3><ol>"
            + "".join(row(*r) for r in rs["disliked"]) + "</ol></div></div>")


def theme_colour(theme):
    """The theme's page colour as #rrggbb (a gradient's first stop), for the
    browser's toolbar and the installed app's splash screen."""
    st = colour.stops(themes.theme_palette(theme).get("--main-bg-color", ""))
    return colour.to_hex(st[0]) if st else "#11141b"


def manifest(base="/"):
    """The web app manifest: the picker installs as an app on phones and
    desktops. Colours follow the live theme. `base`: where the picker is
    served ("/" live; "./" in the static demo)."""
    bg = theme_colour(themes.current_theme())
    icon = lambda name, size, purpose="any": {"src": f"{base}static/{name}?v={VERSION[name]}", "sizes": size,
                                              "type": "image/png", "purpose": purpose}
    return json.dumps({
        "name": "Theme Picker", "short_name": "Themes",
        "description": "Switch the theme.park theme of every app at once.",
        "start_url": f"{base}#themes", "scope": base, "display": "standalone",
        "background_color": bg, "theme_color": bg,
        "icons": [icon("icon-192.png", "192x192"), icon("icon-512.png", "512x512"),
                  icon("icon-maskable-512.png", "512x512", "maskable")],
    }, indent=1)


def render_page(message="", preview=""):
    """preview: a theme to dress the page in WITHOUT applying it (/?preview=,
    the shareable link). Ignored unless it exactly matches a known theme."""
    active = themes.current_theme()
    preview = preview if preview and preview != active and preview in themes.allowed_themes() else ""
    sheet = themes.theme_css_url(preview or active)
    # The picker dresses itself in whatever theme is currently live, loading
    # the same variable sheet the per-app stylesheets import (theme_css_url
    # picks the right directory). Every value in style.css has a fallback so
    # the page still reads correctly if theme-park is down.
    theme_link = (
        f'<link rel="stylesheet" id="theme-css" href="{html.escape(sheet)}">'
        if sheet else '<link rel="stylesheet" id="theme-css" href="">'
    )
    msg_hidden = "" if message else ' hidden'
    preview_banner = (
        f'<form class="preview-banner" id="preview-banner" method="post" action="/set-theme">'
        f'Previewing <b>{html.escape(preview)}</b>. It is not applied; the live theme is still '
        f'<b>{html.escape(active)}</b>. '
        f'<button name="theme" value="{html.escape(preview, quote=True)}">Apply it</button> '
        f'<a href="/#themes">Back to live</a></form>') if preview else ""
    msg_text = html.escape(message)
    shot_idx, dates, today = shots.screenshot_index(), state.theme_dates(), date.today()
    favs = frozenset(state.read_favourites())
    hidden = frozenset(state.read_hidden())
    ratings = state.read_ratings()
    hidden_forms = frozenset(state.read_hidden_forms())
    pairs = themes.variant_pairs()
    grid = lambda names, sect: theme_grid(names, sect, active, shot_idx, dates, today, favs, pairs, hidden, ratings,
                                          hidden_forms)
    app_opts = "".join(f'<option value="{a}">{a} screenshots</option>' for a in shots.screenshot_apps())
    base_opts = current_opt(active)
    fams = "".join(
        f'<button type="button" class="fam" data-family="{n}" title="{n} accents">'
        f'<i style="background:{c}"></i>{n}</button>' for n, c in FAMILIES)
    return PAGE_TEMPLATE.format(
        theme_link=theme_link, style_v=VERSION["style.css"], icon_v=VERSION["icon.svg"], active=html.escape(active),
        theme_colour=theme_colour(preview or active), touch_v=VERSION["apple-touch-icon.png"],
        history=history_html(active), undo=undo_html(active), app_opts=app_opts, fams=fams,
        grid_official=grid(themes.official_themes(), "official"),
        grid_community=grid(themes.community_themes(), "community"),
        **{f"grid_{g.replace('-', '_')}": grid(names, g) for g, names in custom_groups(pairs).items()},
        ed_twin_note=("" if deploy.enabled() and not config.MAKE_TWINS else
                      '<span class="count" id="ed-twin-note">A light/dark twin of it is made automatically.</span>'),
        live_swatch=swatch_html(active),
        msg_hidden=msg_hidden, msg_text=msg_text, preview_banner=preview_banner,
        early_v=VERSION["early.js"], apps=apps_html(active), groups=groups_html(),
        stats=stats_html(), schedule=schedule_html(), base_opts=base_opts, theme_opts=theme_opts_template(),
        collection_opts=collection_opts(), collections_json=collections_json(), capture_banner=capture_banner(),
        script_v=VERSION["app.js"])

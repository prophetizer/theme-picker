"""The picker page: theme tiles, panels, and the template they fill."""

import hashlib
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import config, schedule, shots, state, themes
from .colour import FAMILIES
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
STATIC = {name: (WEB_DIR / name).read_bytes() for name in ("style.css", "app.js", "early.js", "icon.svg")}
STATIC_TYPES = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                "early.js": "text/javascript; charset=utf-8",
                "icon.svg": "image/svg+xml"}
VERSION = {name: hashlib.sha256(data).hexdigest()[:12] for name, data in STATIC.items()}


def swatch_html(theme):
    pal = themes.theme_palette(theme)
    if not pal:
        return ""
    cells = "".join(
        f'<i style="background:{html.escape(pal[v], quote=True)}"></i>'
        for v in themes.SWATCH_VARS if v in pal
    )
    return f'<span class="swatch">{cells}</span>' if cells else ""


def tile_html(t, section, active, shot_idx, dates, today, favs=frozenset(), twin="", twin_of=""):
    """One theme tile. A theme with a generated twin carries data-twin; the
    twin itself data-twin-of, and sits right after it in the same section.
    The page shows one form of each pair at a time (the sun/moon switch, or
    the sidebar's "show every theme as"); without JavaScript both show."""
    m = theme_metrics(t)
    grad = themes.is_gradient(t)
    added = dates.get(t, "")
    try:
        # Generated variants arrive a hundred at a time; badging them "new"
        # would bury the themes that really are.
        fresh = not twin_of and section != "variants" and bool(added) and (today - date.fromisoformat(added)).days <= NEW_DAYS
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
        tags.append(f'<span class="tag new" title="Added {e(added)}">new</span>')
    if grad:
        tags.append('<span class="tag grad">gradient</span>')
    peek = (f'<span class="peek" title="Preview {len(apps)} screenshots (P)" aria-label="Screenshots">&#9635;</span>'
            if apps else "")
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
        f'data-hc="{int(m["high_contrast"])}" '
        f'data-shots="{e(" ".join(apps))}" data-fav="{int(fav)}"{pair_attrs}>'
        f'<span class="tile-top"><span class="name" title="{e(t)}">{e(t)}</span>{star}</span>'
        f'{swatch_html(t)}'
        f'<span class="tile-foot"><span class="tags">{"".join(tags)}</span>{peek}{forms}</span></button>'
    )


def theme_grid(names, section, active, shot_idx, dates, today, favs=frozenset(), pairs=None):
    """Tiles for a section; with `pairs`, each theme's generated twin follows it."""
    pairs = pairs or {}
    entries = []
    for t in names:
        entries.append((t, pairs.get(t, ""), ""))
        if t in pairs:
            entries.append((pairs[t], "", t))
    every = [t for t, _, _ in entries]
    themes.warm_palette_cache(every)
    with ThreadPoolExecutor(max_workers=8) as ex:     # metrics read the same cache
        list(ex.map(theme_metrics, every))
    return "\n".join(tile_html(t, section, active, shot_idx, dates, today, favs, twin=tw, twin_of=of)
                     for t, tw, of in entries)


def apps_html(active):
    """One card per themed app: where it is, a pin control, and what it is served."""
    pinned = state.read_overrides()
    opts = "".join(f'<option value="{html.escape(t)}">{html.escape(t)}</option>'
                   for t in sorted(themes.allowed_themes()))
    cards = []
    for a in state.load_apps():
        n = html.escape(a["name"])
        cur = pinned.get(a["name"], "")
        cards.append(
            f'<div class="app-card" data-app="{n}">'
            f'<a href="https://{html.escape(a["host"])}.{html.escape(config.DOMAIN)}/" '
            f'target="_blank" rel="noopener">{n}</a>'
            f'<select class="pin" data-app="{n}" data-current="{html.escape(cur)}" aria-label="Theme for {n}">'
            f'<option value="">follows the live theme</option>{opts}</select>'
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
        out = ['<option value="">choose a theme...</option>']
        for t in sorted(themes.allowed_themes()):
            mode = theme_metrics(t)["mode"]
            out.append(f'<option value="{e(t)}"{" selected" if t == sel else ""}>'
                       f'{e(t)}{" · " + mode if mode else ""}</option>')
        return "".join(out)
    return (
        f'<div class="sched" id="schedule-panel"><h2 class="tab-title">Day/night schedule '
        f'<span id="sch-state" class="count">{e(schedule_summary(st))}</span></h2>'
        f'<div class="ed-row"><label><input type="checkbox" id="sch-enabled"'
        f'{" checked" if st["enabled"] else ""}> Switch themes by time of day</label></div>'
        f'<div class="ed-row"><label>Day <select id="sch-day">{opts(st["day"])}</select></label>'
        f'<label>from <input type="time" id="sch-day-at" value="{e(st["day_at"])}"></label></div>'
        f'<div class="ed-row"><label>Night <select id="sch-night">{opts(st["night"])}</select></label>'
        f'<label>from <input type="time" id="sch-night-at" value="{e(st["night_at"])}"></label></div>'
        f'<div class="ed-row"><button type="button" id="sch-save">Save</button>'
        f'<span id="sch-status" class="count"></span></div>'
        f'<p class="count">A theme picked by hand stays until the next switch time; then the '
        f'schedule takes over again. Scheduled switches are not announced on ntfy.</p></div>')


def schedule_summary(st):
    if not st["enabled"]:
        return "off"
    if "slot" not in st:
        return "on, but a theme is missing"
    return (f"on · now {st['slot']} ({st[st['slot']]}) · next: {st['next_theme']} "
            f"at {st['next_at']}")


def _dur(sec):
    sec = int(sec)
    if sec >= 86400:
        return f"{sec // 86400}d {sec % 86400 // 3600}h"
    if sec >= 3600:
        return f"{sec // 3600}h {sec % 3600 // 60}m"
    return f"{sec // 60}m" if sec >= 60 else f"{sec}s"


def stats_html():
    st = state.usage_stats()
    if not st:
        return "<p class='none'>No history yet -- apply a theme from here and it starts counting.</p>"
    e = html.escape
    rows_t = "".join(f"<li><b>{e(t)}</b> <span>{_dur(s)}</span></li>" for t, s in st["by_time"])
    rows_c = "".join(f"<li><b>{e(t)}</b> <span>{c}&times;</span></li>" for t, c in st["by_count"])
    return (f"<p class='count'>{st['changes']} changes across {st['distinct']} themes since "
            f"{e(st['since'])}. Only changes made in the picker are counted.</p>"
            f"<div class='stats'><div><h4>Most time on screen</h4><ol>{rows_t}</ol></div>"
            f"<div><h4>Most applied</h4><ol>{rows_c}</ol></div></div>")


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
    pairs = themes.variant_pairs()
    grid = lambda names, sect: theme_grid(names, sect, active, shot_idx, dates, today, favs, pairs)
    app_opts = "".join(f'<option value="{a}">{a} screenshots</option>' for a in shots.APP_ORDER)
    base_opts = "".join(f'<option value="{html.escape(t)}"{" selected" if t == active else ""}>'
                        f'{html.escape(t)}</option>' for t in sorted(themes.allowed_themes()))
    fams = "".join(
        f'<button type="button" class="fam" data-family="{n}" title="{n} accents">'
        f'<i style="background:{c}"></i>{n}</button>' for n, c in FAMILIES)
    return PAGE_TEMPLATE.format(
        theme_link=theme_link, style_v=VERSION["style.css"], icon_v=VERSION["icon.svg"], active=html.escape(active),
        history=history_html(active), undo=undo_html(active), app_opts=app_opts, fams=fams,
        grid_official=grid(themes.official_themes(), "official"),
        grid_community=grid(themes.community_themes(), "community"),
        grid_custom=grid(themes.own_themes(), "custom"),
        live_swatch=swatch_html(active),
        msg_hidden=msg_hidden, msg_text=msg_text, preview_banner=preview_banner,
        early_v=VERSION["early.js"], apps=apps_html(active),
        stats=stats_html(), schedule=schedule_html(), base_opts=base_opts,
        script_v=VERSION["app.js"])

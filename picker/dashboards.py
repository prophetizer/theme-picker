"""Stylesheets that dress Homepage and Glance in the live theme.

theme.park themes the apps behind Traefik, but not the dashboards in front of
them. Rather than writing into either dashboard's config (which would mean
mounting their config directories into this container), the picker SERVES a
stylesheet per dashboard, recomputed from the live theme on each request:

  Homepage: /dashboards/homepage.css -- @import it from Homepage's custom.css
  Glance:   /dashboards/glance.css   -- set it as Glance's theme.custom-css-file
  Homarr:   /dashboards/homarr.css   -- @import it from each board's custom CSS

Each dashboard links it once; after that it follows every theme change on its
next page load. Colours come from editor.theme_vars(), the same #rrggbb
flattening the theme editor starts from.
"""

import colorsys

from . import colour as c
from . import themes
from .editor import theme_vars
from .metrics import theme_metrics
from .variants import fix_contrast


def _mix(a, b, t):
    """Blend two (r, g, b) tuples: t=0 is a, t=1 is b."""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _triplet(rgb):
    return " ".join(str(int(round(x))) for x in rgb)


def _vars(theme):
    v = theme_vars(theme)
    return {k: c.hex_rgb(h) for k, h in v.items() if h}


def _readable_vars(theme):
    """_vars(), made readable for Homepage and Homarr. Where the theme's text
    or muted colour is faint on its page colour -- nearly always a gradient
    whose first stop is a bright glow (74 of 950 themes) -- the page becomes
    glance_background()'s readable stop, as a solid colour; and text that is
    faint on the page or panels gets only its lightness moved. The other
    themes are returned exactly as they were."""
    v = dict(_vars(theme))
    page = v["page_bg"]
    # Only a gradient has another stop to move to; a faint solid theme keeps
    # its page and gets its text fixed below.
    if themes.is_gradient(theme) and (c.contrast(v["text"], page) < 4.5 or c.contrast(v["muted"], page) < 3):
        v["page_bg"] = glance_background(theme, v)
        v.pop("page_bg2", None)                     # Homarr's body gradient: solid instead
    bgs = [v["page_bg"]] + ([v["panel_bg"]] if v.get("panel_bg") else [])
    for k, need in (("text", 4.5), ("text_hover", 4.5), ("muted", 3)):
        if v.get(k) and min(c.contrast(v[k], b) for b in bgs) < need:
            v[k] = fix_contrast(v[k], bgs, need + 0.05) or v[k]
    return v


def homepage_ramp(theme):
    """Homepage's ten-step palette (--color-50 lightest ... --color-900
    darkest), built from the theme's own surfaces and text so that every
    Homepage colour -- page, cards, borders, text -- comes from the theme.
    Always ordered light to dark, which is what Homepage's light and dark
    modes both assume; a light theme simply lands at the light end."""
    v = _readable_vars(theme)
    page, panel, text, muted = v["page_bg"], v["panel_bg"], v["text"], v["muted"]
    white, black = (255, 255, 255), (0, 0, 0)
    if theme_metrics(theme)["mode"] == "light":
        ramp = {50: page, 100: panel, 200: _mix(panel, muted, 0.35), 300: _mix(panel, muted, 0.7),
                400: muted, 500: _mix(muted, text, 0.4), 600: _mix(muted, text, 0.75), 700: text,
                800: _mix(text, black, 0.4), 900: _mix(text, black, 0.7)}
    else:
        ramp = {900: page, 800: panel, 700: _mix(panel, muted, 0.35), 600: _mix(panel, muted, 0.7),
                500: muted, 400: _mix(muted, text, 0.4), 300: _mix(muted, text, 0.75), 200: text,
                100: _mix(text, white, 0.5), 50: _mix(text, white, 0.8)}
    # Themes differ in which surface is lighter (many light themes put white
    # panels on an off-white page), so the ten colours are handed out by
    # luminance: 50 is always the lightest, 900 the darkest.
    colours = sorted(ramp.values(), key=c.lum, reverse=True)
    return dict(zip(sorted(ramp), colours)), v["button"], v["link"]


def homepage_css(theme):
    ramp, start, stop = homepage_ramp(theme)
    lines = [f"  --color-{k}: {_triplet(rgb)} !important;" for k, rgb in ramp.items()]
    lines += [f"  --color-logo-start: {_triplet(start)} !important;",
              f"  --color-logo-stop: {_triplet(stop)} !important;"]
    # Homepage loads custom.css BEFORE its own stylesheet, and sets the
    # palette on a .theme-<colour> class; !important is what lets these win
    # regardless of order or which element carries that class.
    return (f"/* Homepage dressed in the theme picker's live theme: {theme} */\n"
            ":root, [class*=\"theme-\"] {\n" + "\n".join(lines) + "\n}\n")


def _hsl(rgb):
    h, l, s = colorsys.rgb_to_hls(*(x / 255 for x in rgb))
    return round(h * 360), round(s * 100), round(l * 100)


def glance_background(theme, v=None):
    """The one solid colour Glance gets for a page that may be a gradient.

    Glance has a single background (--bgh/--bgs/--bgl). The first stop of a
    gradient is often its glow -- Boreal's is a bright #4f9d69 at the bottom
    edge, over a page that is mostly dark green -- and Glance on that was
    unreadable. So: the stop closest to the gradient's average colour among
    those the theme's text reads on (body 7:1, muted 4.5:1); failing that, the
    same among the panel's stops; else the stop with the best contrast."""
    v = v or _vars(theme)
    pal = themes.theme_palette(theme)
    readable = lambda x: c.contrast(x, v["text"]) >= 7 and c.contrast(x, v["muted"]) >= 4.5
    candidates = []
    # The page first; then the panels, which is where a vivid gradient theme
    # (bright page, darkened panels) is built for its text to read.
    for var, flat in (("--main-bg-color", "page_bg"), ("--modal-bg-color", "panel_bg")):
        st = c.surface(pal.get(var, "")) or ([v[flat]] if v.get(flat) else [])
        candidates += st
        ok = [x for x in st if readable(x)]
        if ok:
            mean = tuple(sum(x[i] for x in st) / len(st) for i in range(3))
            return min(ok, key=lambda x: sum((x[i] - mean[i]) ** 2 for i in range(3)))
    return max(candidates or [v["page_bg"]], key=lambda x: c.contrast(x, v["text"]))


def _subdue(muted, bg):
    """Glance's faintest text (timestamps, captions): the muted colour faded
    toward the background, but never under 3:1 on it."""
    for t in (0.45, 0.35, 0.25, 0.15, 0.05, 0.0):
        x = _mix(muted, bg, t)
        if c.contrast(x, bg) >= 3.05:          # a margin: #rrggbb rounding loses a hair
            return x
    return muted


def glance_css(theme):
    """Glance derives its surfaces from a background HSL (--bgh/--bgs/--bgl)
    and its text from FIXED lightnesses (58% base, 35% subdued, ...) that only
    suit a dark page -- so the text colours are set from the theme as well,
    or a mid-light background swallowed them. Light themes also get Glance's
    light scheme."""
    v = _vars(theme)
    bg = glance_background(theme, v)
    h, s, l = _hsl(bg)
    ph, ps, pl = _hsl(v["link"])
    light = theme_metrics(theme)["mode"] == "light"
    # A theme whose own text or muted colour is faint (the low-contrast
    # badge) gets only its lightness moved, as the picker does for its own
    # interface (app.js uiColours); every other theme's colours are kept.
    text = fix_contrast(v["text"], [bg], 4.55) or v["text"]
    muted = fix_contrast(v["muted"], [bg], 4.55) or v["muted"]
    lines = [f"  --bgh: {h} !important;", f"  --bgs: {s}% !important;", f"  --bgl: {l}% !important;",
             f"  --color-primary: hsl({ph}, {ps}%, {pl}%) !important;",
             f"  --color-text-highlight: {c.to_hex(fix_contrast(v.get('text_hover') or text, [bg], 4.55) or text)} !important;",
             f"  --color-text-paragraph: {c.to_hex(text)} !important;",
             f"  --color-text-base: {c.to_hex(text)} !important;",
             f"  --color-text-base-muted: {c.to_hex(muted)} !important;",
             f"  --color-text-subdue: {c.to_hex(_subdue(muted, bg))} !important;"]
    if light:
        lines.append("  --scheme: 100% - !important;")          # what Glance's light: true sets
    return (f"/* Glance dressed in the theme picker's live theme: {theme} */\n"
            ":root {\n" + "\n".join(lines) + "\n}\n")


def _rgb(rgb, alpha=None):
    r, g, b = (int(round(x)) for x in rgb)
    return f"rgb({r}, {g}, {b})" if alpha is None else f"rgba({r}, {g}, {b}, {alpha})"


def homarr_css(theme):
    """Homarr is Mantine v7: every colour derives from a few semantic
    variables (--mantine-color-body/text/dimmed/default/anchor), the
    --mantine-color-dark-0..9 ramp the dark scheme reads, and the primary
    colour's filled/light variants. All are set for BOTH schemes -- Homarr can
    follow the OS -- and !important, because Homarr applies each board's own
    primary colour and opacity too. The body gets the theme's page colour (its
    gradient if it has one) so the translucent tiles have something to show."""
    v = _readable_vars(theme)
    page, panel, text, muted = v["page_bg"], v["panel_bg"], v["text"], v["muted"]
    button, hover, label, link = v["button"], v["button_hover"], v["button_text"], v["link"]
    black = (0, 0, 0)
    dark = {0: text, 1: _mix(text, muted, 0.5), 2: muted, 3: _mix(muted, panel, 0.5),
            4: _mix(panel, text, 0.18), 5: _mix(panel, text, 0.08), 6: panel, 7: page,
            8: _mix(page, black, 0.2), 9: _mix(page, black, 0.4)}
    decl = {
        "--mantine-color-body": _rgb(page), "--mantine-color-text": _rgb(text),
        "--mantine-color-bright": _rgb(v["text_hover"]), "--mantine-color-dimmed": _rgb(muted),
        "--mantine-color-placeholder": _rgb(muted), "--mantine-color-anchor": _rgb(link),
        "--mantine-color-default": _rgb(panel), "--mantine-color-default-hover": _rgb(dark[5]),
        "--mantine-color-default-color": _rgb(text), "--mantine-color-default-border": _rgb(dark[4]),
        "--mantine-primary-color-filled": _rgb(button), "--mantine-primary-color-filled-hover": _rgb(hover),
        "--mantine-primary-color-light": _rgb(button, 0.15), "--mantine-primary-color-light-hover": _rgb(button, 0.22),
        "--mantine-primary-color-light-color": _rgb(link), "--mantine-primary-color-contrast": _rgb(label),
    }
    decl.update({f"--mantine-color-dark-{k}": _rgb(c) for k, c in dark.items()})
    lines = [f"  {k}: {val} !important;" for k, val in decl.items()]
    page2 = v.get("page_bg2")
    bg = (f"linear-gradient(160deg, {_rgb(page)} 0%, {_rgb(page2)} 100%) fixed"
          if page2 else _rgb(page))
    # Homarr's own item tiles, item badges and widget hover panels take their
    # background from --mantine-color-dark-6 in dark mode but from
    # --mantine-color-WHITE in light mode (with Homarr following the OS), so
    # the palette above never reached them in light mode. Their class names
    # carry a build hash (item-module__Qjq11G__itemCard), so match the stable
    # parts. Homarr's per-board --opacity is kept.
    pr, pg, pb = (int(round(x)) for x in panel)
    br, bgn, bb = (int(round(x)) for x in dark[4])
    cards = (
        '[class*="item-module__"][class*="__itemCard"],\n'
        '[class*="item-content-module__"][class*="__badge"] {\n'
        f"  --background-color: rgba({pr}, {pg}, {pb}, var(--opacity, 1)) !important;\n"
        f"  --border-color: rgba({br}, {bgn}, {bb}, var(--opacity, 1)) !important;\n}}\n"
        '[class*="widget-hover-overlay-module__"][class*="__panel"] {\n'
        f"  --background-color: rgba({pr}, {pg}, {pb}, 0.96) !important;\n"
        f"  --border-color: rgba({br}, {bgn}, {bb}, 0.9) !important;\n}}\n")
    return (f"/* Homarr dressed in the theme picker's live theme: {theme} */\n"
            ":root, :root[data-mantine-color-scheme], [data-mantine-color-scheme] {\n"
            + "\n".join(lines) + "\n}\n"
            f"html, body {{\n  background: {bg} !important;\n}}\n" + cards)


STYLESHEETS = {"homepage.css": homepage_css, "glance.css": glance_css, "homarr.css": homarr_css}

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
from .editor import theme_vars
from .metrics import theme_metrics


def _mix(a, b, t):
    """Blend two (r, g, b) tuples: t=0 is a, t=1 is b."""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _triplet(rgb):
    return " ".join(str(int(round(x))) for x in rgb)


def _vars(theme):
    v = theme_vars(theme)
    return {k: c.hex_rgb(h) for k, h in v.items() if h}


def homepage_ramp(theme):
    """Homepage's ten-step palette (--color-50 lightest ... --color-900
    darkest), built from the theme's own surfaces and text so that every
    Homepage colour -- page, cards, borders, text -- comes from the theme.
    Always ordered light to dark, which is what Homepage's light and dark
    modes both assume; a light theme simply lands at the light end."""
    v = _vars(theme)
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


def glance_css(theme):
    """Glance derives every colour from a background HSL (--bgh/--bgs/--bgl)
    and a primary colour; light themes also need its light scheme."""
    v = _vars(theme)
    h, s, l = _hsl(v["page_bg"])
    ph, ps, pl = _hsl(v["link"])
    light = theme_metrics(theme)["mode"] == "light"
    lines = [f"  --bgh: {h} !important;", f"  --bgs: {s}% !important;", f"  --bgl: {l}% !important;",
             f"  --color-primary: hsl({ph}, {ps}%, {pl}%) !important;"]
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
    v = _vars(theme)
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

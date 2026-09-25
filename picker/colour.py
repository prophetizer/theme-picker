"""Colour maths over CSS values: stop parsing, layer compositing, luminance,
contrast and accent families. Pure functions, no I/O.

The same checks used to vet the custom themes -- body and muted text against
the panel surface, button label against the button -- are applied to ALL
themes, official and community included, which had never been measured.
Colour stops are read out of whatever the variable holds: hex (3/4/6/8
digit), rgb()/rgba(), hsl()/hsla(), inline var() references, and
theme.park's bare "R, G, B" triples. For a gradient the WORST stop counts,
since text has to be readable across the whole panel. Stops under 50%
opacity are ignored: what shows through them depends on the backdrop, which
cannot be known here. That makes this an approximation for heavily
translucent themes -- the lightbox screenshots are the ground truth.
"""

import colorsys
import re

COLOUR = re.compile(
    r"#(?P<hex>[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b"
    r"|rgba?\(\s*(?P<r>[\d.]+%?)\s*[, ]\s*(?P<g>[\d.]+%?)\s*[, ]\s*(?P<b>[\d.]+%?)"
    r"\s*(?:[,/]\s*(?P<ra>[\d.]+%?))?\s*\)"
    r"|hsla?\(\s*(?P<h>[\d.]+)(?:deg)?\s*[, ]\s*(?P<s>[\d.]+)%\s*[, ]\s*(?P<l>[\d.]+)%"
    r"\s*(?:[,/]\s*(?P<ha>[\d.]+%?))?\s*\)")
TRIPLE = re.compile(r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*")
FAMILIES = [("red", "#e5484d"), ("orange", "#f76b15"), ("yellow", "#ffc53d"),
            ("green", "#30a46c"), ("cyan", "#12a594"), ("blue", "#0090ff"),
            ("purple", "#8e4ec6"), ("pink", "#d6409f"), ("neutral", "#8b8d98")]


def _alpha(v):
    if v is None:
        return 1.0
    return float(v[:-1]) / 100 if v.endswith("%") else float(v)


def _chan(v):
    return float(v[:-1]) * 2.55 if v.endswith("%") else float(v)


def stops(value):
    """Opaque-enough colour stops in a CSS value, in order, as (r, g, b)."""
    out = []
    for m in COLOUR.finditer(value or ""):
        try:
            if m.group("hex"):
                h = m.group("hex")
                if len(h) in (3, 4):
                    h = "".join(c * 2 for c in h)
                rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
                a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
            elif m.group("r"):
                rgb = tuple(_chan(m.group(k)) for k in "rgb")
                a = _alpha(m.group("ra"))
            else:
                r, g, b = colorsys.hls_to_rgb(float(m.group("h")) % 360 / 360,
                                              float(m.group("l")) / 100,
                                              float(m.group("s")) / 100)
                rgb = (r * 255, g * 255, b * 255)
                a = _alpha(m.group("ha"))
        except ValueError:
            continue
        if a >= 0.5:
            out.append(tuple(max(0.0, min(255.0, c)) for c in rgb))
    return out


def stops_alpha(value):
    """Every colour stop in a CSS value as ((r, g, b), alpha), none dropped."""
    out = []
    for m in COLOUR.finditer(value or ""):
        try:
            if m.group("hex"):
                h = m.group("hex")
                if len(h) in (3, 4):
                    h = "".join(c * 2 for c in h)
                rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
                a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
            elif m.group("r"):
                rgb, a = tuple(_chan(m.group(k)) for k in "rgb"), _alpha(m.group("ra"))
            else:
                r, g, b = colorsys.hls_to_rgb(float(m.group("h")) % 360 / 360,
                                              float(m.group("l")) / 100, float(m.group("s")) / 100)
                rgb, a = (r * 255, g * 255, b * 255), _alpha(m.group("ha"))
        except ValueError:
            continue
        out.append((tuple(max(0.0, min(255.0, c)) for c in rgb), max(0.0, min(1.0, a))))
    return out


def layers(value):
    """Split a background shorthand into its comma-separated layers, top first.
    Commas inside parentheses (gradient stop lists) do not split."""
    out, depth, cur = [], 0, ""
    for ch in value or "":
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [l for l in out if COLOUR.search(l)]


def surface(value):
    """Colours a background actually shows, compositing stacked layers.

    Several community themes (the whole Blackberry family) paint a dark
    translucent overlay OVER an opaque bright gradient. Reading every layer's
    stops as though each were visible made those themes look light and
    unreadable when on screen they are dark with a coloured glow. So: take the
    bottom layer's opaque stops, then blend each layer above onto them using
    that layer's average colour and opacity -- an estimate of the typical
    panel, not of its single lightest corner. Single-layer backgrounds, which
    is nearly all of them, come out exactly as before.
    """
    ls = layers(value)
    if not ls:
        return []
    base = [rgb for rgb, a in stops_alpha(ls[-1]) if a >= 0.5]
    for layer in reversed(ls[:-1]):                  # bottom-up, like the browser
        st = stops_alpha(layer)
        weight = sum(a for _, a in st)
        if not base or not st or weight <= 0:
            continue
        a = weight / len(st)
        col = [sum(c[i] * w for c, w in st) / weight for i in range(3)]
        base = [tuple(a * col[i] + (1 - a) * b[i] for i in range(3)) for b in base]
    return base


def lum(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def decls(css):
    """Custom properties with inline var() references expanded."""
    raw = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+);", css))

    def expand(val, depth=0):
        if depth > 5:
            return val
        return re.sub(r"var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)",
                      lambda m: expand(raw.get(m.group(1), m.group(2) or ""), depth + 1),
                      val)
    return {k: expand(v).strip() for k, v in raw.items()}


def family(rgb):
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if s < 0.18 or l < 0.08 or l > 0.95:
        return "neutral", 0.0
    deg = h * 360
    for name, lo, hi in (("red", 345, 360), ("red", 0, 15), ("orange", 15, 45),
                         ("yellow", 45, 70), ("green", 70, 165), ("cyan", 165, 200),
                         ("blue", 200, 250), ("purple", 250, 290), ("pink", 290, 345)):
        if lo <= deg < hi:
            return name, deg
    return "red", deg


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb)


def hex_rgb(h):
    """'#rrggbb' -> (r, g, b). Callers validate the format first."""
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

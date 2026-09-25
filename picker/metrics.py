"""Per-theme metrics: light/dark, accent family, and the contrast audit that
drives the "low contrast" and "high contrast" badges."""

from . import colour as c, themes

_CHECKS = (("body text", "--text", 4.5), ("muted text", "--text-muted", 3.0))

# High contrast = WCAG AAA (7:1) for EVERY text role: body, muted, links
# and button labels. A first cut used 7:1 for body text but AA's 4.5:1 for
# the rest, and 38 of 110 themes qualified -- a label that fits a third of
# the list marks nothing. Each role must be measurable; no theme qualifies
# by omission.
HC_BAR = {"--text": 7.0, "--text-muted": 7.0, "--link-color": 7.0, "--button-text": 7.0}

_METRICS_CACHE = {}


def css_metrics(css):
    """{mode, lum, family, hue, warnings, high_contrast, ratios} for a sheet."""
    d = c.decls(css)
    page = c.surface(d.get("--main-bg-color"))
    surface = c.surface(d.get("--modal-bg-color")) or page
    lum = sum(map(c.lum, page)) / len(page) if page else None
    mode = "" if lum is None else ("light" if lum > 0.35 else "dark")

    accent = None
    m = c.TRIPLE.fullmatch(d.get("--accent-color", ""))
    if m:
        accent = tuple(float(x) for x in m.groups())
    else:
        accent = (c.stops(d.get("--accent-color")) or c.stops(d.get("--button-color")) or [None])[0]
    family, hue = c.family(accent) if accent else ("neutral", 0.0)

    warnings, ratio = [], {}
    if surface:
        for label, var, floor in _CHECKS:
            fg = (c.stops(d.get(var)) or [None])[0]
            if fg:
                worst = min(c.contrast(fg, s) for s in surface)
                ratio[var] = worst
                if worst < floor:
                    warnings.append(f"{label} {worst:.1f}:1 on panels (want {floor:g}:1)")
        link = (c.stops(d.get("--link-color")) or [None])[0]
        if link:
            ratio["--link-color"] = min(c.contrast(link, s) for s in surface)
    buttons = c.surface(d.get("--button-color"))
    if "--button-text" not in d:
        warnings.append("--button-text not defined")
    elif buttons:
        fg = (c.stops(d.get("--button-text")) or [None])[0]
        if fg:
            worst = min(c.contrast(fg, s) for s in buttons)
            ratio["--button-text"] = worst
            if worst < 3.0:
                warnings.append(f"button label {worst:.1f}:1 (want 3:1)")

    high = all(v in ratio and ratio[v] >= need for v, need in HC_BAR.items())

    return {"mode": mode, "lum": round(lum or 0.0, 3), "family": family,
            "hue": round(hue), "warnings": warnings, "high_contrast": high,
            "ratios": {k: round(v, 1) for k, v in ratio.items()}}


def theme_metrics(theme):
    """css_metrics() for one theme by name, cached until its stylesheet changes."""
    return themes.cached(_METRICS_CACHE, theme, lambda t: css_metrics(themes.theme_css(t)))

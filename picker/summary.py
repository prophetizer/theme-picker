"""Current-theme summary for the dashboard widgets (/api/current)."""

from . import colour as c, config, state, themes
from .metrics import theme_metrics


def current_summary():
    t = themes.current_theme()
    d = c.decls(themes.theme_css(t))
    swatch = []
    for var in themes.SWATCH_VARS:
        stops = c.surface(d.get(var))
        if stops:
            avg = [sum(s[i] for s in stops) / len(stops) for i in range(3)]
            swatch.append(c.to_hex(avg))
    m = theme_metrics(t)
    last = (state.read_history() or [{}])[-1]
    section = themes.section_of(t)
    return {"theme": t, "section": section, "mode": m["mode"] or "unknown",
            "gradient": themes.is_gradient(t), "low_contrast": bool(m["warnings"]), "swatch": swatch,
            # Same colours as objects: Glance's template helpers read fields out
            # of array items ({{ .String "hex" }}) but not bare strings.
            "colors": [{"hex": h} for h in swatch],
            "pinned": state.read_overrides(),
            "changed_at": last.get("at", "") if last.get("theme") == t else "",
            "changed_by": last.get("by", "") if last.get("theme") == t else "",
            "picker": config.picker_url()}

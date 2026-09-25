"""Prometheus exposition for /metrics: the live theme and the latest
scheduled coverage result. A scrape never runs a coverage check itself --
that would request every themed app once per scrape interval."""

from . import monitor, state, themes
from .metrics import theme_metrics
from .state import _parse_at


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics():
    out = []

    def metric(name, kind, help_, samples):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
            out.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")

    t = themes.current_theme()
    section = themes.section_of(t)
    metric("theme_picker_theme_info", "gauge", "The live theme.",
           [({"theme": t, "section": section, "mode": theme_metrics(t)["mode"] or "unknown"}, 1)])
    last_change = (state.read_history() or [{}])[-1]
    at = _parse_at(last_change.get("at")) if last_change.get("theme") == t else None
    if at:
        metric("theme_picker_theme_changed_timestamp_seconds", "gauge",
               "When the live theme was applied from the picker.", [({}, int(at.timestamp()))])
    metric("theme_picker_themes", "gauge", "Themes available, by section.",
           [({"section": "official"}, len(themes.official_themes())),
            ({"section": "community"}, len(themes.community_themes())),
            ({"section": "custom"}, len(themes.own_themes())),
            ({"section": "variants"}, len(themes.variant_themes()))])

    last = monitor.last()
    if last:
        r = last["result"]
        metric("theme_picker_coverage_app_ok", "gauge",
               "1 if the app was served its expected theme at the last scheduled check.",
               [({"app": x["app"]}, int(x["state"] == "ok")) for x in r["results"]])
        metric("theme_picker_coverage_apps_ok", "gauge", "Apps served their expected theme.", [({}, r["ok"])])
        metric("theme_picker_coverage_apps_total", "gauge", "Themed apps checked.", [({}, r["total"])])
        metric("theme_picker_coverage_last_check_timestamp_seconds", "gauge",
               "When the last scheduled coverage check finished.", [({}, int(last["at"]))])
    return "\n".join(out) + "\n"

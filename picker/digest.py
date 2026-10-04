"""A weekly summary on ntfy: what the week's themes were, what was added,
and anything that needs a look.

    ntfy:
      digest: "mon 09:00"        # day and local time; empty = no digest

Sent once a week at that time by the schedule's 30 s ticker; a digest missed
while the picker was down goes out when it comes back, once. Switching it on
sends nothing until the first time comes round. The last one
sent is remembered in state_dir/theme-digest.json.
"""

from datetime import datetime, time as dtime, timedelta

from . import config, monitor, ntfy, shots, state, themes

DIGEST_FILE = config.STATE_DIR / "theme-digest.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def slot(now, spec=None):
    """The most recent digest time at or before now, or None if off."""
    spec = config.SETTINGS["ntfy.digest"] if spec is None else spec
    if not spec:
        return None
    day, hhmm = spec.split()
    h, m = map(int, hhmm.split(":"))
    days_back = (now.weekday() - DAYS.index(day)) % 7
    at = datetime.combine(now.date() - timedelta(days=days_back), dtime(h, m))
    return at if at <= now else at - timedelta(days=7)


def _fmt(sec):
    sec = int(sec)
    return f"{sec // 86400}d {sec % 86400 // 3600}h" if sec >= 86400 else f"{sec // 3600}h {sec % 3600 // 60}m"


def compose(now):
    """(title, body) for the week ending now."""
    since = now - timedelta(days=7)
    hist = []
    for e in state.read_history():
        at = state._parse_at(e.get("at"))
        if at and isinstance(e.get("theme"), str):
            hist.append((e["theme"], at.astimezone().replace(tzinfo=None), e.get("by", "")))
    week = [h for h in hist if h[1] >= since]
    # Time on screen this week: each theme from its change to the next,
    # starting with whatever was live when the week began.
    before = [h for h in hist if h[1] < since]
    timeline = ([(before[-1][0], since)] if before else []) + [(t, at) for t, at, _ in week]
    secs = {}
    for i, (t, start) in enumerate(timeline):
        end = timeline[i + 1][1] if i + 1 < len(timeline) else now
        secs[t] = secs.get(t, 0) + max(0.0, (end - start).total_seconds())
    top = sorted(secs.items(), key=lambda x: -x[1])[:3]
    lines = [f"{len(week)} theme change{'s' if len(week) != 1 else ''} this week"
             + (f" ({sum(1 for h in week if h[2].startswith('schedule'))} by the schedule)." if week else ".")]
    if top:
        lines.append("Most on screen: " + ", ".join(f"{t} {_fmt(s)}" for t, s in top) + ".")
    added = []
    twins = set(themes.variant_themes())         # generated twins come with their theme
    for t, at in state.theme_dates().items():
        if t in twins:
            continue
        try:
            when = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
        if when >= since:
            added.append(t)
    if added:
        added.sort()
        lines.append(f"{len(added)} new theme{'s' if len(added) != 1 else ''}: "
                     + ", ".join(added[:6]) + (f" and {len(added) - 6} more" if len(added) > 6 else "") + ".")
    cov = (monitor.last() or {}).get("result")
    if cov:
        bad = [r["app"] for r in cov.get("results", []) if r.get("state") != "ok"]
        lines.append(f"Coverage: {cov.get('ok', 0)} of {cov.get('total', 0)} apps themed"
                     + (f"; not: {', '.join(bad[:6])}." if bad else "."))
    apps = shots.screenshot_apps()
    idx = shots.screenshot_index()
    allowed = themes.allowed_themes()
    missing = sum(1 for t in allowed if len(idx.get(t, [])) < len(apps)) if apps else 0
    if missing:
        lines.append(f"{missing} theme{'s' if missing != 1 else ''} still missing screenshots.")
    hidden = len(state.read_hidden())
    lines.append(f"{len(allowed)} themes in all" + (f", {hidden} hidden." if hidden else "."))
    return "Theme picker: your week", "\n".join(lines)


def tick(now=None, send=None):
    """Send this week's digest if it's due and not sent. Returns the body
    sent, else None."""
    now = now or datetime.now()
    due = slot(now)
    if due is None or not ntfy.enabled() and send is None:
        return None
    last = state.read_json(DIGEST_FILE, {}).get("sent", "")
    if not last:
        # Just switched on: start from the next slot. Sending the slot that
        # has already passed put a surprise digest on the phone the moment
        # the setting was added.
        state.write_json(DIGEST_FILE, {"sent": due.isoformat()})
        return None
    if last >= due.isoformat():
        return None
    title, body = compose(now)
    (send or ntfy.send)(title, body, tags="bar_chart", click=config.picker_url())
    state.write_json(DIGEST_FILE, {"sent": due.isoformat()})
    return body

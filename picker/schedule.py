"""Day/night schedule: one theme by day, another by night, switching at two
times of day.

A switch happens at each switch TIME, not continuously: the schedule
remembers the last switch it handled, so a theme picked by hand in between
stays until the next switch time, then the schedule resumes. A switch missed
while the picker was down is caught up at start. Scheduled switches are
recorded in the history as "schedule (day|night)" and send no ntfy notice --
they are expected. Turning the schedule on applies the current slot's theme
straight away.

Times are naive local wall-clock times (the container's TZ): "19:00" means
19:00 on the clock, including across a DST change.
"""

import random
import re
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta

from . import apply, config, state, themes

SCHEDULE_FILE = config.STATE_DIR / "theme-schedule.json"
TICK = 30
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])\Z")
DEFAULTS = {"enabled": False, "day": "", "night": "", "day_at": "07:00", "night_at": "19:00",
            "handled": "",
            # Theme of the day: a random pick once a day, at daily_at, from
            # the favourites or every theme -- never a hidden one or the live
            # one. Exclusive with day/night: enabling one turns the other off.
            "daily_enabled": False, "daily_at": "08:00", "daily_pool": "favourites", "daily_handled": ""}
POOLS = ("favourites", "all")
_LOCK = threading.Lock()


def read():
    data = state.read_json(SCHEDULE_FILE, {})
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        out.update({k: data[k] for k in DEFAULTS if k in data and isinstance(data[k], type(DEFAULTS[k]))})
    return out


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return dtime(h, m)


def switches(sch, now):
    """[(when, slot)] for yesterday, today and tomorrow, in time order."""
    out = []
    for days in (-1, 0, 1):
        d = (now + timedelta(days=days)).date()
        for slot in ("day", "night"):
            out.append((datetime.combine(d, _at(sch[f"{slot}_at"])), slot))
    return sorted(out)


def current_slot(sch, now):
    """(when, slot) of the most recent switch at or before now."""
    return [s for s in switches(sch, now) if s[0] <= now][-1]


def next_switch(sch, now):
    return [s for s in switches(sch, now) if s[0] > now][0]


def validate(data):
    """(schedule, None) or (None, error message) for a submitted schedule."""
    sch = dict(read())
    sch["enabled"] = bool(data.get("enabled"))
    for slot in ("day", "night"):
        t = str(data.get(slot, ""))
        at = str(data.get(f"{slot}_at", ""))
        if not _HHMM.match(at):
            return None, f"{slot.capitalize()} time must be HH:MM (24-hour)."
        if t not in themes.allowed_themes():
            if sch["enabled"] or t:
                return None, f"Pick a {slot} theme."
        sch[slot], sch[f"{slot}_at"] = t, at
    if sch["day_at"] == sch["night_at"]:
        return None, "Day and night need different switch times."
    if sch["enabled"]:
        sch["daily_enabled"] = False                 # one schedule at a time
    return sch, None


def save(data, now=None):
    """Validate, store, and when enabled apply the current slot now.
    Returns (ok, message)."""
    sch, err = validate(data)
    if err:
        return False, err
    with _LOCK:
        sch["handled"] = ""                       # a (re)enabled schedule applies now
        state.write_json(SCHEDULE_FILE, sch)
    if not sch["enabled"]:
        return True, "Schedule off."
    applied = tick(now)
    now = now or datetime.now()
    when, slot = next_switch(sch, now)
    msg = (f"Schedule on: {sch['day']} from {sch['day_at']}, {sch['night']} from {sch['night_at']}. "
           f"Next switch: {sch[slot]} at {when.strftime('%H:%M')}.")
    if applied and applied[2]:
        msg += f" Applied {applied[1]} ({applied[0]}) now."
    elif applied:
        msg += f" Could not apply {applied[1]}: {applied[3]}"
    return True, msg


def daily_pool(sch):
    """The themes the theme of the day picks from: favourites (or every
    theme), minus hidden ones and the live one."""
    allowed = set(themes.allowed_themes())
    hidden = set(state.read_hidden())
    base = state.read_favourites() if sch["daily_pool"] == "favourites" else sorted(allowed)
    live = themes.current_theme()
    return [t for t in base if t in allowed and t not in hidden and t != live]


def daily_due(sch, now):
    """The most recent daily pick time at or before now."""
    today = datetime.combine(now.date(), _at(sch["daily_at"]))
    return today if today <= now else today - timedelta(days=1)


def save_daily(data, now=None, rng=random):
    """Validate and store the theme-of-the-day settings; enabling it turns
    day/night off and picks a theme now. Returns (ok, message)."""
    at, pool, on = str(data.get("at", "")), str(data.get("pool", "")), bool(data.get("enabled"))
    if not _HHMM.match(at):
        return False, "The time must be HH:MM (24-hour)."
    if pool not in POOLS:
        return False, "Pick from favourites or all themes."
    with _LOCK:
        sch = read()
        sch.update(daily_enabled=on, daily_at=at, daily_pool=pool, daily_handled="")
        if on:
            sch["enabled"] = False                   # one schedule at a time
        state.write_json(SCHEDULE_FILE, sch)
    if not on:
        return True, "Theme of the day off."
    if not daily_pool(sch):
        return True, ("Theme of the day on, but there is nothing to pick from yet: "
                      + ("star some favourites." if pool == "favourites" else "every theme is hidden."))
    picked = tick_daily(now, rng=rng)
    msg = f"Theme of the day on: a new pick from {'your favourites' if pool == 'favourites' else 'all themes'} every day at {at}."
    if picked and picked[1]:
        msg += f" Today's: {picked[0]}."
    return True, msg


def tick_daily(now=None, apply_fn=None, rng=random):
    """Pick and apply today's theme if today's pick has not happened.
    Returns (theme, ok, message) when it acted, else None."""
    apply_fn = apply_fn or apply.apply_theme
    now = now or datetime.now()
    with _LOCK:
        sch = read()
        if not sch["daily_enabled"]:
            return None
        when = daily_due(sch, now)
        try:
            handled = datetime.fromisoformat(sch["daily_handled"]) if sch["daily_handled"] else None
        except ValueError:
            handled = None
        if handled and handled >= when:
            return None
        pool = daily_pool(sch)
        result = None
        if pool:
            theme = rng.choice(pool)
            ok, message, status = apply_fn(theme, "schedule (theme of the day)")
            result = (theme, ok, message)
            if not ok:
                print(f"schedule: {message}", file=sys.stderr, flush=True)
                if status != 400:
                    return result                    # retry next tick
        sch["daily_handled"] = when.isoformat()
        state.write_json(SCHEDULE_FILE, sch)
        return result


def tick(now=None, apply_fn=None):
    """Apply the current slot's theme if its switch has not been handled.
    Returns (slot, theme, ok, message) when it acted, else None."""
    apply_fn = apply_fn or apply.apply_theme
    now = now or datetime.now()
    with _LOCK:
        sch = read()
        if not sch["enabled"] or not sch["day"] or not sch["night"]:
            return None
        when, slot = current_slot(sch, now)
        try:
            handled = datetime.fromisoformat(sch["handled"]) if sch["handled"] else None
        except ValueError:
            handled = None
        if handled and handled >= when:
            return None
        theme, result = sch[slot], None
        if theme != themes.current_theme():
            ok, message, status = apply_fn(theme, f"schedule ({slot})")
            result = (slot, theme, ok, message)
            if not ok:
                print(f"schedule: {message}", file=sys.stderr, flush=True)
                if status != 400:                    # set-theme.sh failed: retry next tick
                    return result
                # 400 = no longer a known theme (deleted?): retrying cannot
                # help, so skip this switch instead of logging every 30 s.
        sch["handled"] = when.isoformat()
        state.write_json(SCHEDULE_FILE, sch)
        return result


def status(now=None):
    """The schedule plus where it is now, for the page and /api/schedule."""
    sch = read()
    out = {k: sch[k] for k in ("enabled", "day", "night", "day_at", "night_at",
                               "daily_enabled", "daily_at", "daily_pool")}
    if sch["daily_enabled"]:
        now_ = now or datetime.now()
        out["daily_next"] = (daily_due(sch, now_) + timedelta(days=1)).strftime("%a %H:%M")
        out["daily_pool_size"] = len(daily_pool(sch))
    if sch["enabled"] and sch["day"] and sch["night"]:
        now = now or datetime.now()
        _, slot = current_slot(sch, now)
        when, nslot = next_switch(sch, now)
        out.update(slot=slot, next_at=when.strftime("%H:%M"), next_theme=sch[nslot], next_slot=nslot)
    return out


def _loop():
    while True:
        try:
            tick()
            tick_daily()
        except Exception as e:                   # never let the scheduler die
            print(f"schedule: {e}", file=sys.stderr, flush=True)
        time.sleep(TICK)


def start():
    threading.Thread(target=_loop, name="theme-schedule", daemon=True).start()

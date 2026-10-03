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

Sun mode: day starts at sunrise and night at sunset, each moved by an offset
in minutes, computed here from a latitude and longitude (sun_times(); no
network). Coordinates are stored rounded to 2 decimals (about 1 km). Where
the sun doesn't rise or set that day (polar summer or winter), the clock
times stand in.

Rotation: a random theme every N hours from the favourites or all themes,
like the theme of the day. The three schedules are exclusive: turning one on
turns the others off.
"""

import math
import random
import re
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone

from . import apply, config, state, themes

SCHEDULE_FILE = config.STATE_DIR / "theme-schedule.json"
TICK = 30
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])\Z")
DEFAULTS = {"enabled": False, "day": "", "night": "", "day_at": "07:00", "night_at": "19:00",
            "handled": "",
            # Theme of the day: a random pick once a day, at daily_at, from
            # the favourites or every theme -- never a hidden one or the live
            # one. Exclusive with day/night: enabling one turns the other off.
            "daily_enabled": False, "daily_at": "08:00", "daily_pool": "favourites", "daily_handled": "",
            # Day/night at sunrise and sunset instead of day_at/night_at.
            "sun": False, "lat": 0.0, "lon": 0.0, "day_offset": 0, "night_offset": 0,
            # Rotation: a pick every rotate_every hours -- random from the pool,
            # or the next theme of rotate_list in order (rotate_mode "list").
            "rotate_enabled": False, "rotate_every": 6, "rotate_pool": "favourites", "rotate_handled": "",
            "rotate_mode": "random", "rotate_list": [], "rotate_pos": -1}
MODES = ("random", "list")
POOLS = ("favourites", "all")
_LOCK = threading.Lock()


def read():
    data = state.read_json(SCHEDULE_FILE, {})
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        for k in DEFAULTS:
            v = data.get(k)
            if isinstance(DEFAULTS[k], float) and isinstance(v, int) and not isinstance(v, bool):
                v = float(v)
            if isinstance(v, list):
                v = [t for t in v if isinstance(t, str) and config.SAFE_NAME.match(t)][:200]
            if v is not None and type(v) is type(DEFAULTS[k]):
                out[k] = v
    return out


# --- sunrise and sunset -----------------------------------------------------------
def sun_times(day, lat, lon):
    """(sunrise, sunset) as UTC datetimes for a date at a place, by the
    standard sunrise equation (to within a minute or two). "up" or "down"
    instead when the sun stays above or below the horizon all day."""
    jd0 = day.toordinal() + 1721424.5                 # Julian date at 00:00 UTC
    n = round(jd0 + 0.5 - 2451545.0 + 0.0008)
    j_star = n - lon / 360
    m = (357.5291 + 0.98560028 * j_star) % 360
    mr = math.radians(m)
    c = 1.9148 * math.sin(mr) + 0.0200 * math.sin(2 * mr) + 0.0003 * math.sin(3 * mr)
    lam = math.radians((m + c + 180 + 102.9372) % 360)
    transit = 2451545.0 + j_star + 0.0053 * math.sin(mr) - 0.0069 * math.sin(2 * lam)
    sin_d = math.sin(lam) * math.sin(math.radians(23.4397))
    cos_d = math.cos(math.asin(sin_d))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * sin_d) / (math.cos(phi) * cos_d)
    if cos_w < -1:
        return "up"
    if cos_w > 1:
        return "down"
    w = math.degrees(math.acos(cos_w)) / 360
    at = lambda j: datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=j - 2451545.0)
    return at(transit - w), at(transit + w)


def _local(utc):
    """A UTC datetime as naive local wall-clock time (the container's TZ)."""
    return utc.astimezone().replace(tzinfo=None, second=0, microsecond=0)


def slot_times(sch, day):
    """{slot: datetime} of the two switches on a date: sunrise and sunset in
    sun mode (with the offsets), else the clock times."""
    clock = {slot: datetime.combine(day, _at(sch[f"{slot}_at"])) for slot in ("day", "night")}
    if not sch.get("sun"):
        return clock
    st = sun_times(day, sch["lat"], sch["lon"])
    if isinstance(st, str):
        return clock
    return {"day": _local(st[0]) + timedelta(minutes=sch["day_offset"]),
            "night": _local(st[1]) + timedelta(minutes=sch["night_offset"])}


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return dtime(h, m)


def switches(sch, now):
    """[(when, slot)] for yesterday, today and tomorrow, in time order."""
    out = []
    for days in (-1, 0, 1):
        d = (now + timedelta(days=days)).date()
        out += [(when, slot) for slot, when in slot_times(sch, d).items()]
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
    sch["sun"] = bool(data.get("sun"))
    if sch["sun"] or any(data.get(k) not in (None, "") for k in ("lat", "lon")):
        try:
            lat, lon = float(data.get("lat")), float(data.get("lon"))
        except (TypeError, ValueError):
            return None, "Latitude and longitude must be numbers, e.g. 51.51 and -0.13."
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return None, "Latitude must be -90 to 90 and longitude -180 to 180."
        sch["lat"], sch["lon"] = round(lat, 2), round(lon, 2)   # about 1 km: enough for the sun
    for k in ("day_offset", "night_offset"):
        try:
            v = int(data.get(k) or 0)
        except (TypeError, ValueError):
            return None, "Offsets are whole minutes."
        if not -180 <= v <= 180:
            return None, "Offsets must be within 3 hours (-180 to 180 minutes)."
        sch[k] = v
    if sch["enabled"]:
        sch["daily_enabled"] = sch["rotate_enabled"] = False     # one schedule at a time
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
    if sch["sun"]:
        times = slot_times(sch, now.date())
        msg = (f"Schedule on: {sch['day']} from sunrise ({times['day']:%H:%M} today), "
               f"{sch['night']} from sunset ({times['night']:%H:%M}). ")
    else:
        msg = f"Schedule on: {sch['day']} from {sch['day_at']}, {sch['night']} from {sch['night_at']}. "
    msg += f"Next switch: {sch[slot]} at {when.strftime('%H:%M')}."
    if applied and applied[2]:
        msg += f" Applied {applied[1]} ({applied[0]}) now."
    elif applied:
        msg += f" Could not apply {applied[1]}: {applied[3]}"
    return True, msg


def pool_themes(pool):
    """The themes a random pick chooses from: favourites (or every theme),
    minus hidden ones and the live one. (state.pick() then leaves out the
    disliked ones and favours the liked.)"""
    allowed = set(themes.allowed_themes())
    hidden = set(state.read_hidden())
    base = state.read_favourites() if pool == "favourites" else sorted(allowed)
    live = themes.current_theme()
    return [t for t in base if t in allowed and t not in hidden and t != live]


def daily_pool(sch):
    return pool_themes(sch["daily_pool"])


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
            sch["enabled"] = sch["rotate_enabled"] = False      # one schedule at a time
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
        theme = state.pick(daily_pool(sch), rng)
        result = None
        if theme:
            ok, message, status = apply_fn(theme, "schedule (theme of the day)")
            result = (theme, ok, message)
            if not ok:
                print(f"schedule: {message}", file=sys.stderr, flush=True)
                if status != 400:
                    return result                    # retry next tick
        sch["daily_handled"] = when.isoformat()
        state.write_json(SCHEDULE_FILE, sch)
        return result


def rotate_list(sch):
    """The playlist's themes that can still be applied (known, not hidden)."""
    allowed, hidden = set(themes.allowed_themes()), set(state.read_hidden())
    return [t for t in sch["rotate_list"] if t in allowed and t not in hidden]


def save_rotate(data, now=None, rng=random):
    """Validate and store the rotation; enabling it turns the other schedules
    off and picks a theme now. Returns (ok, message)."""
    pool, on = str(data.get("pool", "")), bool(data.get("enabled"))
    mode = str(data.get("mode") or "random")
    if mode not in MODES:
        return False, "Order is random or my list."
    raw = data.get("list") if isinstance(data.get("list"), list) else []
    allowed = set(themes.allowed_themes())
    playlist = []
    for t in raw:
        if isinstance(t, str) and t in allowed and t not in playlist:
            playlist.append(t)
    if len(raw) > 200:
        return False, "A playlist holds up to 200 themes."
    if mode == "list" and len(playlist) < 2:
        return False, "Add at least two themes to the list."
    try:
        every = int(data.get("every"))
    except (TypeError, ValueError):
        return False, "Every how many hours? A whole number, 1 to 168."
    if not 1 <= every <= 168:
        return False, "Every 1 to 168 hours (a week)."
    if pool not in POOLS:
        return False, "Pick from favourites or all themes."
    with _LOCK:
        sch = read()
        if playlist != sch["rotate_list"]:
            sch["rotate_pos"] = -1                    # a new list starts from its top
        sch.update(rotate_enabled=on, rotate_every=every, rotate_pool=pool, rotate_handled="",
                   rotate_mode=mode, rotate_list=playlist)
        if on:
            sch["enabled"] = sch["daily_enabled"] = False       # one schedule at a time
        state.write_json(SCHEDULE_FILE, sch)
    if not on:
        return True, "Rotation off."
    src = ("your list" if mode == "list" else
           "your favourites" if pool == "favourites" else "all themes")
    if mode == "random" and not pool_themes(pool):
        return True, ("Rotation on, but there is nothing to pick from yet: "
                      + ("star some favourites." if pool == "favourites" else "every theme is hidden."))
    picked = tick_rotate(now, rng=rng)
    msg = (f"Rotation on: {'the next' if mode == 'list' else 'a new'} theme from {src} "
           f"every {every} hour{'s' if every != 1 else ''}.")
    if picked and picked[1]:
        msg += f" Now: {picked[0]}."
    return True, msg


def rotate_due(sch, now):
    """True when the rotation should pick: never picked, or rotate_every
    hours since the last pick."""
    try:
        last = datetime.fromisoformat(sch["rotate_handled"]) if sch["rotate_handled"] else None
    except ValueError:
        last = None
    return last is None or now >= last + timedelta(hours=sch["rotate_every"])


def tick_rotate(now=None, apply_fn=None, rng=random):
    """Pick and apply the next theme if the rotation is due.
    Returns (theme, ok, message) when it acted, else None."""
    apply_fn = apply_fn or apply.apply_theme
    now = now or datetime.now()
    with _LOCK:
        sch = read()
        if not sch["rotate_enabled"] or not rotate_due(sch, now):
            return None
        pos = sch["rotate_pos"]
        if sch["rotate_mode"] == "list":
            playlist = rotate_list(sch)
            if playlist:
                # The theme after the last one applied; by name, so editing
                # the list doesn't jump around.
                last = sch["rotate_list"][pos] if 0 <= pos < len(sch["rotate_list"]) else None
                nxt = (playlist.index(last) + 1) % len(playlist) if last in playlist else 0
                theme, pos = playlist[nxt], sch["rotate_list"].index(playlist[nxt])
            else:
                theme = None
        else:
            theme = state.pick(pool_themes(sch["rotate_pool"]), rng)
        result = None
        if theme:
            ok, message, status = apply_fn(theme, "schedule (rotation)")
            result = (theme, ok, message)
            if not ok:
                print(f"schedule: {message}", file=sys.stderr, flush=True)
                if status != 400:
                    return result                    # retry next tick
        sch["rotate_handled"] = now.replace(second=0, microsecond=0).isoformat()
        sch["rotate_pos"] = pos
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
                               "daily_enabled", "daily_at", "daily_pool",
                               "sun", "lat", "lon", "day_offset", "night_offset",
                               "rotate_enabled", "rotate_every", "rotate_pool",
                               "rotate_mode", "rotate_list")}
    now_ = now or datetime.now()
    if sch["sun"]:
        st = sun_times(now_.date(), sch["lat"], sch["lon"])
        if isinstance(st, str):
            out["sun_today"] = f"the sun stays {st} today; the clock times apply"
        else:
            out["sun_today"] = f"sunrise {_local(st[0]):%H:%M}, sunset {_local(st[1]):%H:%M} today"
    if sch["rotate_enabled"]:
        out["rotate_pool_size"] = (len(rotate_list(sch)) if sch["rotate_mode"] == "list"
                                   else len(pool_themes(sch["rotate_pool"])))
        try:
            last = datetime.fromisoformat(sch["rotate_handled"]) if sch["rotate_handled"] else None
        except ValueError:
            last = None
        if last:
            out["rotate_next"] = (last + timedelta(hours=sch["rotate_every"])).strftime("%a %H:%M")
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
            tick_rotate()
        except Exception as e:                   # never let the scheduler die
            print(f"schedule: {e}", file=sys.stderr, flush=True)
        time.sleep(TICK)


def start():
    threading.Thread(target=_loop, name="theme-schedule", daemon=True).start()

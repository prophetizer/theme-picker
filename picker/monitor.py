"""Scheduled coverage check: alert on ntfy when an app stops getting its
theme, and keep the latest result for /metrics.

The in-page coverage check only runs when someone opens the picker, and the
failures it exists to catch -- a router that lost its middleware, a Traefik
that stalled on a reload -- are silent: the app still works, just unthemed.

An app must fail two checks in a row before it alerts, and each incident
alerts once, with a second message when it recovers. A check during which
the live theme changed is discarded, not judged: the nightly screenshot
capture cycles through every theme, and an app caught mid-switch is not
broken.
"""

import sys
import threading
import time

from . import config, coverage, ntfy, shots, state, themes

INTERVAL = config.SETTINGS["coverage.interval"]   # seconds; 0 = off
FIRST_DELAY = 60
FAILS_TO_ALERT = 2

_LOCK = threading.Lock()
_LAST = {}                       # {"result": check_coverage() output, "at": epoch seconds}
_STREAK = {}                     # app -> consecutive failed checks
_ALERTED = set()                 # apps currently reported as failing


def last():
    with _LOCK:
        return dict(_LAST)


def run_once(check=None):
    """One scheduled check. Returns (alert, recovered) app lists, or None
    when the result was discarded because the theme changed mid-check."""
    check = check or coverage.check_coverage
    before = themes.current_theme()
    result = check()
    if themes.current_theme() != before or result.get("theme") != before:
        return None
    with _LOCK:
        _LAST.update(result=result, at=time.time())
        failing = {r["app"]: r for r in result["results"] if r["state"] != "ok"}
        for app in list(_STREAK):
            if app not in failing:
                del _STREAK[app]
        for app in failing:
            _STREAK[app] = _STREAK.get(app, 0) + 1
        alert = sorted(a for a in failing if _STREAK[a] >= FAILS_TO_ALERT and a not in _ALERTED)
        recovered = sorted(a for a in _ALERTED if a not in failing)
        _ALERTED.update(alert)
        _ALERTED.difference_update(recovered)
    if alert:
        lines = [f"{r['app']}: {r['state']}" + (f" ({r['detail']})" if r["detail"] else "")
                 + f", expected {r['expected']}" for r in (failing[a] for a in alert)]
        ntfy.send(f"Theme coverage: {len(alert)} app{'s' if len(alert) != 1 else ''} not themed",
                  "\n".join(lines) + f"\n{result['ok']} of {result['total']} apps OK.",
                  tags="warning", priority="high")
    if recovered:
        ntfy.send("Theme coverage recovered",
                  f"Themed again: {', '.join(recovered)}.\n{result['ok']} of {result['total']} apps OK.",
                  tags="white_check_mark")
    return alert, recovered


# --- a capture that stopped --------------------------------------------------
# A capture that is killed (OOM, reboot, a hung browser) never reaches its own
# end-of-run alert, and leaves the live theme wherever it stopped. Its status
# file then sits at "running" with an old timestamp, which capture_status()
# reports as stalled. One alert per run: the run's start time is recorded in
# the state dir, so a picker restart doesn't repeat it, and a run that picks up
# again gets one "resumed" message. A stalled status over a day old is history,
# not news, and is left alone.
CAPTURE_ALERT_FILE = config.STATE_DIR / "capture-alert.json"
STALL_NEWS_HOURS = 24


def check_capture(now=None):
    """Returns "stalled", "resumed" or None (nothing sent)."""
    from datetime import datetime
    now = now or datetime.now().astimezone()
    st = shots.capture_status(now)
    run = st.get("started")
    if not run:
        return None
    sent = state.read_json(CAPTURE_ALERT_FILE, {})
    alerted = isinstance(sent, dict) and sent.get("started") == run
    if st.get("stalled") and not alerted:
        try:
            updated = datetime.strptime(st.get("updated") or "", "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
        if (now - updated).total_seconds() > STALL_NEWS_HOURS * 3600:
            return None
        state.write_json(CAPTURE_ALERT_FILE, {"started": run})
        ntfy.send("Screenshot capture stopped",
                  f"No progress since {updated:%H:%M}: theme {st.get('index') or 0} of {st.get('themes') or 0}"
                  + (f" ({st['theme']})" if st.get("theme") else "")
                  + f", {st.get('done') or 0} of {st.get('shots') or 0} shots. The live theme may still be the "
                  f"capture's; it meant to restore {st.get('restore') or 'the one before'}.",
                  tags="warning", priority="high")
        return "stalled"
    if alerted and st.get("running"):
        state.write_json(CAPTURE_ALERT_FILE, {"started": run, "resumed": True})
        if not sent.get("resumed"):
            ntfy.send("Screenshot capture resumed",
                      f"Progressing again: theme {st.get('index') or 0} of {st.get('themes') or 0}.",
                      tags="white_check_mark")
            return "resumed"
    return None


def _loop():
    time.sleep(FIRST_DELAY)
    while True:
        for job in (run_once, check_capture):
            try:
                job()
            except Exception as e:             # never let the monitor thread die
                print(f"coverage monitor: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


def start():
    if INTERVAL > 0:
        threading.Thread(target=_loop, name="coverage-monitor", daemon=True).start()

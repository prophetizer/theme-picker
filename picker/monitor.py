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

from . import config, coverage, ntfy, themes

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


def _loop():
    time.sleep(FIRST_DELAY)
    while True:
        try:
            run_once()
        except Exception as e:                 # never let the monitor thread die
            print(f"coverage monitor: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


def start():
    if INTERVAL > 0:
        threading.Thread(target=_loop, name="coverage-monitor", daemon=True).start()

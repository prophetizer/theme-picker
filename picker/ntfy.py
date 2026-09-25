"""ntfy notifications for theme changes made in the picker, debounced."""

import sys
import threading
import urllib.request
from pathlib import Path

from . import config

# ntfy.* in picker.yml, or NTFY_* in the environment (the homelab sets them
# in compose/primary/theme-picker.yml). Unset means no notifications.
NTFY_URL = config.SETTINGS["ntfy.url"]
NTFY_TOPIC = config.SETTINGS["ntfy.topic"]
NTFY_TOKEN_FILE = config.SETTINGS["ntfy.token_file"]
# Clicking through themes one after another would otherwise put a dozen
# notifications on the phone in a minute. The notification waits until the
# theme has been left alone this long, then reports only the one that stuck.
NTFY_SETTLE_SECONDS = 20

_NOTIFY = {"timer": None, "tried": 0}
_NOTIFY_LOCK = threading.Lock()


def _ntfy_token():
    try:
        return Path(NTFY_TOKEN_FILE).read_text().strip() if NTFY_TOKEN_FILE else ""
    except OSError:
        return ""


def schedule_notify(theme, by, url):
    if not enabled():
        return
    with _NOTIFY_LOCK:
        if _NOTIFY["timer"]:
            _NOTIFY["timer"].cancel()
        _NOTIFY["tried"] += 1
        t = threading.Timer(NTFY_SETTLE_SECONDS, _send_notify,
                            args=(theme, by, url, _NOTIFY["tried"]))
        t.daemon = True
        _NOTIFY["timer"] = t
        t.start()


def _send_notify(theme, by, url, tried):
    with _NOTIFY_LOCK:
        _NOTIFY["timer"], _NOTIFY["tried"] = None, 0
    body = f"Now using {theme}"
    if tried > 1:
        body += f", after trying {tried} themes"
    body += f".\nChanged by {by}."
    send("Homelab theme changed", body, tags="art", click=url)


def enabled():
    return bool(NTFY_URL and NTFY_TOPIC and _ntfy_token())


def send(title, body, tags="", priority="", click=""):
    """Post one message to the topic. Failures are logged, never raised;
    without ntfy configured this does nothing."""
    if not enabled():
        return
    headers = {"Authorization": f"Bearer {_ntfy_token()}", "Title": title}
    if tags:
        headers["Tags"] = tags
    if priority:
        headers["Priority"] = priority
    if click:
        headers["Click"] = click
    req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}", data=body.encode("utf-8"),
                                 method="POST", headers=headers)
    try:
        urllib.request.urlopen(req, timeout=8).read()
    except Exception as e:
        print(f"ntfy notification failed: {e}", file=sys.stderr, flush=True)

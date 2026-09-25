"""Coverage check: is every themed app actually being served its theme?"""

import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config, state, themes

_LINK = re.compile(r"/css/base/([\w-]+)/([\w.-]+?)\.css")

# /api/coverage needs no login on the LAN and each run requests every themed
# app, so concurrent and repeated calls share one result for CACHE_SECONDS.
# The key is the live theme plus the pins, so a check right after a change
# always runs fresh.
CACHE_SECONDS = 30
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def cached_coverage():
    key = (themes.current_theme(), tuple(sorted(state.read_overrides().items())))
    with _CACHE_LOCK:
        hit = _CACHE.get("entry")
        if hit and hit[0] == key and time.monotonic() - hit[1] < CACHE_SECONDS:
            return hit[2]
        result = check_coverage()
        _CACHE["entry"] = (key, time.monotonic(), result)
        return result


def check_coverage():
    """Ask every themed app for its page and read which theme it was served.

    Requests go out through the public hostname exactly as a browser's would,
    with Accept: text/html -- the traefik-themepark plugin only injects its
    stylesheet link into HTML responses. Error pages count: Plex answers 401
    and still carries the link."""
    apps, overrides, main = state.load_apps(), state.read_overrides(), themes.current_theme()

    def fetch(url):
        req = urllib.request.Request(url, headers={"Accept": "text/html",
                                                   "User-Agent": "theme-picker coverage check"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, r.read(600_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            return err.code, err.read(600_000).decode("utf-8", "replace")

    def one(a, retry=True):
        expected = overrides.get(a["name"], main)
        url = f"https://{a['host']}.{config.DOMAIN}/"
        out = {"app": a["name"], "url": url, "expected": expected,
               "pinned": a["name"] in overrides}
        try:
            status, body = fetch(url)
        except Exception as err:
            return {**out, "state": "error", "detail": str(err)[:90]}
        m = _LINK.search(body)
        if not m:
            return {**out, "state": "missing", "detail": f"HTTP {status}, no theme stylesheet in page"}
        if m.group(2) != expected:
            if retry:                                  # Traefik may still be reloading
                time.sleep(2.5)
                return one(a, retry=False)
            return {**out, "state": "wrong", "detail": f"serving {m.group(2)}"}
        return {**out, "state": "ok", "detail": ""}

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(one, apps))
    return {"theme": main, "checked": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ok": sum(r["state"] == "ok" for r in results), "total": len(results),
            "results": results}

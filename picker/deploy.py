"""Deploy custom themes into a self-hosted theme.park -- the portable path.

Off unless custom_themes.theme_park_www is set: the homelab deploys with
theme-switcher's sync-themes.sh and theme-worker.sh instead, which need a
host shell, git and docker exec. With it set, this module does the same job
from inside the picker, needing only theme.park's served www/ directory
mounted read-write:

  1. copy each custom theme (config.CUSTOM_DIR/<name>.css) to
     www/css/theme-options/<name>.css -- only if missing or changed
  2. remove themes this module deployed earlier whose source is gone, with
     their per-app files (themes.py never deletes those)
  3. run theme.park's OWN themes.py, which rebuilds themes.json and every
     css/base/<app>/<theme>.css wrapper: the same output as theme.park's
     container init, not a reimplementation of it
  4. check each deployed theme now has its per-app file

A custom theme may not take a name theme.park itself ships: its container
init copies its own files over www/ on every start, so the two would fight.
What counts as "ours" is the manifest this module writes, never a guess.

The source CSS is copied as it is. It comes from the operator's own
directory, or from the editor, which builds CSS only from validated
primitives; nothing a web request sends reaches it any other way.
"""

import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import config, state

MANIFEST_FILE = config.THEME_DIR / "custom-deployed.json"
CHECK_EVERY = 60            # seconds between checks for changed or missing themes
MAX_THEME_BYTES = 64 * 1024
# Stricter than SAFE_NAME: theme.park lowercases names for its per-app files
# and splits themes.json keys at the first ".", so "My.Theme" would half-deploy.
DEPLOYABLE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_LOCK = threading.Lock()
LAST = {}                   # the last deploy's result, for /api/custom-themes


def enabled():
    return config.THEME_PARK_WWW is not None


def _www():
    return Path(config.THEME_PARK_WWW)


def _read_source(path):
    """A custom theme's bytes, or None unless it is a small regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(MAX_THEME_BYTES + 1)
    return data if len(data) <= MAX_THEME_BYTES else None


def _write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _themes_py_env():
    """theme.park's themes.py writes absolute URLs into themes.json from
    TP_DOMAIN/TP_SCHEME. Taken from theme_park_url so they match what the
    theme.park container itself writes; without it themes.py falls back to
    its CNAME file (the public theme-park.dev)."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TZ")}
    url = urlsplit(config.base_url())
    if url.netloc:
        env["TP_DOMAIN"] = url.netloc + url.path.rstrip("/")
        env["TP_SCHEME"] = url.scheme
    return env


def _run_themes_py(www):
    script = www / "themes.py"
    if not script.is_file():
        raise RuntimeError(f"no themes.py in {www} -- is that theme.park's www directory?")
    r = subprocess.run([sys.executable, str(script)], cwd=www, env=_themes_py_env(),
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"themes.py failed: {tail[0][:200]}")


def deploy(force=False):
    """Bring theme.park in line with CUSTOM_DIR. Returns a result dict and
    keeps it in LAST. Cheap when nothing changed: it compares file contents
    and only runs themes.py when something did (or force=True)."""
    from . import themes                              # themes imports config only
    with _LOCK:
        result = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ok": False, "deployed": [],
                  "removed": [], "refused": [], "unchanged": 0, "error": ""}
        try:
            www = _www()
            opts, community = www / "css" / "theme-options", www / "css" / "community-theme-options"
            if not opts.is_dir():
                raise RuntimeError(f"{opts} not found -- is theme_park_www theme.park's www directory?")
            ours = set(n for n in state.read_json(MANIFEST_FILE, []) if isinstance(n, str)
                       and config.SAFE_NAME.match(n))
            shipped = ({p.stem for p in opts.glob("*.css")} | {p.stem for p in community.glob("*.css")}) - ours
            wanted, changed = [], False
            for name in themes.custom_themes():
                data = _read_source(themes.CUSTOM_THEMES_DIR / f"{name}.css")
                if data is None or not DEPLOYABLE.match(name):
                    result["refused"].append(name)
                    continue
                dst = opts / f"{name}.css"
                if name in shipped:
                    # theme.park's own file of that name -- unless it is this
                    # very theme, copied in by hand before the picker managed
                    # it: identical bytes, so adopt it rather than refuse.
                    try:
                        adopt = not dst.is_symlink() and dst.read_bytes() == data
                    except OSError:
                        adopt = False
                    if not adopt:
                        result["refused"].append(name)
                        continue
                wanted.append(name)
                try:
                    same = dst.read_bytes() == data and not dst.is_symlink()
                except OSError:
                    same = False
                if same:
                    result["unchanged"] += 1
                else:
                    _write(dst, data)
                    result["deployed"].append(name)
                    changed = True
            for gone in sorted(ours - set(wanted) - shipped):
                (opts / f"{gone}.css").unlink(missing_ok=True)
                for wrapper in (www / "css" / "base").glob(f"*/{gone}.css"):
                    wrapper.unlink(missing_ok=True)
                result["removed"].append(gone)
                changed = True
            state.write_json(MANIFEST_FILE, sorted(wanted))
            # A theme.park restart (or a new www volume) can drop per-app
            # files for themes whose source never changed: check for them too.
            # Deprecated apps get no per-app files from themes.py; don't wait for them.
            bases = [d for d in (www / "css" / "base").iterdir()
                     if (d / f"{d.name}-base.css").is_file() and not (d / ".deprecated").exists()]
            missing = lambda: [n for n in wanted if any(not (b / f"{n}.css").is_file() for b in bases)]
            if changed or force or missing():
                _run_themes_py(www)
                missing = missing()
                if missing:
                    raise RuntimeError(f"themes.py ran but did not generate: {', '.join(missing[:5])}")
            result["ok"] = True
        except Exception as e:                        # reported, never fatal to the picker
            result["error"] = str(e)[:300]
        LAST.clear()
        LAST.update(result)
        if result["deployed"] or result["removed"] or result["error"] or result["refused"]:
            print(f"custom themes: deployed {len(result['deployed'])}, removed {len(result['removed'])}, "
                  f"refused {result['refused'] or 'none'}"
                  + (f", ERROR {result['error']}" if result["error"] else ""), file=sys.stderr, flush=True)
        return dict(result)


def _loop():
    while True:
        deploy()
        time.sleep(CHECK_EVERY)


def start():
    if enabled():
        threading.Thread(target=_loop, name="custom-theme-deploy", daemon=True).start()

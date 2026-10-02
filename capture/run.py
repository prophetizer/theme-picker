"""The capture image's entry point: run capture_theme_screenshots.py on a
schedule, as a nightly cron job would.

    CAPTURE_AT=04:30         daily, at this local time (the container's TZ)
    CAPTURE_AT=              once, then exit
    CAPTURE_ON_START=1       also once at start when nothing has been shot yet

Each run is a fresh process, so a browser that leaks or hangs is gone by the
next one; a run that fails is logged and the schedule carries on. The capture
CHANGES THE LIVE THEME while it runs (every theme in turn) and restores it at
the end -- see capture_theme_screenshots.py.
"""

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Next to this file in the image (/app); one level up in a checkout.
SCRIPT = next(p for p in (HERE / "capture_theme_screenshots.py", HERE.parent / "capture_theme_screenshots.py")
              if p.exists())
_AT = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\Z")


def run():
    print(f"capture: starting a run at {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    code = subprocess.run([sys.executable, str(SCRIPT)]).returncode
    print(f"capture: run finished (exit {code})", flush=True)
    return code


def next_at(now, hh, mm):
    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def nothing_shot():
    from picker import config
    shots = Path(os.environ.get("OUT_DIR", config.THEME_DIR / "screenshots")) / "per-app"
    return not any(shots.glob("*.png"))


def main():
    at = os.environ.get("CAPTURE_AT", "04:30").strip()
    if not at:
        sys.exit(run())
    m = _AT.match(at)
    if not m:
        sys.exit(f"capture: CAPTURE_AT must be HH:MM (24-hour) or empty, got {at!r}")
    if os.environ.get("CAPTURE_ON_START", "1") == "1" and nothing_shot():
        run()
    while True:
        when = next_at(datetime.now(), int(m.group(1)), int(m.group(2)))
        print(f"capture: next run {when:%Y-%m-%d %H:%M}", flush=True)
        while datetime.now() < when:
            time.sleep(min(300, max(1, (when - datetime.now()).total_seconds())))
        run()


if __name__ == "__main__":
    main()

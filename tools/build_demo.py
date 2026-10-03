#!/usr/bin/env python3
"""
Build the static Theme Picker demo (the GitHub Pages site).

    python3 tools/build_demo.py --out DIR --theme-park URL --custom-themes DIR

The real page and script, rendered with sample data (six example.com apps,
one pinned, one missing its theme; a few favourites; three weeks of
history), plus tools/demo/demo.js, which answers the picker's API in the
browser so that nothing needs a server: picking a theme re-dresses the page
only. Every theme's stylesheet is copied in (theme.park's from --theme-park,
the custom ones from --custom-themes), so the site needs nothing else.

--theme-park is any theme.park instance the build machine can reach; its
address never appears in the output (the build fails if it would).
"""

import argparse
import json
import os
import random
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE = "tokyo-night"
APPS = [("sonarr", "ok", ""), ("radarr", "ok", ""), ("prowlarr", "ok", ""), ("jellyfin", "ok", ""),
        ("grafana", "missing", "HTTP 200, no theme stylesheet in page"), ("portainer", "ok", "")]


def sample_state(d, custom):
    (d / "themes-src").mkdir()
    shutil.copytree(custom, d / "themes-src" / "themes")
    (d / "apps.yml").write_text("apps:\n" + "".join(f"  - name: {a}\n    theme_app: {a}\n" for a, _, _ in APPS))
    (d / "theme-overrides.json").write_text(json.dumps({"prowlarr": "nord"}))
    (d / "theme-favourites.json").write_text(json.dumps(["tokyo-night", "everforest", "cosmic-fusion", "nord"]))
    (d / "current-theme.env").write_text(f"CURRENT_THEME={LIVE}\n")
    (d / "theme-schedule.json").write_text(json.dumps({          # shown, never run: no server
        "enabled": True, "day": "catppuccin-latte", "night": "catppuccin-mocha",
        "day_at": "07:00", "night_at": "19:30"}))
    rng, t, hist = random.Random(7), datetime.now().astimezone() - timedelta(days=21), []
    pool = ["tokyo-night"] * 5 + ["everforest"] * 4 + ["catppuccin-mocha"] * 4 + ["catppuccin-latte"] * 3 + \
           ["nord", "gruvbox", "cosmic-fusion", "night-owl", "kanagawa", "frost", "dracula"]
    while t < datetime.now().astimezone() - timedelta(hours=2):
        hist.append({"theme": rng.choice(pool), "at": t.isoformat(timespec="seconds"),
                     "by": rng.choice(["schedule (day)", "schedule (night)", "alex", "someone on the LAN (no login)"])})
        t += timedelta(hours=rng.randint(3, 16))
    hist.append({"theme": LIVE, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "by": "alex"})
    (d / "theme-history.json").write_text(json.dumps(hist))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--theme-park", required=True, help="a theme.park instance to read themes from")
    ap.add_argument("--custom-themes", type=Path, required=True, help="a theme-park-themes checkout's themes/")
    args = ap.parse_args()
    tp = args.theme_park.rstrip("/")
    sandbox = Path(tempfile.mkdtemp(prefix="picker-demo-"))
    try:
        sample_state(sandbox, args.custom_themes)
        os.environ.update(THEME_SWITCHER_DIR=str(sandbox), PICKER_CONFIG=str(sandbox / "none.yml"),
                          DOMAIN="example.com", THEME_PARK_URL=tp, PICKER_URL="https://theme-picker.example.com/",
                          COVERAGE_INTERVAL="0")
        for k in [k for k in os.environ if k.startswith("NTFY")]:
            del os.environ[k]
        sys.path.insert(0, str(REPO))
        from picker import editor, render, themes

        out = args.out
        if out.exists():
            shutil.rmtree(out)
        (out / "static").mkdir(parents=True)
        (out / "css").mkdir()
        (out / "data" / "vars").mkdir(parents=True)

        allowed = themes.allowed_themes()
        css_map = {}
        for t in allowed:
            css = themes.theme_css(t)
            if not css:
                print(f"skipping {t}: no stylesheet", file=sys.stderr)
                continue
            (out / "css" / f"{t}.css").write_text(css)
            css_map[t] = f"css/{t}.css"
            (out / "data" / "vars" / f"{t}.json").write_text(json.dumps(editor.theme_vars(t)))

        html = render.render_page()
        # Stylesheet and assets: relative, so the site works under any path.
        html = re.sub(r'(<link rel="stylesheet" id="theme-css" href=")[^"]*(")', rf'\g<1>css/{LIVE}.css\g<2>', html)
        html = html.replace('"/static/', '"static/')
        html = html.replace('href="/manifest.webmanifest"', 'href="manifest.webmanifest"')
        html = re.sub(r'data-shots="[^"]*"', 'data-shots=""', html)          # no screenshots in the demo
        coverage = {"ok": 5, "total": 6, "checked": "", "results": [
            {"app": a, "url": f"https://{a}.example.com/", "expected": "nord" if a == "prowlarr" else LIVE,
             "pinned": a == "prowlarr", "state": s, "detail": det} for a, s, det in APPS]}
        demo = {"css": css_map, "coverage": coverage,
                "favourites": ["tokyo-night", "everforest", "cosmic-fusion", "nord"]}
        data_tag = ('<script type="application/json" id="demo-data">'
                    + json.dumps(demo).replace("</", "<\\/") + "</script>\n")
        banner = ('<p class="preview-banner demo-banner">This is a demo with sample data: picking a theme '
                  'changes this page only. <a href="https://github.com/prophetizer/theme-picker">Get Theme '
                  'Picker</a> to theme your own apps. Theme stylesheets: <a href="https://theme-park.dev">theme.park</a> '
                  'and <a href="https://github.com/prophetizer/theme-park-themes">theme-park-themes</a> (both MIT).</p>\n')
        html = html.replace('<p class="message" id="msg"', banner + '<p class="message" id="msg"', 1)
        html = html.replace('<script src="static/app.js', data_tag + '<script src="demo.js"></script>\n'
                            '<script src="static/app.js', 1)
        html = html.replace("<title>Theme Picker</title>", "<title>Theme Picker demo</title>", 1)
        # Saving is off in the demo, so no twin gets made on save either.
        html = re.sub(r'<span class="count" id="ed-twin-note">[^<]*</span>', '', html)
        if tp in html or urlhost(tp) in html:
            sys.exit("the theme.park address leaked into the page; refusing to write it")
        (out / "index.html").write_text(html)
        for name, data in render.STATIC.items():
            (out / "static" / name).write_bytes(data)
        shutil.copy(REPO / "tools" / "demo" / "demo.js", out / "demo.js")
        (out / "manifest.webmanifest").write_text(render.manifest(base="./"))
        (out / ".nojekyll").write_text("")
        for p in out.rglob("*"):
            if p.is_file() and p.suffix in (".html", ".css", ".js", ".json") and urlhost(tp) in p.read_text():
                sys.exit(f"the theme.park address leaked into {p}; refusing")
        print(f"demo written to {out}: {len(css_map)} themes")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def urlhost(url):
    return re.sub(r"^https?://", "", url).split("/")[0]


if __name__ == "__main__":
    main()

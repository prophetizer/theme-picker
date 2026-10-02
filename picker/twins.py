"""Every theme's light/dark twin, made by the picker itself -- portable mode.

The author's setup makes twins on the host (theme-park-themes'
make_variants.py, run by theme-worker.sh). With custom_themes.theme_park_www set there is no host
job, so deploy.deploy() calls sync() first and the twins are deployed like any
other custom theme:

  sources  your themes in custom_themes.dir (not generated ones), plus
           theme.park's own official and community themes in its www/
  twin     <source>-light.css or <source>-dark.css, written into
           custom_themes.dir with variants.MARK in its header, unless a real
           opposite-mode twin exists already (gruvbox-light for gruvbox)
  refresh  each twin records its source's hash; a changed source gets a new
           twin, a source that is gone (or gained a real twin) loses its one

Only files carrying the mark are ever overwritten or deleted, so a theme you
wrote yourself is never touched, even if its name looks like a twin's.
custom_themes.twins: false turns this off.
"""

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from . import spinner, variants

MAX_BYTES = 64 * 1024
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_GEN = re.compile(re.escape(variants.MARK) + r" (light|dark) of '([^']+)'")
_HASH = re.compile(r"Source sha256: ([0-9a-f]{16})")
ORIGIN = {"official": "theme.park's official theme", "community": "theme.park's community theme",
          "custom": "your theme"}


def _read(path):
    """Text of a small regular file (no symlink), else None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return None
    try:
        return data.decode()
    except UnicodeDecodeError:
        return None


def _write(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def source_hash(css):
    return hashlib.sha256(css.encode()).hexdigest()[:16]


def render(src_name, kind, css, target, decls, new, spin, button_hex):
    """make_variants.render(), naming the picker as the maker and recording
    the source's hash so a changed source is noticed."""
    title = variants.title_of(src_name, css)
    lines = [f"  {var}: {new[var] if var != '--petio-spinner' else spin};" for var, _ in decls]
    return (f"/*\n * theme.park custom theme: {title} ({target})\n *\n"
            f" * {variants.MARK} {target} of '{src_name}', {ORIGIN[kind]} -- by the theme picker.\n"
            f" * Source sha256: {source_hash(css)}\n"
            f" * Do not edit by hand: it is remade whenever '{src_name}' changes.\n"
            f" * Hues and saturation come from '{src_name}'; surfaces and text have their\n"
            f" * lightness flipped, accents keep their colour and move only as far as\n"
            f" * contrast needs (text 7:1, muted and links 4.5:1, UI 3:1 on every panel).\n"
            f" * --petio-spinner computed for '{button_hex}'.\n */\n"
            ":root {\n" + "\n".join(lines) + "\n}\n")


def _sources(custom_dir, www, deployed):
    """({name: (kind, css)} of every theme that can have a twin,
    {name: (target, source, hash)} of the twins already in custom_dir,
    names in custom_dir that aren't generated)."""
    srcs, generated, hand = {}, {}, set()
    for p in sorted(custom_dir.glob("*.css")):
        if not NAME.match(p.stem):
            continue
        css = _read(p)
        if css is None:
            hand.add(p.stem)                         # unreadable: never ours to touch
            continue
        m = _GEN.search(css[:1200])
        if m:
            h = _HASH.search(css[:1200])
            generated[p.stem] = (m.group(1), m.group(2), h.group(1) if h else "")
        else:
            hand.add(p.stem)
            srcs[p.stem] = ("custom", css)
    if www is not None:
        for sub, kind in (("theme-options", "official"), ("community-theme-options", "community")):
            for p in sorted((Path(www) / "css" / sub).glob("*.css")):
                # Deployed customs (and their twins) sit in theme-options too.
                if p.stem in deployed or p.stem in srcs or p.stem in generated or not NAME.match(p.stem):
                    continue
                css = _read(p)
                if css is not None and variants.MARK not in css[:1200]:
                    srcs[p.stem] = (kind, css)
    return srcs, generated, hand


def sync(custom_dir, www=None, deployed=frozenset()):
    """Make, refresh and remove twins in custom_dir. Returns
    {"made": [...], "removed": [...], "skipped": [(name, why), ...]}."""
    custom_dir = Path(custom_dir)
    out = {"made": [], "removed": [], "skipped": []}
    if not custom_dir.is_dir():
        return out
    srcs, generated, hand = _sources(custom_dir, www, set(deployed))
    modes = {}
    for name, (_kind, css) in srcs.items():
        decls = variants.declarations(css)
        modes[name] = variants.mode_of(decls) if "--main-bg-color" in dict(decls) else None
    wanted = {}
    for name, (kind, css) in sorted(srcs.items()):
        mode = modes[name]
        if not mode:
            out["skipped"].append((name, "unreadable"))
            continue
        target = "dark" if mode == "light" else "light"
        twin = next((t for t in variants.counterparts(name) if modes.get(t) == target), None)
        if twin:
            continue                                 # a real twin exists
        vname = f"{name}-{target}"
        if not NAME.match(vname) or vname in hand or vname in srcs:
            out["skipped"].append((name, f"'{vname}' is taken"))
            continue
        wanted[vname] = (name, kind, css, target)
    for vname, (name, kind, css, target) in sorted(wanted.items()):
        if generated.get(vname) == (target, name, source_hash(css)):
            continue                                 # up to date
        try:
            decls, new, button_hex = variants.build(name, css, target)
        except (ValueError, KeyError, ZeroDivisionError) as e:
            out["skipped"].append((name, str(e)[:100]))
            continue
        _write(custom_dir / f"{vname}.css",
               render(name, kind, css, target, decls, new, spinner.solve_filter(button_hex), button_hex))
        out["made"].append(vname)
    for vname in sorted(set(generated) - set(wanted)):
        (custom_dir / f"{vname}.css").unlink(missing_ok=True)
        out["removed"].append(vname)
    return out

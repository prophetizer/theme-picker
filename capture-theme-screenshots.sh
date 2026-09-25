#!/usr/bin/env bash
# Wrapper: runs capture_theme_screenshots.py in its own pinned venv.
# See that file for what it does -- it CHANGES THE LIVE THEME while running.
#
# First run creates the venv from capture-requirements.txt (Playwright drives
# the installed google-chrome via channel="chrome"; no browser is downloaded).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv-capture"
# Re-sync the venv whenever capture-requirements.txt changes, not only on
# first run -- otherwise a new pin never reaches an existing venv and the
# nightly run fails on an import.
STAMP="$VENV/.requirements.sha256"
WANT="$(sha256sum "$DIR/capture-requirements.txt" | cut -d' ' -f1)"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
if [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
  # `python -m pip`, not bin/pip: the venv moved with the repo split, and
  # its scripts' shebangs still point at the old path.
  "$VENV/bin/python" -m pip install -q -r "$DIR/capture-requirements.txt"
  echo "$WANT" > "$STAMP"
fi
exec "$VENV/bin/python" "$DIR/capture_theme_screenshots.py" "$@"

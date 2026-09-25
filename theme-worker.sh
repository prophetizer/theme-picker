#!/usr/bin/env bash
# Deploys themes saved in the theme picker's editor. Run every minute from the
# host crontab (see install-cron.sh); does nothing when the queue is empty.
#
# Why a host job at all: the picker container has no git and no Docker access,
# so it cannot commit a theme or run sync-themes.sh. It writes the finished
# CSS to editor-queue/<name>.css and this picks it up:
#
#   1. move it into themes-src/themes/ (the homelab-themes clone)
#   2. rebuild previews, commit, push to Forgejo
#   3. ./sync-themes.sh -- deploy into theme-park, regenerate, record dates
#   4. record the outcome in editor-status.json, which the picker polls
#
# The queue is NOT trusted: editor-queue/ is writable from inside the picker's
# container, and this job runs on the host with push access and deploys the
# file to every themed app. Each file is first copied somewhere the container
# cannot write (so it cannot change between check and commit), then must pass
# `python3 -m picker.editor --verify` -- parsed back into the editor's inputs
# and rebuilt byte-identical -- and may not overwrite a hand-authored theme.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The theme-switcher directory -- parent of this checkout unless overridden.
DIR="${THEME_SWITCHER_DIR:-$(dirname "$HERE")}"
QUEUE="$DIR/editor-queue"
SRC="$DIR/themes-src"
STATUS="$DIR/editor-status.json"

exec 9>"$DIR/.theme-worker.lock"
flock -n 9 || exit 0                       # a previous run is still going

shopt -s nullglob
queued=("$QUEUE"/*.css)
(( ${#queued[@]} )) || exit 0

status() {   # status <name> <state> <detail>
  python3 - "$STATUS" "$1" "$2" "$3" <<'PY'
import json, sys, datetime, pathlib
p, name, state, detail = pathlib.Path(sys.argv[1]), *sys.argv[2:]
try:
    st = json.loads(p.read_text())
except Exception:
    st = {}
st[name] = {"state": state, "detail": detail,
            "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n"); tmp.replace(p)
PY
}

echo "==> $(date -Is) deploying ${#queued[@]} theme(s) from the editor"
git -C "$SRC" pull --ff-only --quiet

PRIVATE="$(mktemp -d)"                     # host-only: the container cannot reach it
trap 'rm -rf "$PRIVATE"' EXIT

names=()
for f in "${queued[@]}"; do
  name="$(basename "$f" .css)"
  if [[ ! "$name" =~ ^[a-z0-9][a-z0-9-]{1,39}$ ]]; then
    echo "    rejecting bad name: $name"; rm -f -- "$f"; continue
  fi
  cp -- "$f" "$PRIVATE/$name.css" && rm -f -- "$f"
  if ! why="$(cd "$HERE" && python3 -m picker.editor --verify "$name" "$PRIVATE/$name.css" 2>&1)"; then
    echo "    rejecting $name: $why"; status "$name" failed "rejected: $why"; continue
  fi
  if [[ -e "$SRC/themes/$name.css" ]] && ! head -c 600 "$SRC/themes/$name.css" | grep -q "Created in the theme picker's editor"; then
    echo "    rejecting $name: would overwrite a hand-authored theme"
    status "$name" failed "an existing hand-authored theme has that name"; continue
  fi
  mv -- "$PRIVATE/$name.css" "$SRC/themes/$name.css"
  names+=("$name")
done
(( ${#names[@]} )) || exit 0

fail() { for n in "${names[@]}"; do status "$n" failed "$1"; done; echo "!! $1" >&2; exit 1; }

( cd "$SRC" && python3 build_previews.py >/dev/null ) || fail "preview build failed"
git -C "$SRC" add themes previews
if ! git -C "$SRC" diff --cached --quiet; then
  git -C "$SRC" commit -q -m "Add/update ${names[*]} from the theme picker editor" \
    -m "Saved in the theme picker's editor and deployed by theme-worker.sh." \
    || fail "git commit failed"
  git -C "$SRC" push -q origin HEAD || fail "git push failed (theme is committed locally)"
fi
"$DIR/sync-themes.sh" >/dev/null || fail "sync-themes.sh failed"

for n in "${names[@]}"; do status "$n" deployed "committed, pushed and deployed"; echo "    deployed $n"; done

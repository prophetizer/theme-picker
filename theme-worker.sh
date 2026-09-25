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

# Lock (and, via install-cron.sh, the log) live where the container cannot
# reach: in theme-switcher/ it could replace the lock with a symlink, and the
# `exec 9>` below would truncate whatever file that points at, every minute.
HOST_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/theme-picker"
mkdir -p -m 700 "$HOST_STATE"
exec 9>"$HOST_STATE/theme-worker.lock"
flock -n 9 || exit 0                       # a previous run is still going

shopt -s nullglob
queued=("$QUEUE"/*.css)
(( ${#queued[@]} )) || exit 0

status() {   # status <name> <state> <detail>
  # editor-status.json is container-writable, so: read it without following a
  # link, keep only well-formed entries, and write through a fresh temp file
  # (a fixed "editor-status.tmp" could be a planted symlink to any host file).
  python3 - "$STATUS" "$1" "$2" "$3" <<'PY'
import datetime, json, os, re, stat, sys, tempfile
path, name, state, detail = sys.argv[1:]
st = {}
try:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            st = json.loads(f.read(256 * 1024) or b"{}")
except (OSError, ValueError):
    st = {}
ok = lambda k, v: (isinstance(k, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", k)
                   and isinstance(v, dict) and all(isinstance(x, str) for x in v.values()))
st = {k: v for k, v in st.items() if ok(k, v)} if isinstance(st, dict) else {}
st[name] = {"state": state, "detail": detail,
            "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".editor-status-", suffix=".tmp")
with os.fdopen(fd, "w") as f:
    f.write(json.dumps(st, indent=1, sort_keys=True) + "\n")
os.chmod(tmp, 0o644)                     # mkstemp's 0600 would lock the picker out
os.replace(tmp, path)
PY
}

# take <queued file> <dest>: copy one queue entry somewhere host-only, refusing
# anything that is not a small regular file. The queue is container-writable:
# a symlink could point at /dev/zero (filling /tmp, which is RAM here) or at
# any host file, and a FIFO would hang this job while it holds the lock.
take() {
  python3 - "$1" "$2" <<'PY'
import os, stat, sys
src, dst = sys.argv[1:]
try:
    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
except OSError as e:
    sys.exit(f"cannot open safely ({e.strerror})")
with os.fdopen(fd, "rb") as f:
    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        sys.exit("not a regular file")
    data = f.read(16 * 1024 + 1)
if len(data) > 16 * 1024:
    sys.exit("larger than 16 KB")
with open(dst, "xb") as out:
    out.write(data)
PY
}

echo "==> $(date -Is) deploying ${#queued[@]} theme(s) from the editor"
git -C "$SRC" pull --ff-only --quiet

PRIVATE="$(mktemp -d)"                     # host-only: the container cannot reach it
trap 'rm -rf "$PRIVATE"' EXIT

names=()
for f in "${queued[@]}"; do
  name="$(basename "$f" .css)"
  # The file must be exactly <name>.css: $(...) drops trailing newlines, so
  # "nord<newline>.css" came out as "nord" and was committed as nord.css.
  if [[ ! "$name" =~ ^[a-z0-9][a-z0-9-]{1,39}$ || "$f" != "$QUEUE/$name.css" ]]; then
    printf '    rejecting bad name: %q\n' "$(basename "$f")"; rm -f -- "$f"; continue
  fi
  if ! why="$(take "$f" "$PRIVATE/$name.css" 2>&1)"; then
    rm -f -- "$f"; echo "    rejecting $name: $why"; status "$name" failed "rejected: $why"; continue
  fi
  rm -f -- "$f"
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
# Only what this run verified: "add themes previews" also committed -- and
# sync-themes.sh then deployed -- any file placed in themes-src/ by other means.
paths=(previews/index.html)
for n in "${names[@]}"; do paths+=("themes/$n.css" "previews/$n-preview.html"); done
git -C "$SRC" add -- "${paths[@]}" || fail "git add failed"
if ! git -C "$SRC" diff --cached --quiet; then
  git -C "$SRC" commit -q -m "Add/update ${names[*]} from the theme picker editor" \
    -m "Saved in the theme picker's editor and deployed by theme-worker.sh." \
    || fail "git commit failed"
  git -C "$SRC" push -q origin HEAD || fail "git push failed (theme is committed locally)"
fi
"$DIR/sync-themes.sh" >/dev/null || fail "sync-themes.sh failed"

for n in "${names[@]}"; do status "$n" deployed "committed, pushed and deployed"; echo "    deployed $n"; done

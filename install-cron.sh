#!/usr/bin/env bash
# Installs (or refreshes) the theme-switcher's two cron jobs in the CURRENT
# USER's crontab, leaving any other entries alone. Re-run after moving the
# repo. Remove with: ./install-cron.sh --remove
#
#   every minute  theme-worker.sh              deploys themes saved in the
#                                              picker's editor (no-op if none)
#   04:30 daily   capture-theme-screenshots.sh screenshots themes that have
#                                              none yet, or whose file changed
#
# A user crontab rather than a systemd user timer: this account has
# Linger=no, so user timers stop whenever nobody is logged in -- including
# after every reboot. Cron runs regardless.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"            # this checkout
TS="${THEME_SWITCHER_DIR:-$(dirname "$DIR")}"                  # theme-switcher/
BEGIN="# >>> theme-switcher (managed by $DIR/install-cron.sh) >>>"
END="# <<< theme-switcher <<<"

current="$(crontab -l 2>/dev/null || true)"
others="$(printf '%s\n' "$current" | sed "/^# >>> theme-switcher/,/^# <<< theme-switcher <<</d")"

if [[ "${1:-}" == "--remove" ]]; then
  printf '%s\n' "$others" | sed '/^$/N;/^\n$/D' | crontab -
  echo "Removed theme-switcher cron jobs."; exit 0
fi

# Logs go somewhere the picker's container cannot write: in theme-switcher/
# (mounted into it) a planted symlink would have cron append to any file.
LOGS="${XDG_STATE_HOME:-$HOME/.local/state}/theme-picker"
mkdir -p -m 700 "$LOGS"
# Optional dead-man's-switch pings (Healthchecks or any compatible service):
# each job pings its URL after a successful run, so a job that silently stops
# running raises an alert. The URLs act as secrets -- anyone holding one can
# ping it -- so they live in a host-only file, never in this repo:
#   ~/.config/theme-picker/healthchecks.env   (mode 600)
#   HC_WORKER_URL=https://hc.example.com/ping/<uuid>
#   HC_CAPTURE_URL=https://hc.example.com/ping/<uuid>
# Parsed, not sourced, and only plain http(s) URLs are accepted.
HC_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/theme-picker/healthchecks.env"
hc_url() {   # hc_url KEY -> the URL, or nothing
  [[ -f "$HC_FILE" ]] || return 0
  local v
  v="$(sed -n "s/^$1=//p" "$HC_FILE" | tail -n1 | tr -d '\r')"
  # No %: cron turns it into a newline. No quotes or spaces: it is quoted below.
  if [[ "$v" =~ ^https?://[A-Za-z0-9._~:/?#@!\$\&*+,\;=-]+$ ]]; then printf '%s' "$v"; fi
  return 0
}
ping_suffix() {   # ping_suffix URL -> " && curl ... URL", or nothing
  if [[ -n "$1" ]]; then printf " && curl -fsS -m 10 --retry 3 -o /dev/null '%s'" "$1"; fi
  return 0
}
worker_ping="$(ping_suffix "$(hc_url HC_WORKER_URL)")"
capture_ping="$(ping_suffix "$(hc_url HC_CAPTURE_URL)")"

block="$BEGIN
PATH=/usr/local/bin:/usr/bin:/bin
* * * * *  $DIR/theme-worker.sh >> $LOGS/theme-worker.log 2>&1$worker_ping
30 4 * * * $DIR/capture-theme-screenshots.sh >> $LOGS/capture-nightly.log 2>&1$capture_ping
$END"
{ [[ -n "${others//[$'\n ']/}" ]] && printf '%s\n\n' "$others"; printf '%s\n' "$block"; } | crontab -
echo "Installed. Current crontab:"; crontab -l

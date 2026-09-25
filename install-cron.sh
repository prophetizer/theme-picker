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

mkdir -p "$TS/logs"
block="$BEGIN
PATH=/usr/local/bin:/usr/bin:/bin
* * * * *  $DIR/theme-worker.sh >> $TS/logs/theme-worker.log 2>&1
30 4 * * * $DIR/capture-theme-screenshots.sh >> $TS/logs/capture-nightly.log 2>&1
$END"
{ [[ -n "${others//[$'\n ']/}" ]] && printf '%s\n\n' "$others"; printf '%s\n' "$block"; } | crontab -
echo "Installed. Current crontab:"; crontab -l

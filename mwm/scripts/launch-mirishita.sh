#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
config="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
mkdir -p "$state" "$config"
exec 9>"$state/mirishita-launcher.lock"
flock -n 9 || exit 0
exec >>"$state/mirishita-launcher.log" 2>&1
trap 'rc=$?; if command -v notify-send >/dev/null; then notify-send "Mirishita (MWM)" "Startup failed. See MWM launcher log."; fi; exit "$rc"' ERR
# Only initialize the missing backend; keep existing render/display settings.
if [[ ! -e "$config/display-backend" ]]; then
  (
    flock -x 7
    if [[ ! -e "$config/display-backend" ]]; then
      tmp="$(mktemp "$config/.display-backend.XXXXXX")"
      printf 'gamescope\n' > "$tmp"
      mv -- "$tmp" "$config/display-backend"
    fi
  ) 7>"${XDG_CONFIG_HOME:-$HOME/.config}/mwm-config.lock"
fi
if [[ "$(bash "$script_dir/gamescope-control.sh" status 2>/dev/null)" == running\ * ]] &&
   LC_ALL=C waydroid status | grep -Eq 'Session:[[:space:]]*RUNNING'; then
  bash "$script_dir/waydroid-control.sh" launch
else
  bash "$script_dir/waydroid-control.sh" start
  # A dedicated game shortcut also launches when Auto Launch is disabled.
  bash "$script_dir/waydroid-control.sh" launch
fi

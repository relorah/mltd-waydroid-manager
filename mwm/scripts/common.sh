#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

APP_ID="com.bandainamcoent.imas_millionlive_theaterdays"
RTSCALE_CONF="/data/local/tmp/gles_rtscale.conf"
MWM_ROOT_HELPER="/usr/local/libexec/mwm-root-helper"
MWM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

root_helper() {
  if [[ ! -x "$MWM_ROOT_HELPER" ]]; then
    echo "MWM root helper is not installed. Run the top-level install.sh once." >&2
    return 126
  fi
  case "${1:-}" in
    rtscale-write|rtscale-remove|reset-wm-size|set-media-volume|force-stop-app)
      refresh_guard || return $?
      ;;
  esac
  sudo -n "$MWM_ROOT_HELPER" "$@"
}

waydroid_initialized() {
  [[ -f /var/lib/waydroid/waydroid.cfg ]] || [[ -f /var/lib/waydroid/images/system.img ]]
}

require_waydroid_initialized() {
  if ! waydroid_initialized; then
    echo "Waydroid is not initialized. Prepare a working Waydroid + Mirishita environment before using MWM." >&2
    exit 20
  fi
}

wait_waydroid_boot() {
  local i
  for i in $(seq 1 120); do
    if root_helper boot-completed 2>/dev/null | grep -qx '1'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Enabled only during Waydroid Refresh. Latch detection for the entire run.
refresh_guard() {
  [[ "${MWM_SKIP_STARTUP_VERIFICATION:-0}" != 1 ]] || return 0
  [[ -n "${MWM_REFRESH_GUARD_FILE:-}" ]] || return 0
  local pids query query_rc
  if [[ ! -s "$MWM_REFRESH_GUARD_FILE" ]]; then
    query_rc=0
    query="$(sudo -n "$MWM_ROOT_HELPER" game-process-state 2>/dev/null)" || query_rc=$?
    if (( query_rc != 0 )) || ! grep -qx MWM_PID_QUERY_OK <<< "$query"; then
      if [[ -f "$MWM_REFRESH_GUARD_FILE.ready" ]]; then
        printf '%s PID query failed\n' "$(date --iso-8601=ns)" >> "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-events.log"
        printf 'QUERY_FAILED\n' > "$MWM_REFRESH_GUARD_FILE"
      else
        return 0
      fi
    fi
    pids="$(grep -v '^MWM_PID_QUERY_OK$' <<< "$query" || true)"
    if [[ "$pids" =~ ^[[:space:]]*[0-9]+([[:space:]]+[0-9]+)*[[:space:]]*$ ]]; then
      printf '%s early game launch PID=%s\n' "$(date --iso-8601=ns)" "$pids" >> "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-events.log"
      printf '%s PID=%s\n' "$(date --iso-8601=ns)" "$pids" > "$MWM_REFRESH_GUARD_FILE"
    fi
  fi
  if grep -q QUERY_FAILED "$MWM_REFRESH_GUARD_FILE" 2>/dev/null; then
    echo "Could not verify Mirishita process status. Settings application was interrupted. Update the root helper and check Waydroid." >&2
    return 78
  fi
  if [[ -s "$MWM_REFRESH_GUARD_FILE" ]]; then
    echo "MWM_REFRESH_EARLY_LAUNCH: Mirishita launched while settings were being applied. Refresh was interrupted.Some settings may have been applied.Close Mirishita and run Waydroid Refresh again." >&2
    return 76
  fi
}

refresh_phase() {
  local state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
  mkdir -p "$state" || return 0
  printf '%s\n' "$1" > "$state/refresh-phase.tmp.$$" &&
    mv -f "$state/refresh-phase.tmp.$$" "$state/refresh-phase" || true
  printf '%s stage=%s\n' "$(date --iso-8601=ns)" "$1" >> "$state/refresh-events.log" || true
}

# Numeric-only Android geometry, bounded retries; diagnostics stay on stderr.
read_waydroid_dimension() {
  python "$MWM_DIR/scripts/waydroid_dimensions.py" "$1"
}

gamescope_span_enabled() {
  [[ "${XDG_CURRENT_DESKTOP:-}" != *[Gg][Nn][Oo][Mm][Ee]* ]] || return 1
  [[ "$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/mwm/gamescope-span-enabled" 2>/dev/null || echo off)" == on ]]
}

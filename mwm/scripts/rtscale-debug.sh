#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -u
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
LOG_FILE="$STATE_DIR/rtscale-debug.log"
MAX_BYTES=$((2 * 1024 * 1024))
KEEP_BYTES=$((1024 * 1024))
mkdir -p "$STATE_DIR"

action_backend() {
  local v
  v="$(cat "$CFG_DIR/display-backend" 2>/dev/null || true)"
  case "$v" in kwin|gamescope) echo "$v" ;; *) echo gamescope ;; esac
}

render_mode() {
  local v
  v="$(cat "$CFG_DIR/gamescope-render-mode" 2>/dev/null || true)"
  case "$v" in rtscale|fsr) echo "$v" ;; *) [[ "$(action_backend)" == kwin ]] && echo rtscale || echo fsr ;; esac
}

saved_scale() {
  local v="3"
  [[ -f "$CFG_DIR/kwin-rtscale" ]] && v="$(tr -d '[:space:]' < "$CFG_DIR/kwin-rtscale" 2>/dev/null || true)"
  case "$v" in off|[1-8]) echo "$v" ;; 9|10) echo 8 ;; *) echo 3 ;; esac
}

expected_base() {
  local mode w h
  if [[ "$(action_backend)" == gamescope ]]; then
    w="$(read_waydroid_dimension width 2>/dev/null || true)"
    h="$(read_waydroid_dimension height 2>/dev/null || true)"
    if [[ "$w" =~ ^[0-9]+$ && "$h" == 1080 ]]; then
      w=$(( (10#$w * 720 + 540) / 1080 ))
      (( w % 2 == 0 )) || ((w++))
      printf '%sx720\n' "$w"
    else
      echo 'unavailable (display not applied)'
    fi
    return
  fi
  w="$(read_waydroid_dimension width 2>/dev/null || true)"
  h="$(read_waydroid_dimension height 2>/dev/null || true)"
  if [[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] && (( 10#$w > 0 && 10#$h > 0 )); then
    w=$(( (10#$w * 720 + 10#$h / 2) / 10#$h ))
    (( w % 2 == 0 )) || ((w++))
    printf '%sx720\n' "$w"
  else
    echo 'unavailable (KWin logical display not applied)'
  fi
}

trim_log() {
  [[ -f "$LOG_FILE" ]] || return 0
  local size
  size="$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)"
  (( size <= MAX_BYTES )) && return 0
  tail -c "$KEEP_BYTES" "$LOG_FILE" > "$LOG_FILE.tmp" 2>/dev/null || return 0
  mv -f "$LOG_FILE.tmp" "$LOG_FILE"
  printf '[%s] log-trimmed\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" >> "$LOG_FILE"
}

read_config() { root_helper rtscale-read 2>/dev/null || true; }
latest_runtime() { root_helper rtscale-log-mirishita 2>/dev/null | tail -n1 || true; }

summary_view() {
  local b mode render
  b="$(action_backend)"
  render="$(render_mode)"
  mode="$(cat "$CFG_DIR/aspect-ratio" 2>/dev/null || echo auto)"
  if [[ "$b" == kwin ]]; then
    printf 'Backend: KDE / KWin + RTScale (High Quality)\n'
  elif [[ "$render" == rtscale ]]; then
    printf 'Backend: Gamescope + RTScale\n'
  else
    printf 'Backend: Gamescope + FSR1 (Balanced)\n'
  fi
  printf 'Display: %s\n' "$mode"
  printf 'Waydroid: %s\n' "$(waydroid status 2>/dev/null | tr '\n' ';' || echo unavailable)"
  if [[ "$render" == rtscale ]]; then
    printf 'RTScale: %s\n' "$(saved_scale)"
    printf 'Expected base: %s\n' "$(expected_base)"
    printf 'Runtime: %s\n' "$(latest_runtime)"
    printf 'Config:\n%s\n' "$(read_config)"
  else
    printf 'RTScale: Disabled by FSR render mode\n'
    printf 'Gamescope: %s\n' "$("$SCRIPT_DIR/gamescope-control.sh" status 2>/dev/null || true)"
  fi
  printf 'Debug mode: automatic / event-based\n'
  printf 'Log: %s\n' "$LOG_FILE"
}

runtime_view() {
  local b render
  b="$(action_backend)"
  render="$(render_mode)"
  printf 'Backend: %s / render=%s\n' "$b" "$render"
  if [[ "$render" != rtscale ]]; then
    echo 'RTScale runtime is disabled in the FSR profile.'
    "$SCRIPT_DIR/gamescope-control.sh" status 2>/dev/null || true
    return 0
  fi
  echo '--- config ---'
  read_config
  echo '--- latest runtime ---'
  latest_runtime
  echo '--- runtime history ---'
  root_helper rtscale-log-mirishita 2>/dev/null || true
  echo '--- Mirishita processes ---'
  root_helper mirishita-processes 2>/dev/null || true
}

surface_view() {
  echo '--- display state ---'
  root_helper rtscale-display-state 2>/dev/null || true
  echo '--- surfaces ---'
  root_helper rtscale-surfaces 2>/dev/null || true
  echo '--- surface details ---'
  root_helper rtscale-surface-details 2>/dev/null || true
}

libraries_view() {
  echo '--- host overlay hashes ---'
  root_helper rtscale-overlay-hashes 2>/dev/null || true
  echo '--- Android library hashes ---'
  root_helper rtscale-android-lib-hashes 2>/dev/null || true
  echo '--- Mirishita process maps ---'
  root_helper rtscale-process-maps 2>/dev/null || true
}

event_record() {
  local name="${1:-event}" b mode scale runtime render
  trim_log
  b="$(action_backend)"
  render="$(render_mode)"
  mode="$(cat "$CFG_DIR/aspect-ratio" 2>/dev/null || echo auto)"
  scale="$(saved_scale)"
  runtime=""
  [[ "$render" == rtscale ]] && runtime="$(latest_runtime)"
  {
    printf '[%s] EVENT %s backend=%s display=%s' "$(date '+%Y-%m-%d %H:%M:%S.%3N%z')" "$name" "$b" "$mode"
    if [[ "$render" == rtscale ]]; then
      printf ' scale=%s base=%s runtime=%q' "$scale" "$(expected_base)" "${runtime:-none}"
    else
      printf ' rtscale=disabled'
    fi
    printf '\n'
  } >> "$LOG_FILE"
}

snapshot_record() {
  local name="${1:-snapshot}"
  trim_log
  {
    printf '\n=== SNAPSHOT %s / %s ===\n' "$name" "$(date '+%Y-%m-%d %H:%M:%S%z')"
    summary_view
    echo
    runtime_view
    echo
    surface_view
    echo
    libraries_view
    echo '=== END SNAPSHOT ==='
  } >> "$LOG_FILE"
}

case "${1:-status}" in
  event) event_record "${2:-event}" ;;
  snapshot) snapshot_record "${2:-snapshot}" ;;
  view)
    case "${2:-summary}" in
      summary) summary_view ;;
      runtime) runtime_view ;;
      surface) surface_view ;;
      libraries) libraries_view ;;
      log) [[ -f "$LOG_FILE" ]] && cat "$LOG_FILE" || echo '(log is empty)' ;;
      *) echo "unknown view: ${2:-}" >&2; exit 2 ;;
    esac
    ;;
  clear) : > "$LOG_FILE"; echo "RTScale debug log cleared" ;;
  status) echo "automatic / event-based / $LOG_FILE" ;;
  log) echo "$LOG_FILE" ;;
  *) echo "usage: $0 event NAME|snapshot NAME|view summary|runtime|surface|libraries|log|clear|status|log" >&2; exit 2 ;;
esac

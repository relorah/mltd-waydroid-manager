#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -u
source "$(dirname "$0")/common.sh"

ACTION="${1:-status}"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
RTSCALE_STATE="$CFG_DIR/kwin-rtscale"
BACKEND_FILE="$CFG_DIR/display-backend"
RENDER_MODE_FILE="$CFG_DIR/gamescope-render-mode"
MOUSE_STATE="$CFG_DIR/mouse-as-touch"
GAMESCOPE_CTL="$(dirname "$0")/gamescope-control.sh"
RTSCALE_DEBUG_CTL="$(dirname "$0")/rtscale-debug.sh"

backend() {
  echo gamescope
}


render_mode() {
  local v="${MWM_RENDER_MODE_OVERRIDE:-}"
  if [[ -z "$v" ]]; then
    v=fsr
    [[ -f "$RENDER_MODE_FILE" ]] && v="$(tr -d '[:space:]' < "$RENDER_MODE_FILE" 2>/dev/null || true)"
  fi
  case "$v" in rtscale|fsr) echo "$v" ;; *) echo fsr ;; esac
}

saved_render_mode() {
  local v=fsr
  [[ -f "$RENDER_MODE_FILE" ]] && v="$(tr -d '[:space:]' < "$RENDER_MODE_FILE" 2>/dev/null || true)"
  case "$v" in rtscale|fsr) echo "$v" ;; *) echo fsr ;; esac
}


saved_scale() {
  local v="off"
  [[ -f "$RTSCALE_STATE" ]] && v="$(tr -d '[:space:]' < "$RTSCALE_STATE" 2>/dev/null || true)"
  case "$v" in off|[1-8]) echo "$v" ;; 9|10) echo 8 ;; *) echo off ;; esac
}

mouse_as_touch_enabled() {
  [[ ! -f "$MOUSE_STATE" ]] && return 0
  case "$(tr '[:upper:]' '[:lower:]' < "$MOUSE_STATE" 2>/dev/null | tr -d '[:space:]')" in
    off|0|false|no) return 1 ;;
    *) return 0 ;;
  esac
}

status_waydroid() {
  if ! waydroid_initialized; then echo "Not initialized"; exit 0; fi
  local out b
  b="$(backend)"
  out="$(waydroid status 2>&1 || true)"
  if grep -qi 'not initialized' <<<"$out"; then
    echo "Not initialized"
  elif grep -qi 'Session:[[:space:]]*RUNNING' <<<"$out"; then
    if [[ "$b" == gamescope ]]; then
      echo "Running / Gamescope $($GAMESCOPE_CTL status 2>/dev/null || true)"
    else
      echo "Running / KWin Direct"
    fi
  elif grep -qi 'Container:[[:space:]]*RUNNING' <<<"$out"; then
    echo "Container running / backend=$b"
  else
    echo "Stopped / backend=$b"
  fi
}

post_launch_assists() {
  # Audio normalization is always enabled in v0.5.52. Android media volume
  # is applied immediately; the PipeWire stream is normalized asynchronously
  # once the game starts producing audio.
  root_helper set-media-volume >/dev/null 2>&1 || true
  ("$(dirname "$0")/set-audio-levels.sh" >/dev/null 2>&1 8>&- 7>&- &) || true

  "$(dirname "$0")/touch-mapper.sh" stop >/dev/null 2>&1 || true

}

display_exit_status() {
  [[ "$(backend)" == gamescope ]] || return 0
  [[ "$("$GAMESCOPE_CTL" status)" == stopped ]] || return 0
  case "$("$GAMESCOPE_CTL" exit-code)" in
    0|143) return 130 ;;  # Window close or requested SIGTERM.
    *) echo "Gamescope failed. Log: $("$GAMESCOPE_CTL" log)" >&2; return 4 ;;
  esac
}

wait_runtime_boot() {
  local i
  for i in $(seq 1 120); do
    refresh_guard || return $?
    display_exit_status || return $?
    if root_helper boot-completed 2>/dev/null | grep -qx '1'; then return 0; fi
    sleep 1
  done
  return 3
}

mirishita_running() {
  [[ -n "$(root_helper pidof-mirishita 2>/dev/null | tr -d '[:space:]')" ]]
}

wait_mirishita_stopped() {
  local i
  for i in $(seq 1 20); do
    ! mirishita_running && return 0
    sleep 0.5
  done
  echo "Mirishita process remained alive after force-stop; refusing to reuse its old task." >&2
  return 1
}

wait_mirishita_running() {
  local i
  for i in $(seq 1 20); do
    display_exit_status || return $?
    mirishita_running && return 0
    sleep 0.5
  done
  return 1
}

launch_trace() {
  local state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
  mkdir -p "$state"
  printf '%s %s\n' "$(date --iso-8601=ns)" "$*" >> "$state/mirishita-launch.log"
}
launch_command() {
  local rc=0 state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
  launch_trace "begin: $*"
  "$@" >> "$state/mirishita-launch.log" 2>&1 || rc=$?
  launch_trace "end rc=$rc: $*"
  return "$rc"
}
launch_mirishita() {
  launch_trace "launch_mirishita entered"
  if ! root_helper app-installed >/dev/null 2>&1; then
    echo "Mirishita is not installed" >&2
    return 6
  fi

  root_helper set-media-volume >/dev/null 2>&1 || true

  # v0.5.51 treated a zero exit status from `waydroid app launch` as success.
  # That command can return successfully before an Android activity actually
  # starts.  v0.5.52 verifies the game PID and falls back to `monkey`.
  local attempt wait_rc
  for attempt in 1 2 3; do
    display_exit_status || return $?
    mirishita_running && break

    echo "Mirishita: launch attempt $attempt..."
    launch_command waydroid app launch "$APP_ID" || true
    wait_rc=0
    wait_mirishita_running || wait_rc=$?
    launch_trace "attempt=$attempt PID wait rc=$wait_rc"
    (( wait_rc != 0 && wait_rc != 1 )) && return "$wait_rc"
    (( wait_rc == 0 )) && break

    launch_command root_helper launch-mirishita || true
    wait_rc=0
    wait_mirishita_running || wait_rc=$?
    launch_trace "attempt=$attempt PID wait rc=$wait_rc"
    (( wait_rc != 0 && wait_rc != 1 )) && return "$wait_rc"
    (( wait_rc == 0 )) && break

    root_helper force-stop-app >/dev/null 2>&1 || true
    sleep 1
  done

  if ! mirishita_running; then
    echo "Mirishita launch failed: no running process after retries" >&2
    return 6
  fi

  post_launch_assists
  echo "Mirishita: READY"
}

start_display_session() {
  python "$(dirname "$0")/kwin-fullscreen.py" stop || true
  "$GAMESCOPE_CTL" start 8>&- 7>&-
}

stop_display_session() {
  python "$(dirname "$0")/kwin-fullscreen.py" stop || true
  # Disable direct physical input while Android is still running, before
  # the container is removed. This migrates older installations on Restart.
  waydroid prop set persist.waydroid.uevent false >/dev/null 2>&1 || true
  "$(dirname "$0")/touch-mapper.sh" stop >/dev/null 2>&1 || true
  "$GAMESCOPE_CTL" stop >/dev/null 2>&1 || true
  waydroid session stop >/dev/null 2>&1 || true
}

stop_all_verified() {
  python "$(dirname "$0")/performance-overlay.py" stop || true
  stop_display_session
  if ! root_helper container-stop; then
    echo "Waydroid container stop failed; new settings have not been applied." >&2
    return 4
  fi
  local i status
  for i in $(seq 1 40); do
    if status="$(LC_ALL=C waydroid status 2>&1)" &&
       grep -Eq 'Session:[[:space:]]*STOPPED' <<<"$status" &&
       ! grep -Eq '(Session|Container):[[:space:]]*RUNNING' <<<"$status"; then
      return 0
    fi
    sleep 0.25
  done
  echo "Previous Waydroid session did not stop; refusing to reuse it." >&2
  return 4
}

apply_runtime_after_boot() {
  local b="$1" scale render
  render="$(render_mode)"
  # Restore test6's post-boot property application. A stopped session has no
  # IPlatform service, so the pre-start call alone cannot apply presets.
  local mode
  mode="${MWM_ASPECT_MODE_OVERRIDE:-$(cat "$CFG_DIR/aspect-ratio" 2>/dev/null || echo auto)}"
  refresh_guard || return $?
  "$(dirname "$0")/set-aspect-ratio.sh" "$mode" || { refresh_guard || return $?; return 4; }

  # Fractional KDE scaling converts logical properties to physical pixels.
  # This experimental check is diagnostic: do not reboot Android merely
  # because its physical dimensions differ from logical dimensions.
  if [[ "$b" == kwin ]]; then
    local pw ph actual_size
    pw="$(read_waydroid_dimension width)"
    ph="$(read_waydroid_dimension height)"
    actual_size="$(root_helper wm-size)"
    if ! python "$(dirname "$0")/kwin-physical-size.py" "$pw" "$ph" "$actual_size"; then
      echo "WARNING: KWin physical geometry could not be confirmed; continuing without container recreation." >&2
    fi
  fi

  refresh_guard || return $?
  if mouse_as_touch_enabled; then
    "$(dirname "$0")/fake-touch.sh" on >/dev/null 2>&1 || true
  else
    "$(dirname "$0")/fake-touch.sh" off >/dev/null 2>&1 || true
  fi

  if [[ "${MWM_SKIP_STARTUP_VERIFICATION:-0}" == 1 ]]; then
    : # Settings readback remains mandatory; presentation settling is skipped.
  elif [[ "$b" == gamescope ]]; then
    refresh_phase "Checking display..."
    "$(dirname "$0")/wait-display-ready.sh" || return $?
  else
    refresh_phase "KWin fullscreen readiness"
    python "$(dirname "$0")/kwin-fullscreen.py" wait || {
      python "$(dirname "$0")/kwin-fullscreen.py" stop || true
      return 4
    }
    # Recheck the aspect properties after fullscreen configure/settling.
    # This also refuses a silent change to a panel-dependent client size.
    "$(dirname "$0")/set-aspect-ratio.sh" "$mode" || return 4
    python "$(dirname "$0")/kwin-fullscreen.py" wait || return 4
  fi

  refresh_guard || return $?

  refresh_phase "Applying rendering settings..."
  if [[ "$b" == gamescope && "$render" == fsr ]]; then
    # The FSR profile uses Gamescope as its spatial upscaler; clear RTScale.
    local removed
    removed="$(root_helper rtscale-remove)" || { refresh_guard || return $?; return 5; }
    if ! grep -qx 'MWM_RTSCALE_ABSENT' <<<"$removed"; then
      echo "RTScale removal could not be verified. Run install.sh --update-app from this release to update the root helper." >&2
      refresh_guard || return $?
      return 5
    fi
    echo "RTScale: OFF / Gamescope backend"
  elif [[ "$b" == gamescope ]]; then
    scale="$(saved_scale)"
    if ! "$(dirname "$0")/set-rtscale.sh" "$scale"; then
      echo "RTScale setup failed for the Gamescope + RTScale profile" >&2
      refresh_guard || return $?
      return 5
    fi
  else
    scale="$(saved_scale)"
    if ! "$(dirname "$0")/set-rtscale.sh" "$scale"; then
      echo "RTScale runtime setup failed" >&2
      refresh_guard || return $?
      return 5
    fi
  fi
}

auto_start_after_refresh() {
  local rc=0 i
  launch_trace "settings complete; automatic launch stage"
  display_exit_status || return $?
  if mirishita_running; then
    launch_trace "automatic launch skipped: PID already present"
    echo "MWM_GAME_ALREADY_RUNNING: Mirishita is already running. Automatic launch was skipped."
    return 0
  fi
  # Single request; no force-stop/retry or audio helpers in this test path.
  launch_command waydroid app launch "$APP_ID" || rc=$?
  if (( rc != 0 )); then
    echo "Could not request automatic Mirishita launch. Check the log." >&2
    return 6
  fi
  rc=0
  wait_mirishita_running || rc=$?
  launch_trace "automatic launch PID wait rc=$rc"
  (( rc == 0 )) || return "$rc"
  # PID existence is not gameplay readiness. Check a short survival interval.
  for i in {1..6}; do
    sleep 0.5
    display_exit_status || return $?
    if ! mirishita_running; then
      launch_trace "game PID disappeared during startup observation"
      echo "The Mirishita process exited immediately after launch." >&2
      return 6
    fi
  done
  launch_trace "automatic launch: PID survived 3 seconds"
  echo "Mirishita: PID confirmed / short startup observation complete"
}

stop_mirishita_for_refresh() {
  local query i
  refresh_phase "Stopping Mirishita..."
  # Called before creating the early-launch guard: this is an intentional stop.
  if ! root_helper force-stop-app; then
    echo "Could not stop Mirishita. Settings have not been applied." >&2
    return 4
  fi
  for i in {1..20}; do
    if ! query="$(root_helper game-process-state)" ||
       ! grep -qx MWM_PID_QUERY_OK <<< "$query"; then
      echo "Could not verify Mirishita stopped. Settings have not been applied." >&2
      return 78
    fi
    if [[ -z "$(grep -v '^MWM_PID_QUERY_OK$' <<< "$query" | tr -d '[:space:]')" ]]; then
      return 0
    fi
    sleep 0.25
  done
  echo "Mirishita is still running. Settings have not been applied." >&2
  return 4
}

try_rts_fast_refresh() {
  local helper="$(dirname "$0")/rts-fast-state.py" old_config actual i
  LC_ALL=C waydroid status | grep -Eq 'Session:[[:space:]]*RUNNING' || return 10
  [[ "$(backend)" != gamescope || "$(saved_render_mode)" == rtscale ]] || return 10
  display_exit_status >/dev/null 2>&1 || return 10
  python "$helper" check || return 10
  old_config="${XDG_STATE_HOME:-$HOME/.local/state}/mwm/rts-fast-config.txt"
  [[ -f "$old_config" ]] || return 10
  actual="$(root_helper rtscale-read)" || return 10
  [[ "$actual" == "$(cat "$old_config")" ]] || return 10
  stop_mirishita_for_refresh || return $?
  printf '%s RTScale fast Refresh started\n' "$(date --iso-8601=ns)" >> "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-events.log"
  refresh_phase "Applying RTScale multiplier..."
  # Do not stop Android/compositor. Refuse early launch throughout the write.
  export MWM_REFRESH_GUARD_FILE
  MWM_REFRESH_GUARD_FILE="$(mktemp "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-guard.XXXXXXXX")" || return 4
  : > "$MWM_REFRESH_GUARD_FILE.ready"
  (while [[ -f "$MWM_REFRESH_GUARD_FILE" ]]; do refresh_guard >/dev/null 2>&1 || break; sleep 0.25; done) 8>&- 7>&- &
  MWM_GUARD_PID=$!
  trap 'kill "$MWM_GUARD_PID" 2>/dev/null || true; wait "$MWM_GUARD_PID" 2>/dev/null || true; rm -f "$MWM_REFRESH_GUARD_FILE" "$MWM_REFRESH_GUARD_FILE.ready"' EXIT
  refresh_guard || return $?
  "$(dirname "$0")/set-rtscale.sh" "$(saved_scale)" || return 5
  for i in {1..6}; do
    refresh_guard || return $?
    display_exit_status || return $?
    LC_ALL=C waydroid status | grep -Eq 'Session:[[:space:]]*RUNNING' || return 4
    sleep 0.5
  done
  refresh_guard || return $?
  python "$helper" check || return 4
  save_rts_fast_state
  echo "RTScale: fast refresh complete / Android and compositor restart skipped"
  kill "$MWM_GUARD_PID" 2>/dev/null || true
  wait "$MWM_GUARD_PID" 2>/dev/null || true
  rm -f "$MWM_REFRESH_GUARD_FILE" "$MWM_REFRESH_GUARD_FILE.ready"
  unset MWM_REFRESH_GUARD_FILE
  trap - EXIT
  if [[ "$(cat "$CFG_DIR/auto-start-mirishita" 2>/dev/null || echo on)" == on ]]; then
    auto_start_after_refresh || return $?
  fi
  echo "Refreshed / backend=$(backend)"
  refresh_phase "Ready"
  return 0
}
save_rts_fast_state() {
  local state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
  rm -f "$state/rts-fast-state.json" "$state/rts-fast-config.txt"
  root_helper rtscale-read > "$state/rts-fast-config.txt" &&
    python "$(dirname "$0")/rts-fast-state.py" save || {
      rm -f "$state/rts-fast-state.json" "$state/rts-fast-config.txt"
      echo "[INFO] The next Refresh will use normal startup verification."
    }
}

start_all() {
  require_waydroid_initialized
  local b mode render_snapshot
  b="$(backend)"
  printf '%s Refresh started\n' "$(date --iso-8601=ns)" >> "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-events.log"
  export MWM_REFRESH_GUARD_FILE
  # Operation locks are held here; previous abandoned watch files can go.
  find "${XDG_STATE_HOME:-$HOME/.local/state}/mwm" -maxdepth 1 -type f -name 'refresh-guard.*' -delete
  MWM_REFRESH_GUARD_FILE="$(mktemp "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-guard.XXXXXXXX")"
  # Watch in parallel, including startup and long display queries.
  (
    while [[ -f "$MWM_REFRESH_GUARD_FILE" ]]; do
      refresh_guard >/dev/null 2>&1 || break
      sleep 0.25
    done
  ) 8>&- 7>&- &
  MWM_GUARD_PID=$!
  trap 'kill "$MWM_GUARD_PID" 2>/dev/null || true; wait "$MWM_GUARD_PID" 2>/dev/null || true; rm -f "$MWM_REFRESH_GUARD_FILE" "$MWM_REFRESH_GUARD_FILE.ready"' EXIT
  mode="${MWM_ASPECT_MODE_OVERRIDE:-$(cat "$CFG_DIR/aspect-ratio" 2>/dev/null || echo auto)}"
  # Keep settings fixed across compositor startup and Android post-boot setup.
  # Another open MWM window must not switch the profile mid-Refresh.
  local auto_start
  auto_start="$(cat "$CFG_DIR/auto-start-mirishita" 2>/dev/null || echo on)"
  case "$auto_start" in on|off) ;; *) echo "Invalid auto-launch setting" >&2; return 2;; esac
  render_snapshot="$(saved_render_mode)"
  export MWM_ASPECT_MODE_OVERRIDE="$mode"
  export MWM_BACKEND_OVERRIDE="$b"
  export MWM_RENDER_MODE_OVERRIDE="$render_snapshot"

  "$RTSCALE_DEBUG_CTL" event refresh-start >/dev/null 2>&1 || true

  # Apply the saved display profile before creating the Gamescope session.
  "$(dirname "$0")/set-aspect-ratio.sh" "$mode" --prepare >/tmp/mwm-aspect-prestart.log 2>&1 || {
    cat /tmp/mwm-aspect-prestart.log >&2 || true
    "$RTSCALE_DEBUG_CTL" event display-config-failed >/dev/null 2>&1 || true
    return 4
  }
  "$RTSCALE_DEBUG_CTL" event display-configured >/dev/null 2>&1 || true


  refresh_phase "Starting Waydroid..."
  root_helper container-start || return $?
  start_display_session || {
    echo "Display session start failed / backend=$b" >&2
    stop_display_session >/dev/null 2>&1 || true
    root_helper container-stop >/dev/null 2>&1 || true
    return 4
  }

  local boot_rc=0
  refresh_phase "Waiting for Android..."
  wait_runtime_boot || boot_rc=$?
  if (( boot_rc != 0 && boot_rc != 3 )); then return "$boot_rc"; fi
  if (( boot_rc == 0 )); then
    : > "$MWM_REFRESH_GUARD_FILE.ready"
    local apply_rc=0
    refresh_phase "Applying settings..."
    apply_runtime_after_boot "$b" || apply_rc=$?
    refresh_guard || return $?
    if (( apply_rc == 42 )); then
      if [[ "${MWM_DISPLAY_RETRY:-0}" == 1 ]]; then
        echo "Android display remains stale after rebuilding; restart aborted." >&2
        return 4
      fi
      echo "Android retained its old display. Rebuilding once with saved ${mode} settings..."
      stop_all_verified || return $?
      kill "$MWM_GUARD_PID" 2>/dev/null || true
      wait "$MWM_GUARD_PID" 2>/dev/null || true
      rm -f "$MWM_REFRESH_GUARD_FILE" "$MWM_REFRESH_GUARD_FILE.ready"
      MWM_DISPLAY_RETRY=1 start_all
      return $?
    fi
    (( apply_rc == 0 )) || return "$apply_rc"
    "$RTSCALE_DEBUG_CTL" event runtime-applied >/dev/null 2>&1 || true
    # Leave Android on its home screen. The game is launched manually.
    # Do not run launch_mirishita/post_launch_assists in this path.
    display_exit_status || return $?
    refresh_guard || return $?
    refresh_phase "Checking display and session..."
    local observation
    for observation in {1..6}; do
      refresh_guard || return $?
      display_exit_status || return $?
      if [[ -f "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/mangoapp-failed" && "$observation" == 1 ]]; then
        # An optional counter failure must not tear down a healthy game session.
        echo "[WARN] MangoApp reported a failure; display startup will continue. Check gamescope.log if the counter is missing." >&2
      fi
      if ! LC_ALL=C waydroid status | grep -Eq 'Session:[[:space:]]*RUNNING'; then
        echo "Waydroid session stopped during preparation." >&2
        return 4
      fi
      sleep 0.5
    done
    refresh_guard || return $?
    display_exit_status || return $?
    printf '%s Settings applied and display ready\n' "$(date --iso-8601=ns)" >> "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/refresh-events.log"
    echo "Waydroid: READY / settings applied"
    python "$(dirname "$0")/performance-overlay.py" sync 8>&- 7>&- || echo "[WARN] FPS Counter could not be applied" >&2
    refresh_guard || return $?
    kill "$MWM_GUARD_PID" 2>/dev/null || true
    wait "$MWM_GUARD_PID" 2>/dev/null || true
    rm -f "$MWM_REFRESH_GUARD_FILE" "$MWM_REFRESH_GUARD_FILE.ready"
    unset MWM_REFRESH_GUARD_FILE
    trap - EXIT
    display_exit_status || return $?
    save_rts_fast_state
    if [[ "$auto_start" == on ]]; then
      auto_start_after_refresh || return $?
    else
      echo "Launch Mirishita manually from the Android home screen."
    fi
    refresh_phase "Ready"
    # One full diagnostic snapshot per successful Refresh is enough for useful
    # post-mortem data without a 1 Hz background monitor.
    (sleep 2; "$RTSCALE_DEBUG_CTL" snapshot waydroid-ready >/dev/null 2>&1 || true) 8>&- 7>&- &
  else
    echo "Waydroid boot timeout / backend=$b" >&2
    [[ "$b" == gamescope ]] && echo "Gamescope log: $($GAMESCOPE_CTL log 2>/dev/null || true)" >&2
    return 3
  fi
}


restart_without_verification() {
  # Expert/testing mode: pressing Refresh ends the current managed display.
  # Do not wait for the game to exit or invoke full container rebuild checks.
  export MWM_SKIP_STARTUP_VERIFICATION=1
  unset MWM_REFRESH_GUARD_FILE
  "$GAMESCOPE_CTL" stop || return $?
  timeout --kill-after=2 10 waydroid session stop || {
    echo "Waydroid session stop failed; restart aborted." >&2; return 4;
  }
  python "$(dirname "$0")/performance-overlay.py" stop || true
  local state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
  rm -f "$state/rts-fast-state.json" "$state/rts-fast-config.txt"
  export MWM_BACKEND_OVERRIDE=gamescope
  export MWM_RENDER_MODE_OVERRIDE="$(saved_render_mode)"
  export MWM_ASPECT_MODE_OVERRIDE="$(cat "$CFG_DIR/aspect-ratio" 2>/dev/null || echo auto)"
  refresh_phase "Starting Waydroid..."
  root_helper container-start || return $?
  start_display_session || return $?
  refresh_phase "Applying settings..."
  wait_runtime_boot || return $?
  apply_runtime_after_boot gamescope || return $?
  python "$(dirname "$0")/performance-overlay.py" sync 8>&- 7>&- || echo "[WARN] FPS Counter could not be applied" >&2
  echo "Waydroid: settings applied / startup verification skipped / manual game launch"
  refresh_phase "Settings applied"
  return 0
}

case "$ACTION" in
  start|stop|restart|launch)
    mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
    exec 8>"${XDG_STATE_HOME:-$HOME/.local/state}/mwm/waydroid-control.lock"
    mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}"
    exec 7>"${XDG_CONFIG_HOME:-$HOME/.config}/mwm-config.lock"
    flock -n 7 || { echo "Settings are being saved or updated. Try again when complete." >&2; exit 75; }
    [[ ! -d "${XDG_CONFIG_HOME:-$HOME/.config}/mwm-config.previous" ]] || { echo "A previous settings save was interrupted. Settings recovery is required." >&2; exit 78; }
    flock -n 8 || { echo "Waydroid operation already in progress" >&2; exit 75; }
    if [[ -f "${XDG_STATE_HOME:-$HOME/.local/state}/mwm-lite/restore.json" ]]; then
      echo "MWM Lite recovery is pending. Run mwm-lite --recover before Desktop operations." >&2
      exit 78
    fi
    ;;
esac
case "$ACTION" in
  status) status_waydroid ;;
  start)
    require_waydroid_initialized
    refresh_phase "Stopping the existing session..."
    stop_all_verified || exit $?
    start_all || exit $?
    echo "Started / backend=$(backend)"
    ;;
  stop)
    python "$(dirname "$0")/performance-overlay.py" stop || true
    if waydroid_initialized; then
      stop_display_session
      root_helper container-stop >/dev/null 2>&1 || true
    fi
    "$RTSCALE_DEBUG_CTL" event stopped >/dev/null 2>&1 || true
    echo "Stopped"
    ;;
  restart)
    verify="$(cat "$CFG_DIR/verify-waydroid-startup" 2>/dev/null || echo on)"
    case "$verify" in on|off) ;; *) echo "Invalid startup verification setting" >&2; exit 2;; esac
    require_waydroid_initialized
    if [[ "$verify" == off ]]; then
      restart_without_verification || exit $?
      echo "Restarted / backend=$(backend)"
      exit 0
    fi
    fast_rc=0
    try_rts_fast_refresh || fast_rc=$?
    if (( fast_rc == 0 )); then exit 0; fi
    if (( fast_rc != 10 )); then exit "$fast_rc"; fi
    rm -f "${XDG_STATE_HOME:-$HOME/.local/state}/mwm/rts-fast-state.json"
    refresh_phase "Stopping the existing session..."
    stop_all_verified || exit $?
    start_all || exit $?
    echo "Restarted / backend=$(backend)"
    ;;
  launch)
    require_waydroid_initialized
    launch_mirishita
    ;;
  *) echo "usage: $0 start|stop|restart|status|launch" >&2; exit 2 ;;
esac

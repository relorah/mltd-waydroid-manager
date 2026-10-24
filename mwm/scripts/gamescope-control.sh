#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MWM_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
PID_FILE="$STATE_DIR/gamescope.pid"
METRICS_PID_FILE="$STATE_DIR/gamescope-metrics.pid"
LOG_FILE="$STATE_DIR/gamescope.log"
SESSION_FILE="$STATE_DIR/gamescope-session.env"
EXIT_FILE="$STATE_DIR/gamescope-exit-code"
IDENTITY_FILE="$STATE_DIR/gamescope-start-time"
# Serialize mutations. Background sessions must not inherit this lock.
case "${1:-status}" in
  start|stop|restart)
    mkdir -p "$STATE_DIR"
    exec 9>"$STATE_DIR/gamescope-control.lock"
    flock -n 9 || { echo "Gamescope operation already in progress" >&2; exit 75; }
    ;;
esac
process_start_time() {
  local stat
  [[ "$1" =~ ^[0-9]+$ ]] || return 1
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
  stat="${stat##*) }"
  awk '{print $20}' <<< "$stat"
}
owned_supervisor() {
  local pid expected actual
  pid="$(cat "$PID_FILE" 2>/dev/null)" || return 1
  expected="$(cat "$IDENTITY_FILE" 2>/dev/null)" || return 1
  [[ -n "$expected" ]] || return 1
  actual="$(process_start_time "$pid")" || return 1
  [[ "$actual" == "$expected" ]] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq "$SCRIPT_DIR/gamescope-supervisor.sh"
}
ASPECT_FILE="$CFG_DIR/aspect-ratio"
SHARPNESS_FILE="$CFG_DIR/gamescope-sharpness"
FSR_SHARPNESS_ENABLED_FILE="$CFG_DIR/gamescope-fsr-sharpness-enabled"
FSR_SCALE_FILE="$CFG_DIR/gamescope-fsr-scale"
OVERLAY_MODE_FILE="$CFG_DIR/performance-overlay-mode"
REAL_FPS_FILE="$STATE_DIR/gamescope-real-fps"
FG_FPS_FILE="$STATE_DIR/fg-output-fps"
mkdir -p "$STATE_DIR" "$CFG_DIR"

running() {
  [[ -f "$PID_FILE" && ! -s "$EXIT_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  owned_supervisor && kill -0 "$pid" 2>/dev/null
}

stop_metrics_monitor() {
  if [[ -f "$METRICS_PID_FILE" ]]; then
    local pid
    pid="$(cat "$METRICS_PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] &&
       tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq gamescope-metrics-monitor.py; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$METRICS_PID_FILE" "$REAL_FPS_FILE" "$FG_FPS_FILE"
}

stop_gamescope() {
  stop_metrics_monitor
  if [[ -f "$STATE_DIR/mirishita-launch.log" ]] && (( $(stat -c %s "$STATE_DIR/mirishita-launch.log") > 1048576 )); then
    mv -f "$STATE_DIR/mirishita-launch.log" "$STATE_DIR/mirishita-launch.log.1"
  fi
  current_exit="$(readlink -f "$EXIT_FILE" 2>/dev/null || true)"
  while IFS= read -r -d '' old_exit; do
    [[ "$old_exit" == "$current_exit" ]] || rm -f "$old_exit"
  done < <(find "$STATE_DIR" -maxdepth 1 -type f -name 'gamescope-exit.*' -mtime +7 -print0)
  for extra_log in refresh-events.log gamescope-window-fit.log; do
    if [[ -f "$STATE_DIR/$extra_log" ]] && (( $(stat -c %s "$STATE_DIR/$extra_log") > 1048576 )); then
      mv -f "$STATE_DIR/$extra_log" "$STATE_DIR/$extra_log.1"
    fi
  done
  if owned_supervisor; then
    local pid
    pid="$(cat "$PID_FILE")"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in {1..40}; do owned_supervisor || break; sleep 0.1; done
    if owned_supervisor; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE" "$SESSION_FILE" "$IDENTITY_FILE"
  [[ -s "$EXIT_FILE" ]] || printf '143\n' > "$EXIT_FILE"
}

gamescope_span_enabled() {
  [[ "${XDG_CURRENT_DESKTOP:-}" != *[Gg][Nn][Oo][Mm][Ee]* ]] || return 1
  [[ "$(cat "$CFG_DIR/gamescope-span-enabled" 2>/dev/null || echo off)" == on ]]
}

host_screen_size() {
  if [[ "${1:-}" != primary ]] && gamescope_span_enabled; then
    python "$(dirname "$0")/gamescope_span.py" size
    return $?
  fi
  local out
  out="$(QT_QPA_PLATFORM=wayland python - <<'PY' 2>/dev/null || true
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
s = app.primaryScreen()
if s:
    g = s.geometry()
    print(f"{g.width()} {g.height()}")
PY
)"
  if [[ "$out" =~ ^([0-9]+)[[:space:]]+([0-9]+)$ ]]; then
    printf '%s %s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
  else
    printf '1920 1080\n'
  fi
}

mode_to_internal() {
  local mode="${1:-auto}" sw sh w
  case "$mode" in
    32:9) echo "2560 720" ;;
    21:9) echo "1680 720" ;;
    16:9) echo "1280 720" ;;
    4:3)  echo "960 720" ;;
    3:2)  echo "1080 720" ;;
    *x*)
      if [[ "$mode" =~ ^([0-9]+)x720$ ]]; then echo "${BASH_REMATCH[1]} 720"; else return 2; fi
      ;;
    auto|"")
      read -r sw sh < <(host_screen_size)
      (( sh > 0 )) || sh=1080
      w=$(( (720 * sw + sh / 2) / sh ))
      (( w % 2 == 0 )) || ((w++))
      echo "$w 720"
      ;;
    *) return 2 ;;
  esac
}

read_fsr_scale() {
  local v="125"
  local enabled
  if [[ -f "$CFG_DIR/gamescope-fsr-enabled" ]]; then
    enabled="$(cat "$CFG_DIR/gamescope-fsr-enabled")"
  elif [[ "$(read_render_mode)" == rtscale ]]; then
    enabled="$(cat "$CFG_DIR/gamescope-rtscale-fsr-enabled" 2>/dev/null || echo off)"
  else
    enabled=off
  fi
  enabled="${MWM_FSR_ENABLED_OVERRIDE:-$enabled}"
  [[ "$enabled" == on ]] || { printf '100\n'; return; }
  [[ -f "$FSR_SCALE_FILE" ]] && v="$(tr -d '[:space:]' < "$FSR_SCALE_FILE" 2>/dev/null || true)"
  case "$v" in 125|150|175|200) ;; *) v=125 ;; esac
  printf '%s\n' "$v"
}

read_sharpness_native() {
  local v="10"
  [[ -f "$SHARPNESS_FILE" ]] && v="$(tr -d '[:space:]' < "$SHARPNESS_FILE" 2>/dev/null || true)"
  v="${MWM_FSR_SHARPNESS_OVERRIDE:-$v}"
  [[ "$v" =~ ^([0-9]|1[0-9]|20)$ ]] || v=10
  printf '%s\n' "$v"
}

read_fsr_sharpness_enabled() {
  [[ "$(read_fsr_scale)" != 100 ]] && echo on || echo off
}

read_cas_enabled() { echo off; }
read_cas_strength() {
  local value
  value="$(cat "$CFG_DIR/gamescope-cas-strength" 2>/dev/null || native_to_percent "$(read_sharpness_native)")"
  if [[ "$value" =~ ^[0-9]{1,3}$ ]] && (( 10#$value <= 100 )); then
    printf '%s\n' "$((10#$value))"
  else echo 50; fi
}

gamescope_sharpness_option() {
  local help
  help="$(gamescope --help 2>&1 || true)"
  # Prefer the current generic spelling. Some distro builds only expose the
  # older alias; if neither exists, run FSR without a CLI sharpness override.
  if grep -q -- '--sharpness' <<<"$help"; then
    printf '%s\n' '--sharpness'
  elif grep -q -- '--fsr-sharpness' <<<"$help"; then
    printf '%s\n' '--fsr-sharpness'
  else
    return 1
  fi
}
read_window_mode() {
  # Restore the known-working 0.5.72 Wayland presentation path. Window/fullscreen
  # switching is handled by Super+F after startup, without changing backend.
  echo fullscreen
}

read_fg_mode() {
  # Frame generation controls are temporarily removed pending a separate
  # provider integration; never revive an old saved MAKO selection.
  printf 'off\n'
}

read_render_mode() {
  local value="${MWM_RENDER_MODE_OVERRIDE:-}"
  if [[ -z "$value" ]]; then
    value=fsr
    [[ -f "$CFG_DIR/gamescope-render-mode" ]] && value="$(tr -d '[:space:]' < "$CFG_DIR/gamescope-render-mode" 2>/dev/null || true)"
  fi
  case "$value" in rtscale|fsr) printf '%s\n' "$value" ;; *) printf 'fsr\n' ;; esac
}

read_overlay_mode() {
  local v="off"
  if [[ -f "$OVERLAY_MODE_FILE" ]]; then
    v="$(tr -d '[:space:]' < "$OVERLAY_MODE_FILE" 2>/dev/null || true)"
  elif [[ -f "$CFG_DIR/performance-overlay" ]]; then
    local enabled style
    enabled="$(tr -d '[:space:]' < "$CFG_DIR/performance-overlay" 2>/dev/null || true)"
    style="$(tr -d '[:space:]' < "$CFG_DIR/performance-overlay-style" 2>/dev/null || true)"
    case "$enabled" in off|0|false|no) v=off ;; *) [[ "$style" == graph ]] && v=detailed || v=minimal ;; esac
  fi
  case "$v" in off|minimal|detailed|mangoapp) printf '%s\n' "$v" ;; *) printf 'off\n' ;; esac
}

native_to_percent() {
  local native="$1"
  printf '%s\n' "$(( (20 - native) * 5 ))"
}

scale_even() {
  local value="$1" percent="$2" out
  out=$(( (value * percent + 50) / 100 ))
  (( out % 2 == 0 )) || ((out++))
  printf '%s\n' "$out"
}

write_session() {
  local mode="$1" iw="$2" ih="$3" ow="$4" oh="$5" fsr_scale="$6" sharp_pct="$7" tw="$8" th="$9" pipeline="${10}" fg="${11}" overlay="${12}"
  {
    printf 'mode=%q\n' "$mode"
    printf 'internal_width=%q\n' "$iw"
    printf 'internal_height=%q\n' "$ih"
    printf 'fsr_target_width=%q\n' "$tw"
    printf 'fsr_target_height=%q\n' "$th"
    printf 'output_width=%q\n' "$ow"
    printf 'output_height=%q\n' "$oh"
    printf 'virtual_refresh=120\n'
    if [[ "$fsr_scale" == 100 ]]; then printf 'filter=linear\n'; else printf 'filter=fsr\n'; fi
    printf 'fsr_scale_percent=%q\n' "$fsr_scale"
    printf 'sharpness_percent=%q\n' "$sharp_pct"
    printf 'cas_strength_percent=%q\n' "$(read_cas_strength)"
    printf 'pipeline=%q\n' "$pipeline"
    printf 'frame_generation=%q\n' "$fg"
    case "$pipeline" in cas-direct|fsr-cas-dual) printf 'cas_enabled=on\n' ;; *) printf 'cas_enabled=off\n' ;; esac
    printf 'performance_overlay=%q\n' "$overlay"
    if [[ "$fsr_scale" == 100 ]]; then printf 'fsr1_sharpness_enabled=off\n'; else printf 'fsr1_sharpness_enabled=%q\n' "$(read_fsr_sharpness_enabled)"; fi
    printf 'presentation_backend=%q\n' "$(outer_backend "$fg")"
    printf 'window_mode=%q\n' "$(read_window_mode)"
    printf 'render_mode=%q\n' "$(read_render_mode)"
  } > "$SESSION_FILE"
}


launch_outer() {
  local fg="$1" overlay="$2"; shift 2
  local -a command=("$@")
  if [[ "${MWM_GAMESCOPE_STATS_PATH:-}" == /* ]]; then
    [[ -e "$MWM_GAMESCOPE_STATS_PATH" ]] || : > "$MWM_GAMESCOPE_STATS_PATH"
    command=("${command[0]}" --stats-path "$MWM_GAMESCOPE_STATS_PATH" "${command[@]:1}")
  fi
  # Wrap only the outer child: its socket belongs to the final canvas.
  local screenshot_index
  for screenshot_index in "${!command[@]}"; do
    if [[ "${command[$screenshot_index]}" == -- ]]; then
      screenshot_index=$((screenshot_index + 1))
      command=("${command[@]:0:screenshot_index}" bash "$SCRIPT_DIR/screenshot-child.sh" "${command[@]:screenshot_index}")
      break
    fi
  done
  # Keep MAKO scoped to the outer Gamescope process and clear inherited profile
  # overrides so nested children cannot accidentally enable it.
  local -a env_args=(-u MANGOHUD -u MANGOHUD_CONFIG -u MANGOAPP_MSG_TYPE -u MAKO_ENV -u MAKO_PROFILE -u DISABLE_MAKO
    "SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0" "SDL_VIDEODRIVER=wayland" "SDL_VIDEO_WAYLAND_WMCLASS=mwm-gamescope" "SDL_APP_ID=mwm-gamescope")

  # Span uses the same native Wayland startup as a single display, then the
  # KWin fitter expands the borderless window after the compositor is ready.
  rm -f "$STATE_DIR/mangoapp-active" "$STATE_DIR/mangoapp-failed"
  local mango=off real_candidate
  # MWM HUD modes do not need a second overlay process. Hidden MangoApp
  # can repeatedly fail in the host X11 initialization path.
  if [[ "$overlay" == mangoapp || "${MWM_KEEP_HIDDEN_MANGOAPP:-off}" == on ]]; then
    real_candidate="$(command -v mangoapp 2>/dev/null || true)"
    if [[ -f "$SCRIPT_DIR/mangoapp-runtime.py" ]]; then
      real_candidate="$(python3 "$SCRIPT_DIR/mangoapp-runtime.py" mangoapp 2>/dev/null || true)"
    fi
    if [[ -n "$real_candidate" ]] && grep -q -- '--mangoapp' <<< "$(gamescope --help 2>&1)"; then
      mango=on
    else
      echo "[WARN] MangoApp unavailable; continuing without MangoApp (GNOME: select Off)." >> "$LOG_FILE"
    fi
  fi
  case "$mango" in on|off) ;; *) echo "Invalid MangoApp setting" >&2; return 2;; esac
  if [[ "$mango" == on ]]; then
    local real_mango
    real_mango="$real_candidate"
    grep -q -- '--mangoapp' <<< "$(gamescope --help 2>&1)" || { echo "Gamescope lacks --mangoapp support" >&2; return 2; }
    # Attach after the MWM client display exists via performance-overlay.py.
    # The host Gamescope can bypass our PATH wrapper for --mangoapp, losing
    # the FPS collector and the bundled integer-alignment implementation.
    env_args+=("MWM_REAL_MANGOAPP=$real_mango" "PATH=$SCRIPT_DIR/mangoapp-bin:$PATH"
      "MANGOHUD_CONFIG=position=top-left,fps,frametime=0,frame_timing,cpu_stats,gpu_stats,cpu_temp,gpu_temp,font_size=29,height=200,width=285,background_alpha=0.6")
    printf "on\n" > "$STATE_DIR/mangoapp-active"
    echo "MangoApp: deferred attach / nearest Waydroid compositor / X11 overlay" >> "$LOG_FILE"
  fi
  setsid "$SCRIPT_DIR/gamescope-supervisor.sh" "$RUN_EXIT_FILE" env "${env_args[@]}" DISABLE_MAKO=1 "${command[@]}" >>"$LOG_FILE" 2>&1 </dev/null 9>&- 8>&- 7>&- &
}

outer_backend() {
  # Native Wayland presents dmabufs, bypassing MAKO's Vulkan swapchain hooks.
  # SDL is the workaround candidate for native-Wayland windowed surface loss.
  if [[ "$1" != off || "$(read_window_mode)" == windowed ]]; then
    echo sdl
  else
    echo wayland
  fi
}

# Request a 120 Hz virtual mode in both layers, independently of host Hz.
start_no_fsr() {
  local mode="$1" iw="$2" ih="$3" ow="$4" oh="$5" fg="$6" overlay="$7"
  local sharp_pct=0 pipeline=linear-direct cas_status=OFF
  local -a args=(
    gamescope --backend "$(outer_backend "$fg")" --expose-wayland --keep-alive --force-windows-fullscreen
    -w "$iw" -h "$ih" -W "$ow" -H "$oh" -r 120 -S fit -F linear
  )
  if [[ "$(read_window_mode)" == fullscreen ]]; then args+=(-f); else args+=(-b); fi
  args+=(-- env DISABLE_MAKO=1 DISABLE_GAMESCOPE_WSI=1 ENABLE_GAMESCOPE_WSI=0 bash "$SCRIPT_DIR/gamescope-client.sh")
  write_session "$mode" "$iw" "$ih" "$ow" "$oh" 100 "$sharp_pct" "$iw" "$ih" "$pipeline" "$fg" "$overlay"
  : > "$LOG_FILE"
  {
    printf 'MWM 100%%: FSR OFF / CAS %s / linear fit / source %sx%s / output %sx%s / FG %s\n' "$cas_status" "$iw" "$ih" "$ow" "$oh" "$fg"
    printf '  COMMAND:'; printf ' %q' "${args[@]}"; printf '\n'
  } >> "$LOG_FILE"
  launch_outer "$fg" "$overlay" "${args[@]}"
}

start_fsr_150() {
  local mode="$1" iw="$2" ih="$3" ow="$4" oh="$5" native_sharpness="$6" sharp_pct="$7" fg="$8" overlay="$9"
  local tw th sharp_opt
  tw="$(scale_even "$iw" 150)"; th="$(scale_even "$ih" 150)"
  sharp_opt="$(gamescope_sharpness_option 2>/dev/null || true)"

  local -a args=(
    gamescope --backend "$(outer_backend "$fg")" --expose-wayland --keep-alive --force-windows-fullscreen
    -w "$iw" -h "$ih" -W "$ow" -H "$oh" -r 120 -S fit -F fsr
  )
  # Apply the selected native RCAS strength (0=max, 20=min).
  if [[ -n "$sharp_opt" ]]; then
    if [[ "$(read_fsr_sharpness_enabled)" == on ]]; then
      args+=("$sharp_opt" "$native_sharpness")
    else
      args+=("$sharp_opt" 20)
    fi
  fi
  if [[ "$(read_window_mode)" == fullscreen ]]; then args+=(-f); else args+=(-b); fi
  args+=(-- env DISABLE_MAKO=1 DISABLE_GAMESCOPE_WSI=1 ENABLE_GAMESCOPE_WSI=0 bash "$SCRIPT_DIR/gamescope-client.sh")

  write_session "$mode" "$iw" "$ih" "$ow" "$oh" 150 "$sharp_pct" "$tw" "$th" fsr-direct "$fg" "$overlay"
  : > "$LOG_FILE"
  {
    printf 'gamescope: '; gamescope --version 2>&1 | head -n1 || true
    printf 'sharpness-option: %s\n' "${sharp_opt:-none}"
    printf 'MWM Gamescope FSR1 150%% direct pipeline:\n'
    printf '  SOURCE: %sx%s\n  DISPLAY: %sx%s\n  FG: %s\n  Overlay: %s\n' "$iw" "$ih" "$ow" "$oh" "$fg" "$overlay"
    printf '  FSR1 sharpness: %s\n  COMMAND:' "$(read_fsr_sharpness_enabled)"; printf ' %q' "${args[@]}"; printf '\n'
  } >> "$LOG_FILE"
  launch_outer "$fg" "$overlay" "${args[@]}"
}

# Diagnostic route: apply FSR once at the final canvas. Fixed intermediate
# percentage is deliberately bypassed only under this explicit override.
start_fsr_direct_diagnostic() {
  local mode="$1" iw="$2" ih="$3" ow="$4" oh="$5" selected="$6" sharp_pct="$7" fg="$8" overlay="$9"
  local sharp_opt native
  sharp_opt="$(gamescope_sharpness_option 2>/dev/null || true)"
  native="$(read_sharpness_native)"
  local -a args=(gamescope --backend "$(outer_backend "$fg")" --expose-wayland --keep-alive --force-windows-fullscreen
    -w "$iw" -h "$ih" -W "$ow" -H "$oh" -r 120 -S fit -F fsr)
  [[ -z "$sharp_opt" ]] || args+=("$sharp_opt" "$native")
  if [[ "$(read_window_mode)" == fullscreen ]]; then args+=(-f); else args+=(-b); fi
  args+=(-- env DISABLE_MAKO=1 DISABLE_GAMESCOPE_WSI=1 ENABLE_GAMESCOPE_WSI=0 bash "$SCRIPT_DIR/gamescope-client.sh")
  write_session "$mode" "$iw" "$ih" "$ow" "$oh" "$selected" "$sharp_pct" "$ow" "$oh" fsr-direct-diagnostic "$fg" "$overlay"
  : > "$LOG_FILE"
  { printf 'Experimental FSR directly to final canvas; selected intermediate percentage %s is bypassed.\n' "$selected"
    printf '  COMMAND:'; printf ' %q' "${args[@]}"; printf '\n'; } >> "$LOG_FILE"
  launch_outer "$fg" "$overlay" "${args[@]}"
}

start_fsr_scaled() {
  if [[ "${MWM_FSR_PIPELINE:-}" == direct ]]; then
    start_fsr_direct_diagnostic "$@"
    return $?
  fi
  local mode="$1" iw="$2" ih="$3" ow="$4" oh="$5" fsr_scale="$6" sharp_pct="$7" fg="$8" overlay="$9"
  local tw th sharp_opt fsr_native=20 cas_enabled=off pipeline=fsr-dual cas_status=OFF inner_filter=fsr
  if [[ "$fsr_scale" == 100 ]]; then inner_filter=linear; pipeline=bezel-dual; fi
  if [[ "$(read_fsr_sharpness_enabled)" == on ]]; then
    fsr_native="$(read_sharpness_native)"
  fi
  tw="$(scale_even "$iw" "$fsr_scale")"; th="$(scale_even "$ih" "$fsr_scale")"
  sharp_opt="$(gamescope_sharpness_option 2>/dev/null || true)"

  # FSR upscale followed by linear fit; no additional CAS stage. Remove
  # the intermediate linear Gamescope that made the old three-layer chain
  # lose its surface. The inner SDL stage uses the outer Xwayland display;
  # this avoids relying on Wayland protocols in the nested compositor.
  local -a outer=(
    gamescope --backend "$(outer_backend "$fg")" --expose-wayland --keep-alive --force-windows-fullscreen
    -w "$tw" -h "$th" -W "$ow" -H "$oh" -r 120 -S fit -F linear
  )
  if [[ "$(read_window_mode)" == fullscreen ]]; then outer+=(-f); else outer+=(-b); fi
  outer+=(-- env SDL_VIDEODRIVER=x11 DISABLE_MAKO=1 DISABLE_GAMESCOPE_WSI=1 ENABLE_GAMESCOPE_WSI=0 bash -c 'export WAYLAND_DISPLAY="${GAMESCOPE_WAYLAND_DISPLAY:?Outer Gamescope Wayland socket unavailable}"; exec gamescope "$@"' mwm-inner)
  local -a inner=(
    --backend sdl --expose-wayland --keep-alive --force-windows-fullscreen
    -w "$iw" -h "$ih" -W "$tw" -H "$th" -r 120 -S fit -F "$inner_filter"
  )
  [[ -n "$sharp_opt" ]] && inner+=("$sharp_opt" "$fsr_native")
  # Host fullscreen belongs to the outer compositor. The outer
  # --force-windows-fullscreen already fills its nested display; requesting a
  # second fullscreen acquisition inside can strand this Wayland surface.
  inner+=( --
    env DISABLE_MAKO=1 DISABLE_GAMESCOPE_WSI=1 ENABLE_GAMESCOPE_WSI=0 bash "$SCRIPT_DIR/gamescope-client.sh"
  )
  local -a full=("${outer[@]}" "${inner[@]}")

  write_session "$mode" "$iw" "$ih" "$ow" "$oh" "$fsr_scale" "$sharp_pct" "$tw" "$th" "$pipeline" "$fg" "$overlay"
  : > "$LOG_FILE"
  {
    printf 'gamescope: '; gamescope --version 2>&1 | head -n1 || true
    printf 'sharpness-option: %s\n' "${sharp_opt:-none}"
    printf 'MWM Gamescope dual-layer pipeline (FSR1 -> linear fit, CAS %s):\n' "$cas_status"
    printf '  SOURCE: %sx%s\n  FSR1 %s%% target: %sx%s\n  DISPLAY: %sx%s\n  CAS: %s\n  FSR1 sharpness: native %s (0=max, 20=min)\n  FG: %s\n  Overlay: %s\n' \
      "$iw" "$ih" "$fsr_scale" "$tw" "$th" "$ow" "$oh" "$cas_status" "$fsr_native" "$fg" "$overlay"
    printf '  COMMAND:'; printf ' %q' "${full[@]}"; printf '\n'
  } >> "$LOG_FILE"
  launch_outer "$fg" "$overlay" "${full[@]}"
}

start_gamescope() {
  command -v gamescope >/dev/null 2>&1 || { echo "Gamescope backend requested but gamescope is not installed." >&2; return 127; }
  stop_gamescope
  # Preserve recent attempts before start_fsr_* truncates the active log.
  for n in 3 2 1; do
    [[ ! -f "$LOG_FILE.$n" ]] || mv -f "$LOG_FILE.$n" "$LOG_FILE.$((n+1))"
  done
  [[ ! -f "$LOG_FILE" ]] || cp -f "$LOG_FILE" "$LOG_FILE.1"
  rm -f "$LOG_FILE.4"
  rm -f "$EXIT_FILE"
  RUN_EXIT_FILE="$(mktemp "$STATE_DIR/gamescope-exit.XXXXXXXX")"
  ln -s "${RUN_EXIT_FILE##*/}" "$EXIT_FILE"

  rm -f "$STATE_DIR/gamescope-span-layout.json"
  if gamescope_span_enabled; then
    python "$SCRIPT_DIR/gamescope_span.py" snapshot >/dev/null || return 4
  fi
  local mode="auto" iw ih ow oh fsr_scale native_sharpness sharp_pct fg overlay render_mode
  [[ -f "$ASPECT_FILE" ]] && mode="$(tr -d '[:space:]' < "$ASPECT_FILE" 2>/dev/null || true)"
  [[ -z "${MWM_ASPECT_MODE_OVERRIDE:-}" ]] || mode="$MWM_ASPECT_MODE_OVERRIDE"
  [[ -n "$mode" ]] || mode=auto
  read -r iw ih < <(mode_to_internal "$mode")
  read -r ow oh < <(host_screen_size primary)
  render_mode="$(read_render_mode)"
  fsr_scale="$(read_fsr_scale)"
  if [[ "$render_mode" == rtscale ]]; then
    # Preserve the proven 1080p Waydroid presentation for RTScale. Its render
    # target matching base remains 720-high; it is not the display surface.
    iw="$(scale_even "$iw" 150)"; ih=1080
  fi
  native_sharpness="$(read_sharpness_native)"
  sharp_pct="$(native_to_percent "$native_sharpness")"
  fg="$(read_fg_mode)"
  overlay="$(read_overlay_mode)"

  printf '0.00\n' > "$REAL_FPS_FILE"
  printf '0.00\n' > "$FG_FPS_FILE"
  case "$fsr_scale" in
    100)
      if [[ "$(cat "$CFG_DIR/bezel-compensation-enabled" 2>/dev/null)" == on && "$(cat "$CFG_DIR/gamescope-span-enabled" 2>/dev/null)" == on ]]; then
        start_fsr_scaled "$mode" "$iw" "$ih" "$ow" "$oh" 100 "$sharp_pct" "$fg" "$overlay" || return $?
      else
        start_no_fsr "$mode" "$iw" "$ih" "$ow" "$oh" "$fg" "$overlay" || return $?
      fi ;;
    150)
      if [[ "$render_mode" == rtscale || "$(read_cas_enabled)" == on || "$(cat "$CFG_DIR/bezel-compensation-enabled" 2>/dev/null)" == on ]]; then
        start_fsr_scaled "$mode" "$iw" "$ih" "$ow" "$oh" 150 "$sharp_pct" "$fg" "$overlay" || return $?
      else
        start_fsr_150 "$mode" "$iw" "$ih" "$ow" "$oh" "$native_sharpness" "$sharp_pct" "$fg" "$overlay" || return $?
      fi ;;

    125|175|200) start_fsr_scaled "$mode" "$iw" "$ih" "$ow" "$oh" "$fsr_scale" "$sharp_pct" "$fg" "$overlay" || return $? ;;
    *) echo "Unsupported FSR scale: $fsr_scale" >&2; return 2 ;;
  esac

  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  process_start_time "$pid" > "$IDENTITY_FILE" || true
  sleep 1
  if ! running; then
    rm -f "$PID_FILE" "$SESSION_FILE"
    if [[ "$(cat "$EXIT_FILE" 2>/dev/null || true)" == 0 ]]; then
      echo "Gamescope was closed during startup."
      return 130
    fi
    echo "Gamescope exited during startup. Recent log:" >&2
    tail -100 "$LOG_FILE" >&2 || true
    return 1
  fi
  local -a fit_args=()
  if gamescope_span_enabled; then fit_args+=(--span-layout "$STATE_DIR/gamescope-span-layout.json"); fi
  setsid python3 "$SCRIPT_DIR/gamescope-window-fit.py" "${fit_args[@]}" --pid "$pid" --width "$iw" --height "$ih" >>"$STATE_DIR/gamescope-window-fit.log" 2>&1 </dev/null 9>&- 8>&- 7>&- &

  if [[ "$fsr_scale" == 100 ]]; then
    if [[ "$render_mode" == rtscale ]]; then
      printf 'Gamescope + RTScale: ON / x%s / linear presentation / source %sx%s / output %sx%s / FG off / Overlay %s\n' "$(cat "$CFG_DIR/kwin-rtscale" 2>/dev/null || echo 3)" "$iw" "$ih" "$ow" "$oh" "$overlay"
    else
      printf 'Gamescope: ON / 100%% FSR OFF / CAS %s / linear fit / source %sx%s / output %sx%s / FG off / Overlay %s\n' "$(read_cas_enabled)" "$iw" "$ih" "$ow" "$oh" "$overlay"
    fi
    return 0
  fi
  [[ "$render_mode" != rtscale ]] || printf 'RTScale x%s + ' "$(cat "$CFG_DIR/kwin-rtscale" 2>/dev/null || echo 3)"
  printf 'Gamescope + FSR1: ON / FSR1 %s%% / source %sx%s / output %sx%s / FSR1 sharpness %s / FG off / Overlay %s\n' \
    "$fsr_scale" "$iw" "$ih" "$ow" "$oh" "$(read_fsr_sharpness_enabled)" "$overlay"
}

start_bezel_controller() {
  if running; then
    python3 "$SCRIPT_DIR/bezel-control.py" "$(cat "$PID_FILE")" >>"$STATE_DIR/bezel.log" 2>&1 9>&- &
  fi
}

case "${1:-status}" in
  start) start_gamescope && start_bezel_controller ;;
  stop) stop_gamescope; echo "Gamescope: OFF" ;;
  restart) stop_gamescope; sleep 0.5; start_gamescope && start_bezel_controller ;;
  status)
    if running; then
      printf 'running pid=%s' "$(cat "$PID_FILE")"
      if [[ -f "$SESSION_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$SESSION_FILE"
        printf ' virtual_refresh=%s' "${virtual_refresh:-unknown}"
        printf ' internal=%sx%s fsr_target=%sx%s output=%sx%s mode=%s fsr=%s%% sharpness=%s%% sharpness_enabled=%s pipeline=%s fg=%s overlay=%s window=%s presentation=%s' \
          "${internal_width:-?}" "${internal_height:-?}" "${fsr_target_width:-?}" "${fsr_target_height:-?}" \
          "${output_width:-?}" "${output_height:-?}" "${mode:-?}" "${fsr_scale_percent:-?}" \
          "${sharpness_percent:-?}" "${fsr1_sharpness_enabled:-off}" "${pipeline:-?}" "${frame_generation:-off}" "${performance_overlay:-off}" "${window_mode:-unknown}" "${presentation_backend:-unknown}"
      fi
      python3 "$SCRIPT_DIR/gamescope-fps-control.py" --status
      printf '\n'
    else
      echo "stopped"
    fi
    ;;
  exit-code) cat "$EXIT_FILE" 2>/dev/null || echo unknown ;;
  log) printf '%s\n' "$LOG_FILE" ;;
  *) echo "usage: $0 start|stop|restart|status|exit-code|log" >&2; exit 2 ;;
esac

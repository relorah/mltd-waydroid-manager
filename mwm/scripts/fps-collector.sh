#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"

PKG="com.bandainamcoent.imas_millionlive_theaterdays"
INTERVAL="${1:-0.2}"
CACHE_FILE="${2:-}"
CACHE_TMP="${CACHE_FILE:+${CACHE_FILE}.$$}"
if [[ -n "$CACHE_FILE" ]]; then
  mkdir -p "$(dirname "$CACHE_FILE")"
  trap 'rm -f -- "$CACHE_TMP"' EXIT
fi
LAYER=""
LAST_TS=""
STALE_COUNT=0

rh() {
  root_helper "$@" 2>/dev/null | tr -d '\r'
}

emit_metrics() {
  printf '%s\n' "$1"
  if [[ -n "$CACHE_FILE" ]]; then
    printf '%s\n' "$1" > "$CACHE_TMP"
    mv -f -- "$CACHE_TMP" "$CACHE_FILE"
  fi
}

app_running() {
  [[ -n "$(rh pidof-mirishita || true)" ]]
}

latency_for() {
  local layer="$1"
  rh sf-latency "$layer" || true
}

latest_ts() {
  awk '
    NR == 1 { next }
    $2 ~ /^[0-9]+$/ && $2 > 0 && $2 < 9e18 { last=$2 }
    END { if (last) print last; else print 0 }
  '
}

calc_metrics() {
  # Column 2 is Android actualPresentTime. Column 1 is desiredPresentTime.
  # Ignore unsignaled fences (INT64_MAX) and average at most 30 intervals.
  # Frametime is the latest actual presentation interval, not 1000/average FPS.
  awk '
    NR == 1 { next }
    $2 ~ /^[0-9]+$/ && $2 > 0 && $2 < 9e18 {
      v=$2+0
      if (n == 0 || v > t[n]) t[++n]=v
    }
    END {
      fps=0; ft=0
      if (n >= 2) {
        s=(n > 31 ? n-30 : 1)
        dt=t[n]-t[s]
        frames=n-s
        if (dt > 0 && frames > 0) fps=frames*1000000000/dt
        lastdt=t[n]-t[n-1]
        if (lastdt > 0) ft=lastdt/1000000
      }
      if (fps <= 0 || fps > 240) fps=0
      if (ft <= 0 || ft > 1000) ft=0
      printf "%.2f %.2f\n", fps, ft
    }
  '
}

find_layer() {
  local best="" best_ts=0 layer out ts
  while IFS= read -r layer; do
    [[ "$layer" == *"$PKG"* && "$layer" == *"TID:"* ]] || continue
    out="$(latency_for "$layer")"
    ts="$(printf '%s\n' "$out" | latest_ts)"
    [[ "$ts" =~ ^[0-9]+$ ]] || ts=0
    if (( ts > best_ts )); then
      best_ts="$ts"
      best="$layer"
    fi
  done < <(rh sf-list || true)
  printf '%s\n' "$best"
}

while true; do
  # An attached but hidden MangoApp must not duplicate the MWM HUD collector.
  if [[ -n "$CACHE_FILE" ]] && [[ "$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/mwm/performance-overlay-mode" 2>/dev/null || true)" != mangoapp ]]; then
    emit_metrics '0.00 0.00'
    sleep "$INTERVAL"
    continue
  fi
  # Reuse the session controller's sample instead of querying SurfaceFlinger
  # twice. If it is stopped or stale, retain the existing independent path.
  shared="${XDG_STATE_HOME:-$HOME/.local/state}/mwm/gamescope-fps-sample"
  if [[ "${MWM_FPS_SOURCE_OWNER:-0}" != 1 && -r "$shared" ]]; then
    shared_fps= shared_ft= shared_time= shared_pid=
    read -r shared_fps shared_ft shared_time shared_pid < "$shared" || true
    if [[ "$shared_fps" =~ ^[0-9]+\.[0-9]+$ && "$shared_ft" =~ ^[0-9]+\.[0-9]+$ && "$shared_time" =~ ^[0-9]{10}$ && "$shared_pid" =~ ^[0-9]+$ ]] &&
       (( EPOCHSECONDS >= shared_time && EPOCHSECONDS - shared_time <= 1 )) && kill -0 "$shared_pid" 2>/dev/null; then
      emit_metrics "$shared_fps $shared_ft"
      sleep "$INTERVAL"
      continue
    fi
  fi
  if ! app_running; then
    LAYER=""; LAST_TS=""; STALE_COUNT=0
    emit_metrics '0.00 0.00'
    sleep "$INTERVAL"
    continue
  fi

  if [[ -z "$LAYER" ]]; then
    LAYER="$(find_layer)"
    LAST_TS=""; STALE_COUNT=0
    if [[ -z "$LAYER" ]]; then
      emit_metrics '0.00 0.00'
      sleep "$INTERVAL"
      continue
    fi
  fi

  OUT="$(latency_for "$LAYER")"
  TS="$(printf '%s\n' "$OUT" | latest_ts)"
  METRICS="$(printf '%s\n' "$OUT" | calc_metrics)"

  if [[ "$TS" == "0" || -z "$TS" ]]; then
    LAYER=""; LAST_TS=""; STALE_COUNT=0
    emit_metrics '0.00 0.00'
    sleep "$INTERVAL"
    continue
  fi

  if [[ -n "$LAST_TS" && "$TS" == "$LAST_TS" ]]; then
    STALE_COUNT=$((STALE_COUNT + 1))
  else
    STALE_COUNT=0
  fi
  LAST_TS="$TS"

  if (( STALE_COUNT >= 2 )); then
    LAYER=""; LAST_TS=""; STALE_COUNT=0
    emit_metrics '0.00 0.00'
  else
    emit_metrics "$METRICS"
  fi
  sleep "$INTERVAL"
done

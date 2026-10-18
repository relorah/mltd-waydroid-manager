#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export WAYLAND_DISPLAY="${GAMESCOPE_WAYLAND_DISPLAY:?Gamescope Wayland socket unavailable}"
# Keep the controller as the compositor's primary child, so a Waydroid
# launcher that exits immediately cannot orphan it before owner discovery.
exec python3 "$script_dir/gamescope-fps-control.py" --launch

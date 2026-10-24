#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/mwm"
# Always run the listener so Apply can enable capture in an existing session.
mkdir -p "$state"
python3 "$script_dir/span-screenshot.py" "$$" >>"$state/screenshot.log" 2>&1 &
exec "$@"

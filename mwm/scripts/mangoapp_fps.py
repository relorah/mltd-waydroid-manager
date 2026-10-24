#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Display Android game-layer FPS through MangoApp's external-text element."""
import argparse
import math
import os
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mwm"


def fps_text(cache=None, now=None):
    cache = Path(cache) if cache is not None else STATE / "mirishita-fps"
    now = time.time() if now is None else now
    try:
        with cache.open(encoding="ascii") as stream:
            age = now - os.fstat(stream.fileno()).st_mtime
            values = stream.read().split()
        fps = float(values[0])
        if not (0 <= age <= 2 and math.isfinite(fps) and 0 < fps <= 240):
            return "--.--"
        return f"{fps:.2f}"
    except (OSError, ValueError, IndexError):
        return "--.--"


def ui_scale(session=None):
    """Undo only the outer Gamescope fit; never execute the session file."""
    session = STATE / "gamescope-session.env" if session is None else Path(session)
    try:
        fields = dict(line.split("=", 1) for line in session.read_text().splitlines() if "=" in line)
        if fields.get("pipeline") not in ("fsr-dual", "fsr-cas-dual"):
            return 1.0
        tw, th, ow, oh = (int(fields[key]) for key in
                         ("fsr_target_width", "fsr_target_height", "output_width", "output_height"))
        if not all(0 < value <= 32768 for value in (tw, th, ow, oh)):
            return 1.0
        scale = max(tw / ow, th / oh)
        return scale if 0.125 <= scale <= 8 else 1.0
    except (OSError, ValueError, KeyError):
        return 1.0


def render_config(visible, scale=None):
    text = (ROOT / "config/MangoApp.conf").read_text(encoding="utf-8")
    command = shlex.join(["/bin/bash", str(Path(__file__).resolve().with_name("mangoapp-fps-text.sh"))])
    text = text.replace("@MWM_GAME_FPS@", command)
    # Keep the compensated HUD slightly smaller on the final display.
    scale = (ui_scale() if scale is None else scale) * 0.4725
    for key in ("font_size", "font_size_secondary", "font_size_text", "width", "height"):
        text = "\n".join(f"{key}={float(line.split("=", 1)[1]) * scale:.12g}" if line.startswith(key + "=") else line
                         for line in text.splitlines())
    lines = [line for line in text.splitlines() if not line.strip().startswith("no_display")]
    return "\n".join(lines) + f"\nno_display={0 if visible else 1}\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", action="store_true")
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    print(render_config(args.visible), end="") if args.config else print(fps_text())

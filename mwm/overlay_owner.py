# SPDX-License-Identifier: MIT
"""Identify MWM HUDs across source and installed copies of the application."""
import os
from pathlib import Path


def hud_instances(renderer, proc_root=Path('/proc'), uid=None):
    uid = os.getuid() if uid is None else uid
    renderer = Path(renderer).resolve()
    found = []
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            for arg in args:
                if not arg.endswith(b'/fps_overlay.py'):
                    continue
                candidate = Path(os.fsdecode(arg)).resolve()
                app = candidate.parent
                recognized = candidate == renderer or (
                    (app / 'mwm.py').is_file()
                    and (app / 'scripts/performance-overlay.py').is_file()
                    and (app / 'scripts/fps-collector.sh').is_file())
                if recognized:
                    found.append((int(proc.name), args))
                    break
        except (OSError, ValueError):
            continue
    return found


def hud_should_run(style, cfg):
    try:
        mode = (Path(cfg) / 'performance-overlay-mode').read_text().strip().lower()
    except OSError:
        # Preserve direct/manual HUD launches without saved MWM settings.
        return True
    mode = {'text': 'minimal', 'graph': 'detailed'}.get(mode, mode)
    return mode == style and mode in ('minimal', 'detailed')

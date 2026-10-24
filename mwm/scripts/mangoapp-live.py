#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Attach MangoApp to the running MWM compositor without restarting the game."""
import os,sys,subprocess,time,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from host_platform import mangoapp_program
STATE=Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state")))/"mwm"
def identity(pid):
    try:return Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()[19]
    except (OSError,IndexError):return None

def child_environment(pid):
    queue=[pid];candidates=[];seen=set()
    while queue:
        current=queue.pop(0)
        if current in seen:continue
        seen.add(current)
        try:
            for task in Path(f"/proc/{current}/task").glob("*/children"):
                try:queue.extend(map(int,task.read_text().split()))
                except OSError:pass
            env=dict(v.split("=",1) for v in Path(f"/proc/{current}/environ").read_text().split("\0") if "=" in v)
            if env.get("GAMESCOPE_WAYLAND_DISPLAY") and env.get("DISPLAY"):
                candidates.append(env)
        except OSError:pass
    if not candidates:raise RuntimeError("MWM compositor client display unavailable")
    return candidates[-1]

def run():
    owner=int((STATE/"gamescope.pid").read_text());token=identity(owner)
    if token is None:raise RuntimeError("MWM display session stopped")
    env=child_environment(owner);real=mangoapp_program(ROOT)
    if real is None:raise RuntimeError("MangoApp executable unavailable")
    for key in ("WAYLAND_DISPLAY","MANGOHUD_CONFIG"):env.pop(key,None)
    env.update(MWM_REAL_MANGOAPP=str(real),XDG_SESSION_TYPE="x11",SDL_VIDEODRIVER="x11")
    (STATE/"mangoapp-failed").unlink(missing_ok=True)
    child=subprocess.Popen(["bash",str(ROOT/"scripts/mangoapp-bin/mangoapp")],env=env,start_new_session=True)
    def stop(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while child.poll() is None and identity(owner)==token:
            if int((STATE/"gamescope.pid").read_text())!=owner:break
            time.sleep(.5)
    finally:
        if child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
if __name__=="__main__":
    try:run()
    except (OSError,ValueError,RuntimeError) as e:print("MangoApp attach:",e,file=sys.stderr);sys.exit(1)

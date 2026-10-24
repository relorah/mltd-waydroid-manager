#!/usr/bin/env python3
"""Fit only this MWM session's window after leaving fullscreen on KDE."""
import argparse
import json
import os
import signal
import tempfile
from pathlib import Path
import shutil
import subprocess
import time


def fit_geometry(frame, client, area, ratio):
    """Use the largest ratio-correct client size that fits the work area."""
    bx = max(0, frame['width'] - client['width'])
    by = max(0, frame['height'] - client['height'])
    width = min(area['width'] - bx, (area['height'] - by) * ratio)
    width = max(1, round(width))
    height = max(1, round(width / ratio))
    fw, fh = width + bx, height + by
    x = max(area['x'], min(frame['x'], area['x'] + area['width'] - fw))
    y = max(area['y'], min(frame['y'], area['y'] + area['height'] - fh))
    return dict(x=round(x), y=round(y), width=round(fw), height=round(fh))


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def descendants(pid):
    found = {pid}
    queue = [pid]
    while queue:
        current = queue.pop()
        try:
            children = Path(f'/proc/{current}/task/{current}/children').read_text().split()
        except OSError:
            continue
        for child in map(int, children):
            if child not in found:
                found.add(child)
                queue.append(child)
    return sorted(found)


def query(pids, target=None, geometry=None, span=False):
    # PID ownership avoids touching unrelated Gamescope applications.
    js = '''
var pids = PIDS, target = TARGET, geometry = GEOMETRY, span = SPAN;
var list = workspace.stackingOrder || [];
for (var i=0; i<list.length; i++) {
 var w=list[i], cls=String(w.resourceClass || "").toLowerCase();
 var desktop=String(w.desktopFileName || "").toLowerCase();
 if (pids.indexOf(Number(w.pid))<0 || (cls.indexOf("gamescope")<0 && desktop.indexOf("gamescope")<0)) continue;
 var id=String(w.internalId);
 if (target !== null && id !== target) continue;
 if (geometry !== null) {
   if (w.minimized) continue;
   if(span) { w.fullScreen=false; w.noBorder=true; }
   else if(w.fullScreen) continue;
   w.setMaximize(false,false);
   w.frameGeometry=geometry;
 }
 var f=w.frameGeometry, c=w.clientGeometry;
 var a=workspace.clientArea(KWin.WorkArea,w);
 output_result(JSON.stringify({id:id,fullscreen:!!w.fullScreen,minimized:!!w.minimized,resizing:!!w.resize,
 frame:{x:f.x,y:f.y,width:f.width,height:f.height},
 client:{x:c.x,y:c.y,width:c.width,height:c.height},
 area:{x:a.x,y:a.y,width:a.width,height:a.height}}));
 break;
}
'''.replace('PIDS', json.dumps(pids)).replace('TARGET', json.dumps(target)).replace('GEOMETRY', json.dumps(geometry)).replace('SPAN',json.dumps(span))
    try:
        result = subprocess.run(['kdotool','kwinscript','--inline',js],capture_output=True,text=True,timeout=2)
        for line in result.stdout.splitlines():
            if line.startswith('{'):
                return json.loads(line)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


class ResizeScript:
    """Keep a session-scoped KWin event handler alive until Gamescope exits."""
    def __init__(self, owner_pid):
        self.dbus = shutil.which('qdbus6') or shutil.which('qdbus')
        self.name = f'mwm-window-aspect-{owner_pid}-{os.getpid()}'
        self.path = None
        self.window_id = None

    def call(self, path, method, *args):
        return subprocess.run([self.dbus, 'org.kde.KWin', path, method, *args],
                              capture_output=True, text=True, timeout=3, check=True).stdout.strip()

    def attach(self, window_id, ratio):
        if self.window_id == window_id:
            return
        self.close()
        self.window_id = window_id
        if not self.dbus:
            print('qdbus6 unavailable: drag-time ratio lock disabled; no delayed resize correction.', flush=True)
            return
        try:
            template = Path(__file__).with_name('gamescope-window-aspect.js').read_text()
            script = template.replace('__MWM_WINDOW_ID__', json.dumps(window_id)).replace('__MWM_ASPECT_RATIO__', repr(ratio))
            fd, name = tempfile.mkstemp(prefix=self.name+'-', suffix='.js')
            self.path = Path(name)
            with os.fdopen(fd, 'w') as stream:
                stream.write(script)
            script_id = int(self.call('/Scripting', 'org.kde.kwin.Scripting.loadScript', str(self.path), self.name))
            if script_id < 0:
                raise ValueError('KWin refused resize script')
            self.call(f'/Scripting/Script{script_id}', 'org.kde.kwin.Script.run')
            print('KWin drag-time aspect handler attached: '+window_id, flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print('KWin aspect handler unavailable: '+str(error), flush=True)
            self.close()
            # Retry on the next new window, rather than issuing D-Bus requests
            # every poll when this KWin version cannot load the script.
            self.window_id = window_id

    def close(self):
        if self.path is not None:
            try:
                self.call('/Scripting', 'org.kde.kwin.Scripting.unloadScript', self.name)
            except (OSError, subprocess.SubprocessError):
                pass
            self.path.unlink(missing_ok=True)
            self.path = None
        self.window_id = None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--width',type=int,required=True)
    parser.add_argument('--height',type=int,required=True)
    parser.add_argument('--span-layout',type=Path)
    args=parser.parse_args()
    span=json.loads(args.span_layout.read_text()) if args.span_layout else None
    if not shutil.which('kdotool') or args.width<=0 or args.height<=0:
        return
    identity=process_identity(args.pid)
    previous={}
    pending={}
    fitted=set()
    span_initialized=False
    resize_script=ResizeScript(args.pid)
    def terminate(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        while identity is not None and process_identity(args.pid)==identity:
            pids=descendants(args.pid)
            if span is not None:
                state=query(pids)
                if state and not state['minimized']:
                    # Expand once at startup; later fullscreen is allowed on
                    # one display. Restore the span whenever it becomes windowed.
                    if not span_initialized or not state['fullscreen']:
                        try:
                            latest=json.loads(args.span_layout.read_text())
                            if all(k in latest for k in ('x','y','width','height')):
                                span=latest
                        except (OSError,ValueError):
                            pass
                        query(pids,geometry=span,span=True)
                        span_initialized=True
                time.sleep(.35)
                continue
            state=query(pids)
            if state:
                key=state['id']
                resize_script.attach(key,args.width/args.height)
                full=state['fullscreen']
                if state.get('resizing',False) and not full:
                    # The user chose the window size before initial fitting.
                    fitted.add(key)
                    pending.pop(key,None)
                elif full:
                    pending.pop(key,None)
                elif previous.get(key,True) and not state['minimized']:
                    pending[key]=time.monotonic()+.6
                previous[key]=full
                if key in pending and time.monotonic()>=pending[key] and not state['minimized']:
                    geometry=fit_geometry(state['frame'],state['client'],state['area'],args.width/args.height)
                    query(pids,key,geometry)
                    fitted.add(key)
                    pending.pop(key,None)
            time.sleep(.35)
    finally:
        resize_script.close()

if __name__=='__main__':
    main()

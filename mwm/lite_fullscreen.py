#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keep Lite's Waydroid and FPS windows on the primary Plasma output."""
import subprocess
import time

SCRIPT = '''
var list=workspace.stackingOrder || [], game=null;
var target={x:TARGET_X,y:TARGET_Y,width:TARGET_W,height:TARGET_H};
for(var i=0;i<list.length;i++) {
 var w=list[i], c=String(w.resourceClass || '').toLowerCase();
 if(c==='waydroid' || c.indexOf('waydroid.')===0) {
  var g=w.frameGeometry;
  if(Math.abs(g.x-target.x)>2 || Math.abs(g.y-target.y)>2 ||
     Math.abs(g.width-target.width)>2 || Math.abs(g.height-target.height)>2) {
   w.fullScreen=false;
   w.frameGeometry=target;
  }
  w.fullScreen=true;
  game=w;
 }
}
if(game) {
 for(var i=0;i<list.length;i++) {
  var w=list[i];
  if(w.caption!=='MWM Lite FPS') continue;
  w.keepAbove=true;
  w.skipTaskbar=true;
  var g=w.frameGeometry;
  w.frameGeometry={x:target.x+12,y:target.y+12,width:g.width,height:g.height};
 }
}
'''


def script_for(geometry):
    script = SCRIPT
    for key, value in zip(('X', 'Y', 'W', 'H'), geometry):
        script = script.replace('TARGET_'+key, str(int(value)))
    return script


def main():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    while True:
        app.processEvents()
        screen = app.primaryScreen()
        if screen is None:
            raise RuntimeError('Primary screen unavailable')
        g = screen.geometry()
        script = script_for((g.x(), g.y(), g.width(), g.height()))
        subprocess.run(['kdotool', 'kwinscript', '--inline', script], check=True, timeout=5)
        time.sleep(1)



if __name__ == '__main__':
    main()

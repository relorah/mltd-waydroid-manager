#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Enforce fullscreen only for Waydroid windows on Plasma."""
import subprocess
import time

SCRIPT = '''
var list=workspace.stackingOrder || [];
for(var i=0;i<list.length;i++) {
 var w=list[i], c=String(w.resourceClass || '').toLowerCase();
 if(c==='waydroid' || c.indexOf('waydroid.')===0) w.fullScreen=true;
}
'''
if __name__ == '__main__':
    while True:
        subprocess.run(['kdotool', 'kwinscript', '--inline', SCRIPT], check=True, timeout=5)
        time.sleep(1)

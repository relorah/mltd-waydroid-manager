#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate a Gamescope canvas from enabled KScreen outputs; no monitor writes."""
import importlib.util,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from span_display_info import union_bounds
CFG=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'mwm'
STATE=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'mwm'
def enabled():
 try:value=(CFG/'gamescope-span-enabled').read_text().strip()
 except FileNotFoundError:return False
 if value not in ('on','off'):raise ValueError('Invalid Gamescope span setting')
 return value=='on'
def geometry(outputs):
 return union_bounds(outputs)

def discover():
 result=subprocess.run(['kscreen-doctor','-j'],capture_output=True,text=True,timeout=4,check=True)
 return geometry(json.loads(result.stdout)['outputs'])
def calibrated_base(profile,width,height):
 if not isinstance(profile,dict):raise ValueError('RTScale calibration must be an object')
 if profile.get('display_width')!=width or profile.get('display_height')!=height:
  raise ValueError('RTScale calibration belongs to a different Android display; recalibrate before restarting')
 w=profile.get('base_width');h=profile.get('base_height')
 if type(w)!=int or type(h)!=int or not 320<=w<=7680 or h!=720:
  raise ValueError('Invalid measured RTScale base')
 return f'{w}x{h}'
def wait():
 layout=json.loads((STATE/'gamescope-span-layout.json').read_text());pid=int((STATE/'gamescope.pid').read_text())
 path=Path(__file__).with_name('gamescope-window-fit.py');spec=importlib.util.spec_from_file_location('fit',path);fit=importlib.util.module_from_spec(spec);spec.loader.exec_module(fit)
 stable=0
 for _ in range(30):
  row=fit.query(fit.descendants(pid))
  good=row and not row['fullscreen'] and all(abs(row['client'][k]-layout[k])<=2 for k in ('x','y','width','height'))
  stable=stable+1 if good else 0
  if stable>=3:print('Gamescope span READY: '+json.dumps(row['client']));return
  time.sleep(.25)
 raise RuntimeError('Gamescope outer window did not match the display canvas')
if __name__=='__main__':
 try:
  action=sys.argv[1]
  if action=='enabled':raise SystemExit(0 if enabled() else 1)
  if action=='rts-base':
   print(calibrated_base(json.loads((CFG/'gamescope-span-rts-base.json').read_text()),int(sys.argv[2]),int(sys.argv[3])))
  elif action=='wait':wait()
  else:
   g=discover()
   if action=='snapshot':
    STATE.mkdir(parents=True,exist_ok=True);(STATE/'gamescope-span-layout.json').write_text(json.dumps(g))
   print(f"{g['width']} {g['height']}")
 except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as e:print('Gamescope span: '+str(e),file=sys.stderr);sys.exit(4)

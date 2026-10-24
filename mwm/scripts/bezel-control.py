#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Session-scoped bezel output controller. Never changes OS layout or game input."""
import fcntl,importlib.util,json,os,re,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from bezel import display_plan,fingerprint,shader
from span_display_info import inventory
spec=importlib.util.spec_from_file_location('shot',ROOT/'scripts/span-screenshot.py');shot=importlib.util.module_from_spec(spec);spec.loader.exec_module(shot)
CFG=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'mwm'
STATE=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'mwm'
def read(name,default):
 try:return (CFG/name).read_text().strip()
 except OSError:return default

def plan():
 outputs=inventory(subprocess.check_output(['kscreen-doctor','-j'],text=True,timeout=3))
 overrides=json.loads(read('gamescope-span-physical-overrides','{}'))
 for o in outputs:
  if o['name'] in overrides:o['physical_mm']=overrides[o['name']]
 return display_plan(outputs,float(read('bezel-width-mm','17.5')))

def run(owner):
 STATE.mkdir(parents=True,exist_ok=True)
 lock=(STATE/'bezel-controller.lock').open('a')
 deadline=time.monotonic()+5
 while True:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
  except BlockingIOError:
   if time.monotonic()>deadline:return
   time.sleep(.2)
 token=shot.process_identity(owner)
 if token is None:return
 active=False;display=None;target=None;initial=None;last=None;blocked=False
 def prop(*args):
  return subprocess.check_output(['xprop','-display',display,'-root',*args],text=True,stderr=subprocess.STDOUT,timeout=3)
 def clear():
  nonlocal active
  if active and target and f'= {target}' in prop('GAMESCOPE_PID'):
   prop('-remove','GAMESCOPE_RESHADE_EFFECT');prop('-f','GAMESCOPE_NEW_SCALING_SCALER','32c','-set','GAMESCOPE_NEW_SCALING_SCALER','2')
  active=False
 signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
 try:
  while shot.process_identity(owner)==token and (STATE/'gamescope.pid').exists() and (STATE/'gamescope.pid').read_text().strip()==str(owner):
   try:
    if not display:
     for _,pid,env in shot.descendant_environments(owner):
      try:
       if Path(f'/proc/{pid}/exe').resolve().name=='gamescope' and Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[1:3]==[b'--backend',b'sdl'] and env.get('DISPLAY'):
        display=env['DISPLAY'];break
      except OSError:pass
     if not display:time.sleep(.5);continue
     value=prop('GAMESCOPE_PID');match=re.search(r'GAMESCOPE_PID\(CARDINAL\) = (\d+)',value)
     if not match:
      display=None;raise RuntimeError('Waiting for Gamescope X server')
     target=int(match.group(1))
     if target not in [pid for _,pid,_ in shot.descendant_environments(owner)]:raise RuntimeError('Unrelated Gamescope display')
    wanted=read('bezel-compensation-enabled','off')=='on' and read('gamescope-span-enabled','off')=='on'
    current=plan() if wanted else None
    if current:
     monitor_key=json.dumps({**current,'gap_mm':0,'width_mm':0,'screens':[{**r,'physical':[0,*r['physical'][1:]]} for r in current['screens']]},sort_keys=True)
     if initial is None:initial=monitor_key
     elif initial!=monitor_key:blocked=True
    if not wanted or blocked:
     clear();message='Bezel: monitor layout changed; restart after checking layout' if blocked else 'Bezel: off'
    else:
     key=fingerprint(current)
     if not active or key!=last:
      name='MWM-Bezel-Generated-'+key+'.fx'
      dest=Path.home()/'.local/share/gamescope/reshade/Shaders'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(shader(current))
      effect=prop('GAMESCOPE_RESHADE_EFFECT')
      if 'not found' not in effect and 'MWM-Bezel-' not in effect:raise RuntimeError('Another output shader is active')
      prop('-f','GAMESCOPE_RESHADE_EFFECT','8s','-set','GAMESCOPE_RESHADE_EFFECT',name)
      prop('-f','GAMESCOPE_NEW_SCALING_SCALER','32c','-set','GAMESCOPE_NEW_SCALING_SCALER','4')
      active=True;last=key
     message=f"Bezel: {current['gap_mm']:g} mm applied"
    (STATE/'bezel-status').write_text(message+'\n')
   except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
    try:clear()
    except Exception:pass
    (STATE/'bezel-status').write_text('Bezel: '+str(error)+'\n')
   time.sleep(2)
 finally:
  try:clear()
  except Exception:pass
if __name__=='__main__':run(int(sys.argv[1]))

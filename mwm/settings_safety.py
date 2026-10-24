"""Validate and replace MWM settings under the runtime's configuration lock."""
import os, shutil, tempfile
from pathlib import Path
from contextlib import contextmanager

CHOICES = {
 'f12-screenshot-enabled': {'on','off'},
 'rtscale-msaa-samples': {'0','2'},
 'gamescope-span-enabled': {'on','off'},
 'verify-waydroid-startup': {'on','off'},
 'display-backend': {'gamescope'}, 'gamescope-render-mode': {'fsr','rtscale'},
 'rtscale-zoom-fix': {'on','off'}, 'gamescope-fsr-enabled': {'on','off'},
 'gamescope-fsr-sharpness-enabled': {'on','off'}, 'mouse-as-touch': {'on','off'},
 'auto-start-mirishita': {'on','off'}, 'performance-overlay-mode': {'off','minimal','detailed','mangoapp'},
 'gamescope-fsr-scale': {'100','125','150','175','200'},
 'kwin-rtscale': {'off'} | {str(i) for i in range(1,9)},
 'gamescope-cas-enabled': {'on','off'}, 'gamescope-cas-strength': {str(i) for i in range(101)},
 'gamescope-sharpness': {str(i) for i in range(21)},
}
def validate(values):
 for key,value in values.items():
  value=value.strip()
  if key in CHOICES and value not in CHOICES[key]: raise ValueError(f'Invalid {key}: {value}')
  if key=='gamescope-span-physical-overrides':
   import json,re
   try: overrides=json.loads(value)
   except (TypeError,ValueError): raise ValueError('Invalid physical size overrides')
   if not isinstance(overrides,dict): raise ValueError('Invalid physical size overrides')
   for name,size in overrides.items():
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9._-]+',name): raise ValueError('Invalid monitor name in physical size overrides')
    if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 100<=v<=3000 for v in size): raise ValueError('Physical size overrides must be millimetres between 100 and 3000')
  if key=='custom-aspect':
   import re
   m=re.fullmatch(r'(\d{1,2}):(\d{1,2})',value)
   if not m or not all(1<=int(v)<=99 for v in m.groups()):raise ValueError('Invalid custom aspect ratio')
  if key=='aspect-ratio' and value not in {'auto','32:9','21:9','16:9','4:3','3:2'}:
   import re
   m=re.fullmatch(r'(\d+)x720',value)
   if not m or not 320<=int(m[1])<=7680:raise ValueError('Invalid display width')

@contextmanager
def config_lock(config):
 import fcntl
 config=Path(config); config.parent.mkdir(parents=True,exist_ok=True)
 with (config.parent/'mwm-config.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise RuntimeError('Settings are being applied or updated. Try again when complete.')
  yield

def commit(config,values,obsolete=()):
 validate(values)
 config=Path(config)
 with config_lock(config):
  if (config.parent/'mwm-config.previous').exists():
    raise RuntimeError('The previous save was interrupted. Settings recovery is required.')
  config.mkdir(parents=True,exist_ok=True)
  stage=Path(tempfile.mkdtemp(prefix='mwm-config.stage-',dir=config.parent))
  previous=config.parent/'mwm-config.previous'
  try:
   shutil.copytree(config,stage,dirs_exist_ok=True)
   for key,value in values.items():
    if '/' in key or '\\' in key:raise ValueError('Invalid setting name')
    p=stage/key
    if p.is_symlink():p.unlink()
    with p.open('w',encoding='utf-8') as out:
     out.write(value.strip()+'\n');out.flush();os.fsync(out.fileno())
   for key in obsolete:(stage/key).unlink(missing_ok=True)
   os.replace(config,previous)
   try:os.replace(stage,config)
   except BaseException:
    os.replace(previous,config);raise
   # A cleanup failure must not pretend that a committed save failed.
   try:shutil.rmtree(previous)
   except OSError:pass
  finally:
   if stage.exists():shutil.rmtree(stage,ignore_errors=True)

def recover(config):
 config=Path(config)
 with config_lock(config):
  previous=config.parent/'mwm-config.previous'
  if not previous.exists():return False
  if not config.exists():os.replace(previous,config)
  else:shutil.rmtree(previous)
  return True

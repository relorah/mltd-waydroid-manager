#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Match OS display scales and bottom-align a side-by-side layout; keep one undo point."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from span_display_info import inventory, logical_rect, matched_scale_layout, union_bounds
STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'mwm'
BACKUP = STATE / 'display-size-before.json'

def read_outputs():
    raw = subprocess.check_output(['kscreen-doctor', '-j'], text=True, timeout=5)
    return [o for o in inventory(raw) if o.get('connected') and o.get('enabled')]

def fingerprint(output):
    info = output.get('edid_info') or {}
    return [output['name'], info.get('vendor'), info.get('product_code'),
            info.get('model'), output.get('physical_mm'), output.get('size'), output.get('rotation', 1)]

def saved_layout(outputs):
    return [{'name':o['name'], 'scale':o['scale'], 'x':logical_rect(o)[0],
             'y':logical_rect(o)[1], 'fingerprint':fingerprint(o)} for o in outputs]

def apply_layout(layout):
    args=['kscreen-doctor']
    for item in layout:
        args += [f"output.{item['name']}.scale.{item['scale']}",
                 f"output.{item['name']}.position.{item['x']},{item['y']}"]
    subprocess.run(args, check=True, timeout=12)

def window_probe(outputs):
    try:
        spec=importlib.util.spec_from_file_location('fit', Path(__file__).with_name('gamescope-window-fit.py'))
        fit=importlib.util.module_from_spec(spec);spec.loader.exec_module(fit)
        owner=int((STATE/'gamescope.pid').read_text());pids=fit.descendants(owner)
        row=fit.query(pids)
        if not row:return None
        g=row['client']
        visible=sum(min(g['x']+g['width'],x+w)>max(g['x'],x) and
                    min(g['y']+g['height'],y+h)>max(g['y'],y)
                    for x,y,w,h in map(logical_rect,outputs))
        return (fit,pids) if visible>1 else None
    except (OSError,ValueError,KeyError):return None

def run(action):
    before=read_outputs();current=saved_layout(before)
    if action=='apply':
        layout=matched_scale_layout(before)
        STATE.mkdir(parents=True,exist_ok=True)
        # Keep the first restore point across repeated adjustment attempts.
        if not BACKUP.exists():
            temp=BACKUP.with_suffix('.tmp');temp.write_text(json.dumps(current));temp.replace(BACKUP)
        else:
            original=json.loads(BACKUP.read_text())
            if sorted(json.dumps(i['fingerprint'],sort_keys=True) for i in original)!=sorted(json.dumps(i['fingerprint'],sort_keys=True) for i in current):
                raise ValueError('Monitor hardware changed; restore or move the previous display-size backup first')
    else:
        layout=json.loads(BACKUP.read_text())
        if sorted(json.dumps(i['fingerprint'],sort_keys=True) for i in layout)!=sorted(json.dumps(i['fingerprint'],sort_keys=True) for i in current):
            raise ValueError('Restore belongs to a different monitor configuration')
    probe=window_probe(before)
    try:
        apply_layout(layout)
        time.sleep(.6)
        after=read_outputs()
        actual={o['name']:o for o in after}
        for item in layout:
            o=actual[item['name']];r=logical_rect(o)
            if abs(float(o['scale'])-float(item['scale']))>.01 or abs(r[0]-item['x'])>2 or abs(r[1]-item['y'])>2:
                raise RuntimeError('OS did not apply the requested display layout')
    except Exception:
        apply_layout(current)
        raise
    if probe:
        fit,pids=probe;bounds=union_bounds(after)
        fit.query(pids,geometry=bounds,span=True)
        (STATE/'gamescope-span-layout.json').write_text(json.dumps(bounds))
    if action=='restore':BACKUP.unlink()
    print(' · '.join(f"{i['name']}: {i['scale']*100:g}%" for i in layout), flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['apply','restore']);args=parser.parse_args()
    try:run(args.action)
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        print('Display size: '+str(error),file=sys.stderr);sys.exit(1)

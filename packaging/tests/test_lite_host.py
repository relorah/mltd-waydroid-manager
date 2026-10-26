"""Desktop selection and GNOME activation gates before runtime mutation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mwm'))
import lite_host as host


class HostTests(unittest.TestCase):
    def test_desktops_on_both_distributions(self):
        for desktop,expected in [('KDE','plasma'),('ubuntu:GNOME','gnome'),('GNOME','gnome'),('unknown','other')]:
            with patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':desktop,'XDG_SESSION_DESKTOP':'','GAMESCOPE_WAYLAND_DISPLAY':''}):
                self.assertEqual(host.desktop_kind(),expected)
        with patch.dict(os.environ,XDG_CURRENT_DESKTOP='KDE',XDG_SESSION_DESKTOP='gamescope'):
            self.assertEqual(host.desktop_kind(),'steam')

    def test_gnome_requires_active_extension(self):
        with patch.object(host,'desktop_kind',return_value='gnome'),patch.object(host,'gnome_ready',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'enable GNOME'):host.check_fullscreen()
        with patch.object(host,'desktop_kind',return_value='gnome'),patch.object(host,'gnome_ready',return_value=True):
            self.assertEqual(host.check_fullscreen(),'gnome')

    def test_plasma_requires_helper(self):
        with patch.object(host,'desktop_kind',return_value='plasma'),patch.object(host.shutil,'which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'kdotool'):host.check_fullscreen()

    def test_gnome_install_only_writes_user_extension_files(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,XDG_DATA_HOME=d),patch.object(host.shutil,'which',return_value=None),patch.object(host,'gnome_ready',return_value=False):
            self.assertFalse(host.install_gnome_extension(ROOT/'mwm/gnome_extension'))
            destination=Path(d)/'gnome-shell/extensions'/host.UUID
            self.assertEqual(sorted(p.name for p in destination.iterdir()),['extension.js','metadata.json'])
            self.assertEqual((destination/'extension.js').read_bytes(),(ROOT/'mwm/gnome_extension/extension.js').read_bytes())

    def test_gnome_removal_preserves_user_modified_files(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,XDG_DATA_HOME=d),patch.object(host.shutil,'which',return_value=None),patch.object(host,'gnome_ready',return_value=False):
            source=ROOT/'mwm/gnome_extension'
            host.install_gnome_extension(source)
            destination=Path(d)/'gnome-shell/extensions'/host.UUID
            (destination/'extension.js').write_text('user modified')
            host.remove_gnome_extension(source)
            self.assertEqual((destination/'extension.js').read_text(),'user modified')
            self.assertFalse((destination/'metadata.json').exists())

    @unittest.skipUnless(shutil.which('node'),'Node is required for GNOME API mock')
    def test_gnome_extension_only_controls_live_lite_windows(self):
        source=(ROOT/'mwm/gnome_extension/extension.js').read_text()
        source='\n'.join(line for line in source.splitlines() if not line.startswith('import '))
        source=source.replace('export default class','class')
        harness='''
class Extension {}
let changes=[];
const game={get_wm_class:()=> 'Waydroid',get_monitor:()=>0,move_to_monitor:i=>changes.push(['monitor',i]),is_fullscreen:()=>false,make_fullscreen:()=>changes.push(['fullscreen'])};
const fps={get_wm_class:()=> 'python',get_title:()=> 'MWM Lite FPS',make_above:()=>changes.push(['above']),move_frame:(u,x,y)=>changes.push(['fps',x,y])};
const other={get_wm_class:()=> 'browser',get_title:()=> 'Keep'};
global.display={get_primary_monitor:()=>1,get_monitor_geometry:()=>({x:2400,y:198})};
global.get_window_actors=()=>[game,fps,other].map(meta_window=>({meta_window}));
'''
        checks='''
const extension=new MwmLiteFullscreen();
extension._sessionAlive=()=>false;extension._update();
if(changes.length)throw Error('Changed windows without a session');
extension._sessionAlive=()=>true;extension._update();
if(JSON.stringify(changes)!==JSON.stringify([['monitor',1],['fullscreen'],['above'],['fps',2412,210]]))throw Error(JSON.stringify(changes));
'''
        subprocess.run(['node','--input-type=module'],input=harness+source+checks,text=True,check=True,capture_output=True)


if __name__=='__main__':unittest.main()

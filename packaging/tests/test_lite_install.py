"""Lite install paths keep Desktop settings and omit Gamescope dependencies."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]


class LiteInstallTests(unittest.TestCase):
    def test_arch_dependency_set_has_no_gamescope(self):
        source=(ROOT/'install.sh').read_text()
        function='install_packages() {'+source.split('install_packages() {',1)[1].split('\nwait_boot()',1)[0]
        # Extract through the function's final brace, before the next function.
        function=function.split('\n}\n',1)[0]+'\n}\n'
        script='set -Eeuo pipefail\nsay(){ :; }; sudo(){ printf "%s\\n" "$@"; }; python(){ :; };\nHOST_FAMILY=arch; LITE_ONLY=1; PYSIDE6_MIN_VERSION=6.7; XDG_CURRENT_DESKTOP=test\n'+function+'\ninstall_packages'
        result=subprocess.run(['bash','-c',script],capture_output=True,text=True,check=True)
        packages=result.stdout.splitlines()
        self.assertIn('pyside6',packages)
        self.assertNotIn('gamescope',packages)
        self.assertNotIn('mangohud',packages)

    def test_ubuntu_lite_does_not_probe_or_run_gamescope(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'ubuntu-safe-apt.sh').write_text('mwm_ubuntu_safe_install(){ shift; printf "%s\\n" "$@" > "$PKG_OUT"; }\n')
            venv=root/'app/.runtime/venv/bin';venv.mkdir(parents=True)
            stub=venv/'python';stub.write_text('#!/bin/bash\nexit 0\n');stub.chmod(0o755)
            env=dict(os.environ,PACKAGING=d,APP_HOME=str(root/'app'),PKG_OUT=str(root/'packages'),BOOTSTRAP_PYTHON='/bin/true',PYSIDE6_MIN_VERSION='6.7',XDG_CURRENT_DESKTOP='GNOME')
            script='set -Eeuo pipefail\nLITE_ONLY=1; sudo(){ :; }; gamescope(){ echo UNEXPECTED >&2; return 99; }; die(){ echo "$*" >&2; exit 1; };\nsource "$1/packaging/ubuntu-host.sh"; install_ubuntu_packages'
            subprocess.run(['bash','-c',script,'_',str(ROOT)],env=env,check=True,capture_output=True,text=True)
            packages=(root/'packages').read_text().splitlines()
            self.assertIn('python3-venv',packages)
            self.assertNotIn('gamescope',packages)
            self.assertNotIn('libglfw3',packages)

    @unittest.skipUnless(shutil.which('rsync'),'rsync required')
    def test_lite_only_launchers_and_desktop_settings_preserved(self):
        source=(ROOT/'install.sh').read_text()
        function='install_mwm_launcher() {'+source.split('install_mwm_launcher() {',1)[1].split('\nfinal_verify()',1)[0]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);app=root/'app';app.mkdir();cfg=root/'config/mwm';cfg.mkdir(parents=True)
            (cfg/'kwin-rtscale').write_text('6\n')
            bindir=root/'bin';bindir.mkdir();(bindir/'mwm').write_text('existing Desktop launcher')
            desktop=root/'applications';desktop.mkdir();(desktop/'mwm.desktop').write_text('existing Desktop entry')
            env=dict(os.environ,HOME=d,XDG_CONFIG_HOME=str(root/'config'),APP_HOME=str(app),SCRIPT_DIR=str(ROOT),LOCAL_BIN=str(bindir),DESKTOP_DIR=str(desktop),LITE_ONLY='1')
            script='set -Eeuo pipefail\nsay(){ :; }; ok(){ :; }; pkill(){ return 1; }; update-desktop-database(){ :; };\n'+function+'\ninstall_mwm_launcher'
            subprocess.run(['bash','-c',script],env=env,check=True,capture_output=True,text=True)
            self.assertEqual((bindir/'mwm').read_text(),'existing Desktop launcher')
            self.assertEqual((desktop/'mwm.desktop').read_text(),'existing Desktop entry')
            self.assertEqual((cfg/'kwin-rtscale').read_text(),'6\n')
            for name in ('mwm-lite','mwm-lite-settings','mwm-lite-steam-setup'):
                self.assertTrue(os.access(bindir/name,os.X_OK))
                self.assertTrue((desktop/(name+'.desktop')).exists())
            self.assertIn('steam_setup.py',(bindir/'mwm-lite-steam-setup').read_text())


if __name__=='__main__':unittest.main()

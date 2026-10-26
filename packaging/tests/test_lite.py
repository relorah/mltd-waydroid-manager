"""Lite profile defaults, geometry and transaction failure recovery."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('lite', ROOT/'mwm/lite.py')
lite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lite)


class LiteTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(lite, 'CONFIG', Path(d)/'settings.json'):
            self.assertEqual(lite.load_settings(), dict(scale=3, fps=False, boost=False))
            for scale in (1, 3, 6):
                lite.save_json(lite.CONFIG, dict(scale=scale, fps=True, boost=False))
                self.assertEqual(lite.load_settings()['scale'], scale)
            for value in (0, 2, 8, True, '3'):
                lite.save_json(lite.CONFIG, {'scale': value})
                with self.assertRaises(ValueError):
                    lite.load_settings()
            lite.save_json(lite.CONFIG, {'fps': 'false'})
            with self.assertRaises(ValueError):
                lite.load_settings()

    def test_geometry(self):
        for size, expected in [((1920,1080),1280), ((2560,1440),1280), ((1280,800),1152), ((3440,1440),1720)]:
            self.assertEqual(lite.dimensions(*size), expected)
        for size in ((0,0), (1920,0), (99999,1080)):
            with self.assertRaises(ValueError):
                lite.dimensions(*size)

    def test_supported_device_detection(self):
        with patch.object(lite.os, 'lstat', side_effect=OSError):
            self.assertFalse(lite.boost_available())
        with patch.object(lite.os, 'lstat', return_value=Mock(st_mode=0o100644)):
            self.assertFalse(lite.boost_available())

    def transaction(self, fail_at=None, terminate=False):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            calls = []
            props = {key: 'original-'+key for key in lite.PROPS}
            def prop(key, value=None):
                if value is None:
                    return props[key]
                calls.append(('prop', key, value))
            def helper(*args):
                calls.append(args)
                if args == (fail_at,) and calls.count(args) == 1:
                    raise RuntimeError('injected failure')
                if args == ('pidof-mirishita',):
                    if terminate:
                        raise KeyboardInterrupt
                    return ''
                return ''
            process = Mock()
            process.poll.return_value = None
            process.wait.return_value = 0
            with patch.object(lite, 'STATE', state), patch.object(lite, 'load_settings', return_value=dict(scale=3,fps=False,boost=False)), patch.object(lite, 'screen_size', return_value=(1920,1080)), patch.object(lite, 'boost_available', return_value=False), patch.object(lite, 'call', return_value='STOPPED'), patch.object(lite, 'boot'), patch.object(lite, 'stop_helpers'), patch.object(lite, 'prop', side_effect=prop), patch.object(lite, 'helper', side_effect=helper), patch.object(lite.subprocess, 'Popen', return_value=process), patch.dict(os.environ, WAYLAND_DISPLAY='wayland-test', XDG_CURRENT_DESKTOP='test'), patch.object(lite.time, 'monotonic', side_effect=[0, 99]):
                with self.assertRaises((RuntimeError, KeyboardInterrupt)):
                    lite.run_locked()
            self.assertIn(('lite-rtscale-restore',), calls)
            for key in lite.PROPS:
                self.assertIn(('prop',key,props[key]), calls)
            self.assertFalse((state/'restore.json').exists())
            return calls

    def test_startup_failure_restores(self):
        calls = self.transaction(fail_at='force-stop-app')
        self.assertNotIn(('rtscale-write','3','1280','720','1','1'),calls)

    def test_launch_timeout_restores(self):
        calls = self.transaction()
        self.assertIn(('rtscale-write','3','1280','720','1','1'),calls)

    def test_steam_termination_restores(self):
        self.transaction(terminate=True)

    def test_failed_restore_keeps_journal(self):
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d)/'restore.json'
            lite.save_json(journal, {'props':dict.fromkeys(lite.PROPS,'')})
            with patch.object(lite, 'call'), patch.object(lite, 'helper', side_effect=RuntimeError('failure')):
                with self.assertRaises(RuntimeError):
                    lite.restore(journal)
            self.assertTrue(journal.exists())

    def test_desktop_profile_is_not_written(self):
        source = (ROOT/'mwm/lite.py').read_text()
        self.assertNotIn("/ 'mwm'", source)
        self.assertNotIn('gamescope-control', source)

class LiteBackupTests(unittest.TestCase):
    def test_android_backup_round_trip_and_absent_file(self):
        import subprocess
        source = (ROOT/'packaging/mwm-root-helper').read_text()
        def action(name, directory):
            body = source.split('  '+name+')',1)[1].split('    ;;',1)[0]
            body = body.replace('[[ $# -eq 1 ]] || exit 2', ':')
            body = body.replace('/data/local/tmp', str(directory)).replace('restorecon ', ': ').replace('= 0:700', '= '+str(os.getuid())+':700')
            return subprocess.run(['bash','-c', 'set -euo pipefail\nwd() { "$@"; }\nrestorecon() { :; }\nset -- action\n'+body], capture_output=True)
        for existing in (True, False):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                config = directory/'gles_rtscale.conf'
                original = b'custom desktop configuration\n\nscale=6\n'
                if existing:
                    config.write_bytes(original)
                self.assertEqual(action('lite-rtscale-save',directory).returncode,0)
                # A second start must never overwrite the original backup.
                self.assertNotEqual(action('lite-rtscale-save',directory).returncode,0)
                config.write_text('Lite temporary configuration\n')
                self.assertEqual(action('lite-rtscale-restore',directory).returncode,0)
                self.assertEqual(config.read_bytes() if config.exists() else None, original if existing else None)
                self.assertEqual(action('lite-rtscale-restore',directory).returncode,0)


class LiteSupervisorTests(unittest.TestCase):
    def test_owner_identity(self):
        with patch.object(lite, 'OWNER', None):
            self.assertTrue(lite.owner_alive())
        stamp = Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
        with patch.object(lite, 'OWNER', (os.getpid(),stamp)):
            self.assertTrue(lite.owner_alive())
        with patch.object(lite, 'OWNER', (os.getpid(),'wrong')):
            self.assertFalse(lite.owner_alive())
        with patch.object(lite, 'OWNER', (999999999,'1')):
            self.assertFalse(lite.owner_alive())

    def test_service_owns_cleanup_without_steam_preload(self):
        process=Mock()
        process.wait.return_value=0
        process.poll.return_value=0
        with tempfile.TemporaryDirectory() as directory, patch.object(lite,'STATE',Path(directory)), patch.object(lite.subprocess,'Popen',return_value=process) as start, patch.dict(os.environ,LD_PRELOAD='steam-test-preload',SteamAppId='123'):
            self.assertEqual(lite.run_supervised(),0)
        command=start.call_args.args[0]
        self.assertIn('--property=KillMode=mixed',command)
        self.assertIn('--property=TimeoutStopSec=180',command)
        self.assertIn('--setenv=SteamAppId=123',command)
        self.assertIn('--session-owner',command)
        self.assertFalse(any('LD_PRELOAD' in arg for arg in command))

    def test_primary_screen_script(self):
        spec=importlib.util.spec_from_file_location('lite_fullscreen',ROOT/'mwm/lite_fullscreen.py')
        fullscreen=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fullscreen)
        script=fullscreen.script_for((-1920,120,1920,1080))
        self.assertNotIn('TARGET_',script)
        self.assertIn('x:-1920',script)
        self.assertIn('w.frameGeometry=target',script)
        self.assertIn('w.fullScreen=true',script)


if __name__ == '__main__':
    unittest.main()

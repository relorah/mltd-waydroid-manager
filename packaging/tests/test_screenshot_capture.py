"""Capture routing and focus regression tests; no live shortcuts or settings writes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import struct

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location('screenshot', ROOT/'mwm/scripts/span-screenshot.py')
screenshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screenshot)

class CaptureTests(unittest.TestCase):
    def test_control_v2_is_rejected(self):
        event = screenshot.message(2, 0, struct.pack('<I', 17) + screenshot.string('gamescope_control') + struct.pack('<I', 2))
        event += screenshot.message(3, 0, struct.pack('<I', 9))
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'GAMESCOPE_WAYLAND_DISPLAY':'/tmp/test-only'}), patch.object(screenshot.socket, 'socket') as factory:
            client = factory.return_value.__enter__.return_value
            client.recv.return_value = event
            with self.assertRaisesRegex(RuntimeError, 'v3'):
                screenshot.request_capture(Path(folder)/'unused.png')
            self.assertEqual(client.sendall.call_count, 1)

    def test_v3_fragmented_registry_requests_full_composition_and_preserves_size(self):
        event = screenshot.message(2, 0, struct.pack('<I', 17) + screenshot.string('gamescope_control') + struct.pack('<I', 3))
        event += screenshot.message(3, 0, struct.pack('<I', 9))
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'GAMESCOPE_WAYLAND_DISPLAY':'/tmp/test-only'}), patch.object(screenshot.socket, 'socket') as factory:
            path = Path(folder)/'image.png'
            # Minimal framing fixture, not a decoded-image validation test.
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I',13) + b'IHDR' + struct.pack('>II',3840,1080) + b'\0\0\0\0IEND\xaeB`\x82')
            client = factory.return_value.__enter__.return_value
            client.recv.side_effect = [event[:5],event[5:19],event[19:]]
            self.assertEqual(screenshot.request_capture(path), (3840,1080))
            wire = client.sendall.call_args.args[0]
            self.assertTrue(wire.endswith(screenshot.message(4,2,screenshot.string(str(path))+struct.pack('<II',3,0))))

    def test_nested_compositor_uses_outer_window_owner(self):
        def read_stat(path, *args, **kwargs):
            pid=int(str(path).split('/')[2])
            return f"{pid} (process) S { {10:20,20:30,30:1}[pid]}"
        def resolve_exe(path, *args, **kwargs):
            pid=int(str(path).split('/')[2])
            return Path('/usr/bin/gamescope' if pid in (10,20) else '/usr/bin/bash')
        with patch.object(Path, 'read_text', read_stat), patch.object(Path, 'resolve', resolve_exe):
            self.assertEqual(screenshot.gamescope_ancestor(10),20)

    def test_bezel_capture_uses_inner_socket_without_changing_environment(self):
        env = {'GAMESCOPE_WAYLAND_DISPLAY':'gamescope-0', 'XDG_RUNTIME_DIR':'/run/user/test'}
        descendants = [(1, 20, dict(env)), (3, 30, dict(env, GAMESCOPE_WAYLAND_DISPLAY='gamescope-1'))]
        with patch.dict('os.environ', env), patch.object(screenshot, 'outer_effect', return_value='MWM-Bezel-17p5-Copy.fx'), patch.object(screenshot, 'descendant_environments', return_value=descendants), patch.object(screenshot, 'process_identity', return_value='token'):
            self.assertEqual(screenshot.capture_source(10), ('gamescope-1','/run/user/test','before bezel compensation'))
            self.assertEqual(screenshot.os.environ['GAMESCOPE_WAYLAND_DISPLAY'],'gamescope-0')

    def test_ordinary_capture_keeps_outer_composition(self):
        with patch.dict('os.environ', {'GAMESCOPE_WAYLAND_DISPLAY':'gamescope-0','XDG_RUNTIME_DIR':'/run/user/test'}), patch.object(screenshot, 'outer_effect', return_value='OtherEffect.fx'), patch.object(screenshot, 'descendant_environments') as discover:
            self.assertEqual(screenshot.capture_source(10), ('gamescope-0','/run/user/test','display'))
            discover.assert_not_called()

    def test_missing_inner_socket_does_not_save_distorted_fallback(self):
        with patch.dict('os.environ', {'GAMESCOPE_WAYLAND_DISPLAY':'gamescope-0','XDG_RUNTIME_DIR':'/run/user/test'}), patch.object(screenshot, 'outer_effect', return_value='MWM-Bezel-17p5-Copy.fx'), patch.object(screenshot, 'descendant_environments', return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'inner Gamescope'):
                screenshot.capture_source(10)

    def test_effect_detection_refuses_another_session(self):
        properties='GAMESCOPE_PID(CARDINAL) = 999\nGAMESCOPE_RESHADE_EFFECT(STRING) = "MWM-Bezel-17p5-Copy.fx"'
        with patch.dict('os.environ', {'DISPLAY':':1'}), patch.object(screenshot.subprocess,'check_output',return_value=properties):
            with self.assertRaisesRegex(RuntimeError,'does not belong'):
                screenshot.outer_effect(10)

    def test_focused_owner_only(self):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtQml import QJSEngine
        app = QCoreApplication.instance() or QCoreApplication([])
        engine = QJSEngine()
        result = engine.evaluate('var callback; var calls=0; var workspace={activeWindow:null}; function registerShortcut(a,b,c,fn){callback=fn;return true;} function callDBus(a,b,c,d){if(d==="Capture")calls++;}')
        self.assertFalse(result.isError())
        self.assertFalse(engine.evaluate(screenshot.shortcut_script(123)).isError())
        for active,expected in [('null',0), ('{pid:456,minimized:false}',0), ('{pid:123,minimized:true}',0), ('{pid:123,minimized:false}',1)]:
            self.assertEqual(engine.evaluate('workspace.activeWindow='+active+';callback();calls').toInt(),expected)

if __name__ == '__main__':
    unittest.main()

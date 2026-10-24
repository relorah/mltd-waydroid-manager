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

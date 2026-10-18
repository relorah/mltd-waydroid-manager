import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mwm'))
sys.path.insert(0, str(ROOT / 'mwm/scripts'))
from overlay_owner import hud_instances, hud_should_run

spec = importlib.util.spec_from_file_location('overlay_control', ROOT / 'mwm/scripts/performance-overlay.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def app_copy(path):
    (path / 'scripts').mkdir(parents=True)
    for name in ('mwm.py', 'fps_overlay.py', 'scripts/performance-overlay.py', 'scripts/fps-collector.sh'):
        (path / name).touch()
    return path / 'fps_overlay.py'


def process(proc, pid, renderer):
    entry = proc / str(pid)
    entry.mkdir()
    (entry / 'cmdline').write_bytes(b'python\0' + os.fsencode(renderer) + b'\0--style\0detailed\0')


class OwnerTests(unittest.TestCase):
    def test_cross_copy_detection_excludes_unrelated_processes(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            own = app_copy(base / 'desktop')
            installed = app_copy(base / 'installed')
            proc = base / 'proc'; proc.mkdir()
            process(proc, 101, own)
            process(proc, 102, installed)
            unrelated = base / 'other/fps_overlay.py'
            unrelated.parent.mkdir(); unrelated.touch()
            process(proc, 103, unrelated)
            self.assertEqual({pid for pid, _ in hud_instances(own, proc)}, {101, 102})
            self.assertEqual(hud_instances(own, proc, uid=os.getuid() + 1), [])

    def test_saved_mode_prevents_late_or_stale_hud_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self.assertTrue(hud_should_run('detailed', cfg))
            for mode, visible in [('mangoapp', False), ('off', False), ('minimal', False), ('detailed', True)]:
                (cfg / 'performance-overlay-mode').write_text(mode)
                self.assertEqual(hud_should_run('detailed', cfg), visible)

    def switch(self, mode, fail_control=False):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); cfg = base / 'cfg'; cfg.mkdir()
            (cfg / 'performance-overlay-mode').write_text(mode)
            own = app_copy(base / 'desktop')
            installed = app_copy(base / 'installed')
            proc = base / 'proc'; proc.mkdir()
            process(proc, 101, installed)
            events = []

            def kill(pid, sig):
                events.append(('kill', pid))
                (proc / str(pid) / 'cmdline').unlink(missing_ok=True)

            def command(*args, **kwargs):
                events.append(('mango', args[0]))
                if fail_control:
                    raise subprocess.CalledProcessError(1, args[0])
                return subprocess.CompletedProcess(args[0], 0)

            with patch.object(control, 'CFG', cfg), patch.object(control, 'STATE', base / 'state'), \
                 patch.object(control, 'instances', lambda: hud_instances(own, proc)), \
                 patch.object(control, 'mango_running', lambda: True), \
                 patch.object(control, 'render_config', lambda visible: f'no_display={int(not visible)}\n'), \
                 patch.object(control.os, 'kill', kill), patch.object(control.subprocess, 'run', command):
                if fail_control:
                    with self.assertRaises(RuntimeError):
                        control.reconcile()
                else:
                    control.reconcile()
            self.assertEqual(hud_instances(own, proc), [])
            return events

    def test_switch_to_mango_stops_other_copy_before_reveal(self):
        events = self.switch('mangoapp')
        self.assertEqual(events[0], ('kill', 101))

    def test_failed_mango_visibility_request_cannot_leave_mwm_hud(self):
        self.switch('detailed', fail_control=True)


if __name__ == '__main__':
    unittest.main()

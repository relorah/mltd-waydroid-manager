import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'mwm/scripts'
sys.path.insert(0, str(SCRIPTS))
from gamescope_fps_policy import FPSPolicy, read_mode

spec = importlib.util.spec_from_file_location('fps_control', SCRIPTS / 'gamescope-fps-control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def feed(policy, rate, start=0, seconds=6):
    for tick in range(int(seconds * 5) + 1):
        policy.update(rate, start + tick / 5)


class PolicyTests(unittest.TestCase):
    def test_default_is_120_and_does_not_capture_startup_dips(self):
        p = FPSPolicy()
        feed(p, 47, seconds=12)
        feed(p, 57, 13, 12)
        feed(p, 60, 26, 10)
        self.assertEqual(p.limit, 120)
        self.assertFalse(p.observing)

    def test_stable_sixty_and_dips(self):
        p = FPSPolicy('auto')
        feed(p, 59.94)
        self.assertEqual(p.limit, 60)
        feed(p, 42, 7, 15)
        self.assertEqual(p.limit, 60)
        self.assertFalse(p.observing)

    def test_future_120_and_load_dips(self):
        p = FPSPolicy('auto')
        feed(p, 119.88)
        self.assertEqual(p.limit, 120)
        self.assertFalse(p.observing)
        feed(p, 60, 7, 10)
        self.assertEqual(p.limit, 120)

    def test_no_inference_from_gpu_bound_rate(self):
        p = FPSPolicy('auto')
        feed(p, 47, seconds=30)
        self.assertEqual(p.limit, 120)
        self.assertTrue(p.observing)

    def test_idle_relearns_new_session(self):
        p = FPSPolicy('auto')
        feed(p, 60)
        for n in range(7, 18):
            p.update(0, n)
        self.assertEqual(p.limit, 120)
        feed(p, 120, 18)
        self.assertEqual(p.limit, 120)
        self.assertFalse(p.observing)

    def test_short_burst_and_invalid_samples_are_not_modes(self):
        p = FPSPolicy('auto')
        feed(p, 60, seconds=2)
        self.assertTrue(p.observing)
        for n, value in enumerate([float('nan'), float('inf'), -1, 999]):
            p.update(value, 3 + n)
        self.assertTrue(p.observing)

    def test_config_and_fixed_modes(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'mode'
            self.assertEqual(read_mode(cfg), '120')
            cfg.write_text('120\n')
            self.assertEqual(read_mode(cfg), '120')
            cfg.write_text('200\n')
            self.assertEqual(read_mode(cfg), '120')
        for mode, value in [('60', 60), ('120', 120), ('off', 0)]:
            p = FPSPolicy(mode)
            feed(p, 20, seconds=10)
            self.assertEqual(p.limit, value)


class BackendTests(unittest.TestCase):
    def test_optional_control_failure_still_launches_waydroid(self):
        with tempfile.TemporaryDirectory() as d:
            tool = Path(d) / 'waydroid'
            tool.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$CALLS"\n')
            tool.chmod(0o755)
            env = dict(os.environ, PATH=d + ':/usr/bin', CALLS=str(Path(d) / 'calls'))
            env.pop('GAMESCOPE_WAYLAND_DISPLAY', None)
            result = subprocess.run([sys.executable, str(SCRIPTS / 'gamescope-fps-control.py'), '--launch'],
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(d) / 'calls').read_text().strip(), 'show-full-ui')
            (Path(d) / 'calls').unlink()
            subprocess.run([sys.executable, str(SCRIPTS / 'gamescope-fps-control.py'), '--check'],
                           env=env, capture_output=True, text=True, timeout=5, check=True)
            self.assertFalse((Path(d) / 'calls').exists())

    def test_only_scoped_runtime_requests(self):
        with tempfile.TemporaryDirectory() as d, socket.socket(socket.AF_UNIX) as s:
            root = Path(d)
            s.bind(str(root / 'session'))
            tool = root / 'gamescopectl'
            tool.write_text('#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\n'
                            'if sys.argv[1:] == ["help"]: print("debug_set_fps_limit")\n'
                            'else: Path(os.environ["CALLS"]).write_text(" ".join(sys.argv[1:]))\n')
            tool.chmod(0o755)
            env = dict(os.environ, PATH=d, GAMESCOPE_WAYLAND_DISPLAY='session',
                       XDG_RUNTIME_DIR=d, CALLS=str(root / 'calls'))
            b = control.Backend(env)
            self.assertFalse((root / 'calls').exists())
            b.request(60)
            self.assertEqual((root / 'calls').read_text(), 'debug_set_fps_limit 60')
            b.request(120)
            self.assertEqual((root / 'calls').read_text(), 'debug_set_fps_limit 120')
            with self.assertRaises(ValueError):
                b.request(200)
            env.pop('GAMESCOPE_WAYLAND_DISPLAY')
            with self.assertRaises(RuntimeError):
                control.Backend(env)

    def test_live_mode_change_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / 'cfg'; cfg.mkdir()
            scripts = root / 'scripts'; scripts.mkdir()
            collector = scripts / 'fps-collector.sh'
            collector.write_text('#!/bin/bash\nprintf "60.00 16.67\\n"\nsleep 30\n')
            collector.chmod(0o755)
            requests = []

            class FakeBackend:
                socket = root / 'session'
                def alive(self): return len(requests) < 2
                def request(self, fps):
                    requests.append(fps)
                    (cfg / 'gamescope-fps-limit').write_text('60\n')

            old_scripts = control.SCRIPTS
            old_term = signal.getsignal(signal.SIGTERM)
            old_int = signal.getsignal(signal.SIGINT)
            try:
                control.SCRIPTS = scripts
                owner = (os.getpid(), control.process_identity(os.getpid()))
                control.run(FakeBackend(), owner, cfg, root / 'state')
            finally:
                control.SCRIPTS = old_scripts
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)
            self.assertEqual(requests, [120, 60])
            self.assertFalse((root / 'state/gamescope-fps-sample').exists())
            self.assertFalse((root / 'state/gamescope-fps-limit.json').exists())


class SharedTelemetryTests(unittest.TestCase):
    def test_shared_sample_avoids_duplicate_queries_and_stale_falls_back(self):
        for fresh in (True, False):
            with self.subTest(fresh=fresh), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                scripts = root / 'scripts'; scripts.mkdir()
                target = scripts / 'fps-collector.sh'
                target.write_bytes((SCRIPTS / 'fps-collector.sh').read_bytes())
                target.chmod(0o755)
                (scripts / 'common.sh').write_text('root_helper() { touch "$QUERY_LOG"; return 0; }\n')
                state = root / 'state/mwm'; state.mkdir(parents=True)
                stamp = int(time.time()) - (0 if fresh else 10)
                (state / 'gamescope-fps-sample').write_text(f'59.94 16.68 {stamp} {os.getpid()}\n')
                proc = subprocess.Popen([str(target), '0.2'],
                    env=dict(os.environ, XDG_STATE_HOME=str(root / 'state'), QUERY_LOG=str(root / 'queried')),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    line = proc.stdout.readline().strip()
                    self.assertEqual(line, '59.94 16.68' if fresh else '0.00 0.00')
                    self.assertEqual((root / 'queried').exists(), not fresh)
                finally:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=3)
                    proc.stdout.close(); proc.stderr.close()


class PipelineTests(unittest.TestCase):
    def test_all_pipelines_launch_controller_at_the_waydroid_compositor(self):
        source = (SCRIPTS / 'gamescope-control.sh').read_text()
        functions = 'start_no_fsr() {' + source.split('start_no_fsr() {', 1)[1].split('\nstart_gamescope()', 1)[0]
        stubs = '''set -Eeuo pipefail
outer_backend() { echo wayland; }
read_window_mode() { echo fullscreen; }
read_fsr_sharpness_enabled() { echo off; }
read_sharpness_native() { echo 18; }
gamescope_sharpness_option() { echo --sharpness; }
gamescope() { echo test; }
scale_even() { echo "$(( $1 * $2 / 100 ))"; }
write_session() { :; }
launch_outer() { shift 2; printf '%s\\n' "$@" > "$CALLS"; }
'''
        for call in ('start_no_fsr auto 1280 720 1920 1080 off off',
                     'start_fsr_150 auto 1280 720 1920 1080 18 10 off off',
                     'start_fsr_scaled auto 1280 720 1920 1080 150 10 off off'):
            with self.subTest(call=call), tempfile.TemporaryDirectory() as d:
                env = dict(os.environ, SCRIPT_DIR=str(SCRIPTS), LOG_FILE=d + '/log', CALLS=d + '/calls')
                subprocess.run(['bash', '-c', stubs + functions + '\n' + call],
                               env=env, capture_output=True, text=True, check=True)
                args = Path(d + '/calls').read_text().splitlines()
                self.assertEqual(args.count(str(SCRIPTS / 'gamescope-client.sh')), 1)
                self.assertEqual(args[-2:], ['bash', str(SCRIPTS / 'gamescope-client.sh')])
                limits = [args[n + 1] for n, item in enumerate(args) if item == '-r']
                self.assertEqual(limits, ['120', '120'] if 'start_fsr_scaled' in call else ['120'])


if __name__ == '__main__':
    unittest.main()

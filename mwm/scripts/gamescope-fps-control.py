#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Session-scoped Gamescope FPS control; no host monitor configuration."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import time

from gamescope_fps_policy import FPSPolicy, read_mode

SCRIPTS = Path(__file__).resolve().parent


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def gamescope_ancestor():
    pid = os.getppid()
    for _ in range(32):
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
            name = Path(f'/proc/{pid}/exe').resolve().name
            if name == 'gamescope':
                return pid, fields[19]
            pid = int(fields[1])
            if pid <= 1:
                break
        except (OSError, ValueError, IndexError):
            break
    return None


class Backend:
    def __init__(self, env=None):
        self.env = dict(os.environ if env is None else env)
        self.executable = shutil.which('gamescopectl', path=self.env.get('PATH'))
        socket_name = self.env.get('GAMESCOPE_WAYLAND_DISPLAY', '')
        if not socket_name:
            raise RuntimeError('Gamescope did not supply a Wayland socket')
        self.socket = Path(socket_name)
        if not self.socket.is_absolute():
            runtime = self.env.get('XDG_RUNTIME_DIR')
            if not runtime or '/' in socket_name:
                raise RuntimeError('Invalid Gamescope socket')
            self.socket = Path(runtime) / socket_name
        if not self.executable or not self.alive():
            raise RuntimeError('gamescopectl or the session socket is unavailable')
        help_result = self.command('help')
        if 'debug_set_fps_limit' not in help_result:
            raise RuntimeError('This Gamescope does not advertise runtime FPS control')

    def alive(self):
        try:
            return stat.S_ISSOCK(self.socket.stat().st_mode)
        except OSError:
            return False

    def command(self, *args):
        result = subprocess.run([self.executable, *args], env=self.env,
                                capture_output=True, text=True, timeout=3)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip() or 'gamescopectl failed')
        return result.stdout + result.stderr

    def request(self, fps):
        if fps not in (0, 60, 120):
            raise ValueError('Invalid FPS limit')
        self.command('debug_set_fps_limit', str(fps))


def atomic_text(path, text):
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        temp.write_text(text)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def stop_collector(proc):
    if proc is None:
        return
    # The collector and its restricted-helper children have their own group.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)
    proc.stdout.close()


def run(backend, owner, cfg, state, launcher=None):
    state.mkdir(parents=True, exist_ok=True)
    sample_file = state / 'gamescope-fps-sample'
    status_file = state / 'gamescope-fps-limit.json'
    stop = False

    def terminate(*_args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    collector = None
    requested = None
    mode = None
    policy = None
    retry_at = 0
    last_status = 0
    measured = 0.0
    last_sample = 0
    selector = selectors.DefaultSelector()
    with (state / 'gamescope-fps-control.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            while not stop and backend.alive() and process_identity(owner[0]) == owner[1]:
                now = time.monotonic()
                if launcher is not None:
                    launcher.poll()
                saved_mode = read_mode(cfg / 'gamescope-fps-limit')
                if saved_mode != mode:
                    mode = saved_mode
                    policy = FPSPolicy(mode)
                if mode == 'auto' and collector is None and now >= retry_at:
                    collector = subprocess.Popen(
                        [str(SCRIPTS / 'fps-collector.sh'), '0.2'],
                        env={**os.environ, 'MWM_FPS_SOURCE_OWNER': '1'},
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1, start_new_session=True)
                    selector.register(collector.stdout, selectors.EVENT_READ)
                    last_sample = now
                if mode != 'auto' and collector is not None:
                    selector.unregister(collector.stdout)
                    stop_collector(collector)
                    collector = None
                    sample_file.unlink(missing_ok=True)
                if collector is not None:
                    for key, _ in selector.select(timeout=.2):
                        line = key.fileobj.readline()
                        if not line:
                            selector.unregister(collector.stdout)
                            stop_collector(collector)
                            collector = None
                            retry_at = now + 3
                            print('Gamescope FPS: measurement stopped; retrying', flush=True)
                            break
                        try:
                            parts = line.split()
                            measured, frametime = float(parts[0]), float(parts[1])
                            if not (0 <= measured <= 240 and 0 <= frametime <= 1000):
                                continue
                        except (IndexError, ValueError):
                            continue
                        last_sample = time.monotonic()
                        policy.update(measured, last_sample)
                        atomic_text(sample_file, f'{measured:.2f} {frametime:.2f} {int(time.time())} {os.getpid()}\n')
                else:
                    time.sleep(.2)
                if mode == 'auto' and now - last_sample > 2:
                    policy.update(0, now)
                    measured = 0.0
                if policy.limit != requested:
                    backend.request(policy.limit)
                    requested = policy.limit
                    print(f'Gamescope FPS: requested {requested or "unlimited"} / mode={mode}', flush=True)
                if now - last_status >= 1:
                    atomic_text(status_file, json.dumps(dict(
                        owner_pid=os.getpid(), socket=str(backend.socket), mode=mode,
                        measured_fps=measured, requested_fps=requested,
                        observing=policy.observing, updated=time.time())) + '\n')
                    last_status = now
        finally:
            stop_collector(collector)
            selector.close()
            for path in (sample_file, status_file):
                try:
                    owned = (str(os.getpid()) == path.read_text().split()[-1]
                             if path == sample_file else json.loads(path.read_text())['owner_pid'] == os.getpid())
                    if owned:
                        path.unlink(missing_ok=True)
                except (OSError, ValueError, KeyError, IndexError):
                    pass
            if requested is not None and backend.alive() and process_identity(owner[0]) == owner[1]:
                try:
                    backend.request(0)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true', help='read capabilities without changing limits')
    actions.add_argument('--status', action='store_true', help='read the last session request without changing limits')
    actions.add_argument('--launch', action='store_true', help='launch the Waydroid client in this compositor')
    args = parser.parse_args()
    if args.status:
        state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'mwm'
        try:
            data = json.loads((state / 'gamescope-fps-limit.json').read_text())
            age = time.time() - float(data['updated'])
            if not 0 <= age <= 3:
                raise ValueError('stale')
            print(f' fps_control={data["mode"]} requested_fps={data["requested_fps"]} measured_fps={data["measured_fps"]:.2f}', end='')
        except (OSError, ValueError, KeyError, TypeError):
            print(' fps_control=inactive', end='')
        return
    launcher = None
    run_entered = False
    try:
        owner = gamescope_ancestor()
        if args.launch:
            launcher = subprocess.Popen(['waydroid', 'show-full-ui'])
        backend = Backend()
        if args.check:
            print(f'Gamescope runtime FPS control available: {backend.socket}')
            return
        if owner is None:
            raise RuntimeError('FPS control must be launched by its Gamescope session')
        cfg = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'mwm'
        state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'mwm'
        run_entered = True
        run(backend, owner, cfg, state, launcher)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        # Optional control must never prevent Waydroid from launching.
        print(f'Gamescope FPS control unavailable: {exc}', flush=True)
    finally:
        if launcher is not None:
            if not run_entered:
                launcher.wait()
            else:
                launcher.poll()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""MWM Lite: isolated direct Wayland launcher and fullscreen settings."""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
APP = 'com.bandainamcoent.imas_millionlive_theaterdays'
HELPER = '/usr/local/libexec/mwm-root-helper'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'mwm-lite/settings.json'
STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'mwm-lite'
OWNER = None

PROPS = ('width', 'height', 'multi_windows', 'fake_touch', 'width_padding', 'height_padding', 'uevent')


def call(*args):
    return subprocess.check_output(args, text=True, timeout=150).strip()


def helper(*args):
    return call('sudo', '-n', HELPER, *args)


def prop(key, value=None):
    key = 'persist.waydroid.' + key
    if value is None:
        return call('waydroid', 'prop', 'get', key)
    call('waydroid', 'prop', 'set', key, value)
    if call('waydroid', 'prop', 'get', key) != value:
        raise RuntimeError('Property verification failed: ' + key)


def boost_available():
    try:
        return all(stat.S_ISCHR(os.lstat(p).st_mode) for p in ('/dev/icc', '/dev/mp1'))
    except OSError:
        return False


def load_settings():
    data = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('Invalid Lite settings')
    result = dict(scale=3, fps=False, boost=False)
    result.update(data)
    if type(result['scale']) is not int or result['scale'] not in (1, 3, 6):
        raise ValueError('RTScale must be x1, x3 or x6')
    if any(type(result[k]) is not bool for k in ('fps', 'boost')):
        raise ValueError('Invalid Lite toggle')
    return result


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as out:
        json.dump(data, out)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def dimensions(width, height):
    if not (320 <= width <= 16384 and 240 <= height <= 16384):
        raise ValueError('Invalid primary screen geometry')
    base = round(width * 720 / height / 2) * 2
    if not 320 <= base <= 7680:
        raise ValueError('Unsupported aspect ratio')
    return base


def screen_size():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    screen = app.primaryScreen()
    if screen is None:
        raise RuntimeError('Primary screen unavailable')
    g = screen.geometry()
    return g.width(), g.height()


def owner_alive():
    if OWNER is None:
        return True
    pid, stamp = OWNER
    try:
        fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] != 'Z' and fields[19] == stamp
    except (OSError, IndexError):
        return False


def boot(check_owner=True):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if check_owner and not owner_alive():
            raise KeyboardInterrupt
        try:
            if helper('boot-completed') == '1':
                return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass  # The Android shell may not be ready just after session start.
        time.sleep(1)
    raise RuntimeError('Waydroid boot timeout')


def stop_session():
    call('waydroid', 'session', 'stop')


def stop_helpers():
    # SIGKILL cannot run parent cleanup. Recover only this installation's two
    # Lite helpers, owned by this user; never match arbitrary Python processes.
    targets = {os.fsencode(str(ROOT/name)) for name in ('lite_fps.py', 'lite_fullscreen.py')}
    owned = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = entry.joinpath('cmdline').read_bytes().split(b'\0')
            if not targets.intersection(args):
                continue
            stamp = entry.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]
            os.kill(int(entry.name), signal.SIGTERM)
            owned.append((entry, stamp))
        except (OSError, IndexError):
            pass
    deadline = time.monotonic() + 4
    while any(entry.exists() for entry, _ in owned) and time.monotonic() < deadline:
        time.sleep(.1)
    for entry, stamp in owned:
        try:
            if entry.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19] == stamp:
                os.kill(int(entry.name), signal.SIGKILL)
        except (OSError, IndexError):
            pass


def restore(journal):
    stop_helpers()
    data = json.loads(journal.read_text())
    boost_error = None
    if data.get('boost_requested'):
        try:
            helper('ps5-boost', 'off')
        except Exception as error:
            boost_error = error
    stop_session()
    helper('container-stop')
    helper('container-start')
    session = subprocess.Popen(['waydroid', 'session', 'start'])
    try:
        boot(check_owner=False)
        helper('force-stop-app')
        for key in PROPS:
            prop(key, data['props'][key])
        helper('lite-rtscale-restore')
    finally:
        stop_session()
        session.wait(timeout=20)
        helper('container-stop')
    if boost_error is not None:
        raise RuntimeError('PS5 Boost OFF failed; recovery remains pending') from boost_error
    journal.unlink()


def run(recover=False):
    # Share the established Desktop operation/config locks for the entire
    # session, including cleanup. Desktop cannot refresh underneath Lite.
    paths = [Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'mwm-config.lock',
             STATE.parent/'mwm/waydroid-control.lock']
    with ExitStack() as stack:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_locked(recover)


def run_locked(recover=False):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE/'session.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = STATE/'restore.json'
        if journal.exists():
            if not recover:
                raise RuntimeError('Interrupted Lite session: run mwm-lite --recover')
            restore(journal)
            return
        if recover:
            return
        settings = load_settings()
        width, height = screen_size()
        base = dimensions(width, height)
        if 'RUNNING' in call('waydroid', 'status').upper():
            raise RuntimeError('Stop Desktop MWM / Waydroid before launching Lite')
        if not os.environ.get('WAYLAND_DISPLAY'):
            raise RuntimeError('Lite requires Wayland')
        boost_enabled = settings['boost'] and boost_available()
        if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper() and not shutil.which('kdotool'):
            raise RuntimeError('Plasma fullscreen requires kdotool')
        children = []
        watched = []
        def interrupted(_signal, _frame):
            raise KeyboardInterrupt
        previous = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            helper('container-start')
            children.append(subprocess.Popen(['waydroid', 'session', 'start']))
            boot()
            original = {key: prop(key) for key in PROPS}
            # Journal precedes backup; restore helper is idempotent when no
            # backup exists. An incomplete backup fails closed. No runtime writes
            # precede the backup.
            save_json(journal, {'props': original, 'boost_requested': boost_enabled})
            helper('lite-rtscale-save')
            helper('force-stop-app')
            values = dict(width=str(width), height=str(height), multi_windows='false', fake_touch=APP,
                          width_padding='', height_padding='', uevent='false')
            for key, value in values.items():
                prop(key, value)
            helper('rtscale-write', str(settings['scale']), str(base), '720', '1', '1')
            stop_session()
            children[0].wait(timeout=20)
            helper('container-stop')
            helper('container-start')
            children.append(subprocess.Popen(['waydroid', 'session', 'start']))
            boot()
            if boost_available():
                helper('ps5-boost', 'on' if boost_enabled else 'off')
            watched.append(children[-1])
            if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper():
                children.append(subprocess.Popen([sys.executable, str(ROOT/'lite_fullscreen.py')]))
                watched.append(children[-1])
            children.append(subprocess.Popen(['waydroid', 'show-full-ui']))
            call('waydroid', 'app', 'launch', APP)
            if settings['fps']:
                children.append(subprocess.Popen([sys.executable, str(ROOT/'lite_fps.py')]))
                watched.append(children[-1])
            started = False
            deadline = time.monotonic() + 40
            while True:
                if not owner_alive():
                    raise KeyboardInterrupt
                running = bool(helper('pidof-mirishita'))
                started |= running
                if started and not running:
                    break
                if not started and time.monotonic() > deadline:
                    raise RuntimeError('Mirishita launch timeout')
                if any(child.poll() is not None for child in watched):
                    raise RuntimeError('Lite display or overlay process exited')
                time.sleep(1)
        finally:
            for s in previous:
                signal.signal(s, signal.SIG_IGN)
            try:
                for child in reversed(children):
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                if journal.exists():
                    restore(journal)
                else:
                    stop_session()
                    helper('container-stop')
            finally:
                for s, handler in previous.items():
                    signal.signal(s, handler)


def settings_ui():
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle('MWM Lite Settings')
    window.setScreen(app.primaryScreen())
    window.setStyleSheet('QWidget { font-size: 26px; } QPushButton, QComboBox { padding: 14px; } QCheckBox::indicator { width: 28px; height: 28px; }')
    layout = QVBoxLayout(window)
    layout.setContentsMargins(48, 40, 48, 40)
    layout.setSpacing(24)
    layout.addWidget(QLabel('MWM Lite Settings'))
    layout.addWidget(QLabel('RTScale — applies at next game launch'))
    data = load_settings()
    scale = QComboBox()
    for label, value in (('x3 (Standard)', 3), ('x6', 6), ('x1 (Recovery)', 1)):
        scale.addItem(label, value)
    scale.setCurrentIndex(scale.findData(data['scale']))
    layout.addWidget(scale)
    fps = QCheckBox('FPS Counter')
    fps.setChecked(data['fps'])
    layout.addWidget(fps)
    boost = QCheckBox('PS5 Boost Mode')
    boost.setChecked(data['boost'] and boost_available())
    boost.setEnabled(boost_available())
    layout.addWidget(boost)
    instructions = QLabel('Steam Input: use a mouse / keyboard layout. Exit through the Steam menu. PS5 Boost changes system clocks; fan cooling stays enabled after exit.')
    instructions.setWordWrap(True)
    layout.addWidget(instructions)
    save = QPushButton('Save && Close')
    def commit():
        try:
            save_json(CONFIG, dict(scale=scale.currentData(), fps=fps.isChecked(), boost=boost.isChecked() and boost_available()))
            window.close()
        except OSError as error:
            QMessageBox.critical(window, 'MWM Lite', str(error))
    save.clicked.connect(commit)
    layout.addWidget(save)
    window.showFullScreen()
    return app.exec()


def run_supervised():
    # Steam force-kills tracked descendants, including restoration commands.
    # A user service owns Waydroid and cleanup outside Steam's process tree;
    # it watches this small tracked launcher to notice even a SIGKILL.
    STATE.mkdir(parents=True, exist_ok=True)
    stamp = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    unit = 'mwm-lite-session'
    command = ['systemd-run', '--user', '--wait', '--collect', '--quiet',
               '--unit='+unit, '--property=TimeoutStopSec=180',
               '--property=KillMode=mixed',
               '--property=StandardOutput=append:'+str(STATE/'session.log'),
               '--property=StandardError=append:'+str(STATE/'session.log')]
    for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'XAUTHORITY', 'XDG_CURRENT_DESKTOP',
                'XDG_SESSION_TYPE', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME',
                'SteamAppId', 'SteamGameId', 'SteamOverlayGameId'):
        if key in os.environ:
            command.append('--setenv='+key+'='+os.environ[key])
    # Use the same known-working interpreter, without Steam's preload / Qt
    # library environment. The service manager supplies a clean session PATH.
    command += [sys.executable, str(ROOT/'lite.py'), '--session-owner', str(os.getpid())+':'+stamp]
    wait = subprocess.Popen(command)
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return wait.wait()
    finally:
        if wait.poll() is None:
            subprocess.run(['systemctl', '--user', 'stop', '--no-block', unit], timeout=5, check=False)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--settings', action='store_true')
    mode.add_argument('--recover', action='store_true')
    mode.add_argument('--session-owner', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.settings:
            return settings_ui()
        if args.session_owner:
            global OWNER
            pid, stamp = args.session_owner.split(':', 1)
            if not pid.isdecimal() or not stamp.isdecimal():
                raise ValueError('Invalid session owner')
            OWNER = (int(pid), stamp)
            return run()
        return run(True) if args.recover else run_supervised()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        message = 'MWM Lite: ' + str(error)
        print(message, file=sys.stderr)
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            with (STATE/'errors.log').open('a') as log:
                log.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')
        except OSError:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())

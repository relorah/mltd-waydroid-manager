#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Experimental outer Gamescope capture; never stitches desktop screenshots."""
import datetime
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time


def string(value):
    data = value.encode() + b'\0'
    return struct.pack('<I', len(data)) + data + b'\0' * (-len(data) % 4)


def message(obj, opcode, data=b''):
    return struct.pack('<II', obj, ((8 + len(data)) << 16) | opcode) + data


def request_capture(path):
    """Bind Gamescope control v3 on the OUTER compositor's private socket."""
    display = os.environ['GAMESCOPE_WAYLAND_DISPLAY']
    address = display if display.startswith('/') else str(Path(os.environ['XDG_RUNTIME_DIR']) / display)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(address)
        client.sendall(message(1, 1, struct.pack('<I', 2)) + message(1, 0, struct.pack('<I', 3)))
        pending = b''
        control = None
        done = False
        while not done:
            data = client.recv(65536)
            if not data:
                raise RuntimeError('Gamescope closed the control socket')
            pending += data
            while len(pending) >= 8:
                obj, header = struct.unpack_from('<II', pending)
                size, opcode = header >> 16, header & 65535
                if size < 8:
                    raise RuntimeError('Invalid Wayland message')
                if len(pending) < size:
                    break
                body, pending = pending[8:size], pending[size:]
                if obj == 1 and opcode == 0:
                    raise RuntimeError('Gamescope rejected the control request')
                if obj == 2 and opcode == 0:
                    name, length = struct.unpack_from('<II', body)
                    interface = body[8:8 + length].rstrip(b'\0')
                    version = struct.unpack_from('<I', body, 8 + ((length + 3) & ~3))[0]
                    if interface == b'gamescope_control' and version >= 3:
                        control = name
                if obj == 3 and opcode == 0:
                    done = True
        if control is None:
            raise RuntimeError('Gamescope control v3 screenshot support unavailable')
        bind = struct.pack('<I', control) + string('gamescope_control') + struct.pack('<II', 3, 4)
        client.sendall(message(2, 0, bind) + message(4, 2, string(str(path)) + struct.pack('<II', 3, 0)))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size > 24:
                with path.open('rb') as image:
                    header = image.read(24)
                if header[:8] == b'\x89PNG\r\n\x1a\n':
                    with path.open('rb') as image:
                        image.seek(-12, 2)
                        complete = image.read() == b'\x00\x00\x00\x00IEND\xaeB`\x82'
                    if complete:
                        return struct.unpack('>II', header[16:24])
            time.sleep(.1)
        raise RuntimeError('Screenshot timed out; inspect Gamescope log')


def pictures_dir():
    try:
        value = subprocess.check_output(['xdg-user-dir', 'PICTURES'], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        value = ''
    return (Path(value) if value and Path(value).is_absolute() else Path.home() / 'Pictures') / 'MWM'


def capture(state):
    folder = pictures_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.png')
    width, height = request_capture(path)
    print(f'Screenshot saved: {path} ({width}x{height})', flush=True)
    subprocess.Popen(['notify-send', 'MWM Screenshot', f'Saved {width}×{height}: {path.name}']) if __import__('shutil').which('notify-send') else None


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def gamescope_ancestor(start_pid=None):
    pid = os.getppid() if start_pid is None else start_pid
    outer = None
    for _ in range(32):
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
            if Path(f'/proc/{pid}/exe').resolve().name == 'gamescope':
                outer = pid
            pid = int(fields[1])
            if pid <= 1:
                break
        except (OSError, IndexError, ValueError):
            break
    if outer is not None:
        return outer
    raise RuntimeError('Could not identify the owning Gamescope process')


def enabled(config):
    try:
        return (config / 'f12-screenshot-enabled').read_text().strip() == 'on'
    except OSError:
        return False


def shortcut_script(pid):
    # Match the compositor process, not a generic Gamescope window/class.
    return '''var accepted = registerShortcut("MWM F12 Screenshot", "MWM F12 Screenshot", "F12", function () {
    var w = workspace.activeWindow;
    callDBus("org.mwm.Screenshot", "/Screenshot", "org.mwm.Screenshot", "ShortcutObserved",
        JSON.stringify({pid:w?Number(w.pid):0, minimized:w?!!w.minimized:false}));
    if (w && Number(w.pid) === %d && !w.minimized) {
        callDBus("org.mwm.Screenshot", "/Screenshot", "org.mwm.Screenshot", "Capture");
    }
});
callDBus("org.mwm.Screenshot", "/Screenshot", "org.mwm.Screenshot", "ShortcutReady", accepted);
''' % pid


def main():
    import signal
    import threading
    import shutil
    from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot, ClassInfo
    from PySide6.QtDBus import QDBusConnection

    owner = int(sys.argv[1])
    identity = process_identity(owner)
    target = gamescope_ancestor(owner)
    target_identity = process_identity(target)
    if identity is None or target_identity is None:
        raise RuntimeError('Gamescope session has already exited')
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'mwm'
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'mwm'
    state.mkdir(parents=True, exist_ok=True)
    status_path = state / 'screenshot-status.json'
    script_path = state / 'screenshot-shortcut.js'
    dbus = shutil.which('qdbus6') or shutil.which('qdbus')
    app = QCoreApplication(sys.argv)
    bus = QDBusConnection.sessionBus()
    if not bus.registerService('org.mwm.Screenshot'):
        raise RuntimeError('Screenshot listener already running, or session D-Bus unavailable')

    def status(text):
        print(text, flush=True)
        temp = status_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'pid': os.getpid(), 'owner': owner, 'message': text}), encoding='utf-8')
        os.replace(temp, status_path)

    def kwin(method, *args):
        if not dbus:
            raise RuntimeError('qdbus6/qdbus unavailable; KDE Plasma is required for F12')
        return subprocess.check_output([dbus, 'org.kde.KWin', '/Scripting',
                                        'org.kde.kwin.Scripting.' + method, *args],
                                       text=True, stderr=subprocess.STDOUT, timeout=3).strip()

    busy = threading.Lock()

    @ClassInfo(**{'D-Bus Interface': 'org.mwm.Screenshot'})
    class Receiver(QObject):
        @Slot(bool)
        def ShortcutReady(self, accepted):
            if not enabled(config):
                return
            status('F12: enabled (KDE shortcut; focused MWM game only)' if accepted else
                   'F12 unavailable: shortcut registration refused; check Plasma Shortcuts')

        @Slot(str)
        def ShortcutObserved(self, details):
            print(f'F12 received: target={target} active={details}', flush=True)

        @Slot()
        def Capture(self):
            if (not enabled(config) or
                    process_identity(target) != target_identity or not busy.acquire(False)):
                return

            def work():
                try:
                    capture(state)
                except Exception as error:
                    print(f'Screenshot failed: {error}', flush=True)
                    if shutil.which('notify-send'):
                        subprocess.Popen(['notify-send', 'MWM Screenshot failed', str(error)])
                finally:
                    busy.release()
            threading.Thread(target=work, daemon=True).start()

    receiver = Receiver()
    if not bus.registerObject('/Screenshot', receiver, QDBusConnection.RegisterOption.ExportAllSlots):
        bus.unregisterService('org.mwm.Screenshot')
        raise RuntimeError('Could not register screenshot receiver')

    loaded = False
    last_attempt = 0.0
    previous_error = None

    def unload():
        nonlocal loaded
        # Unload on OFF as well as exit, releasing the live shortcut action.
        result = kwin('unloadScript', 'mwm-f12-screenshot')
        if result.lower() not in ('true', 'false', ''):
            raise RuntimeError('Unexpected KWin unload result: ' + result)
        loaded = False

    def tick():
        nonlocal loaded, last_attempt, previous_error
        if process_identity(owner) != identity or process_identity(target) != target_identity:
            app.quit()
            return
        wanted = enabled(config)
        if wanted == loaded:
            return
        if time.monotonic() - last_attempt < 3:
            return
        last_attempt = time.monotonic()
        try:
            if wanted:
                # Clean up a script left by an interrupted previous session.
                unload()
                script_path.write_text(shortcut_script(target), encoding='utf-8')
                script_id = int(kwin('loadScript', str(script_path), 'mwm-f12-screenshot'))
                if script_id < 0:
                    raise RuntimeError('KWin refused F12 shortcut script')
                subprocess.check_output([dbus, 'org.kde.KWin', f'/Scripting/Script{script_id}',
                                         'org.kde.kwin.Script.run'], text=True,
                                        stderr=subprocess.STDOUT, timeout=3)
                loaded = True
                status('F12: shortcut requested; waiting for KDE')
            else:
                unload()
                status('F12: off')
            previous_error = None
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as error:
            text = 'F12 unavailable: ' + str(error)
            if text != previous_error:
                status(text)
                previous_error = text
            # A failed run may still have loaded a script. Do not leave it active.
            if wanted:
                try:
                    unload()
                except Exception:
                    pass

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(250)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    status('F12: waiting for Apply' if not enabled(config) else 'F12: initializing')
    try:
        try:
            unload()
        except Exception as error:
            status('F12: KDE shortcut initialization unavailable: ' + str(error))
        tick()
        app.exec()
    finally:
        try:
            unload()
        except Exception as error:
            print('F12 cleanup: ' + str(error), flush=True)
        bus.unregisterObject('/Screenshot')
        bus.unregisterService('org.mwm.Screenshot')
        script_path.unlink(missing_ok=True)
        status_path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'F12 Screenshot unavailable: {error}', flush=True)

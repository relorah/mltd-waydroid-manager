# SPDX-License-Identifier: MIT
"""Conservative native Steam shortcut registration; no Steam account settings."""
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shlex
import struct
import tempfile
import time
import zlib

TITLES = (('Mirishita (MWM Lite)', 'mwm-lite'), ('MWM Lite Settings', 'mwm-lite-settings'))
MAX_BYTES = 16 * 1024 * 1024


@dataclass
class Value:
    kind: int
    data: object


def decode(raw):
    """Retain scalar type/bytes and order, so unrelated entries round-trip."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Steam shortcuts file is too large')
    position = 0
    def take(size):
        nonlocal position
        if position + size > len(raw):
            raise ValueError('Truncated Steam shortcuts file')
        result = raw[position:position+size]
        position += size
        return result
    def string():
        nonlocal position
        end = raw.find(b'\0', position)
        if end < 0:
            raise ValueError('Unterminated Steam string')
        result = raw[position:end].decode('utf-8', 'surrogateescape')
        position = end + 1
        return result
    def obj(depth=0):
        if depth > 32:
            raise ValueError('Steam shortcuts nesting limit')
        result = {}
        while True:
            kind = take(1)[0]
            if kind == 8:
                return result
            key = string()
            if key in result:
                raise ValueError('Duplicate Steam key; file was not changed')
            if kind == 0:
                data = obj(depth+1)
            elif kind == 1:
                data = string()
            elif kind in (2, 3, 4, 6):
                data = take(4)
            elif kind in (7, 10):
                data = take(8)
            else:
                raise ValueError('Unsupported Steam field type; file was not changed')
            result[key] = Value(kind, data)
    result = obj()
    if position != len(raw):
        raise ValueError('Trailing Steam shortcuts data; file was not changed')
    if 'shortcuts' not in result or result['shortcuts'].kind != 0:
        raise ValueError('Steam shortcuts root is missing')
    return result


def encode(data):
    def string(value):
        if '\0' in value:
            raise ValueError('NUL in Steam field')
        return value.encode('utf-8', 'surrogateescape') + b'\0'
    result = bytearray()
    for key, value in data.items():
        result += bytes([value.kind]) + string(key)
        if value.kind == 0:
            result += encode(value.data)
        elif value.kind == 1:
            result += string(value.data)
        else:
            result += value.data
    return bytes(result) + b'\x08'


def text(value):
    return Value(1, str(value))


def integer(value):
    return Value(2, struct.pack('<I', value & 0xffffffff))


def app_id(executable, title):
    return zlib.crc32((executable+title).encode()) | 0x80000000


def number(value):
    if value.kind != 2 or len(value.data) != 4:
        raise ValueError('Invalid Steam AppID')
    return struct.unpack('<I', value.data)[0]


def process_running():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid == os.getuid() and entry.joinpath('comm').read_text().strip() == 'steam':
                return True
        except OSError:
            pass
    return False


def accounts(home=None):
    home = Path(home or Path.home())
    roots = [home/'.local/share/Steam', home/'.steam/steam', home/'.steam/debian-installation']
    result = []
    seen = set()
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        userdata = root/'userdata'
        if not userdata.is_dir():
            continue
        for folder in sorted(userdata.iterdir()):
            if folder.is_dir() and folder.name.isdecimal() and folder.name != '0':
                result.append((root, folder.name))
    return result


def update_document(document, bin_dir):
    entries = document['shortcuts'].data
    ids = {}
    changed = False
    for title, program in TITLES:
        path = Path(bin_dir)/program
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('Install MWM Lite before registering Steam shortcuts: '+str(path))
        quoted = '"'+str(path)+'"'
        candidates = []
        for entry in entries.values():
            if entry.kind != 0:
                raise ValueError('Invalid Steam shortcut entry')
            fields = entry.data
            exe = fields.get('exe', text(''))
            name = fields.get('appname', fields.get('AppName', text('')))
            if exe.kind != 1 or name.kind != 1:
                raise ValueError('Invalid Steam shortcut fields')
            try:
                parts = shlex.split(exe.data)
            except ValueError:
                parts = []
            if len(parts) == 1 and (parts[0] == str(path) or
                    (name.data == title and Path(parts[0]).name == program)):
                candidates.append(fields)
            elif name.data == title:
                raise ValueError('A different Steam shortcut already uses '+title)
        if len(candidates) > 1:
            raise ValueError('Duplicate Lite shortcuts; resolve them in Steam first')
        if candidates:
            fields = candidates[0]
            # Keep AppID, custom titles, arguments, artwork and input bindings.
            for key, value in (('exe', quoted), ('StartDir', '"'+str(Path(bin_dir))+'"')):
                if fields.get(key) != text(value):
                    fields[key] = text(value)
                    changed = True
        else:
            identifier = app_id(quoted, title)
            fields = {key: text(value) for key, value in dict(appname=title, exe=quoted,
                StartDir='"'+str(Path(bin_dir))+'"', icon='', ShortcutPath='', LaunchOptions='',
                DevkitGameID='').items()}
            fields.update({key: integer(value) for key, value in dict(appid=identifier, IsHidden=0,
                AllowDesktopConfig=1, AllowOverlay=1, OpenVR=0, Devkit=0, LastPlayTime=0).items()})
            fields['tags'] = Value(0, {})
            index = max([int(key) for key in entries if key.isdecimal()] + [-1]) + 1
            entries[str(index)] = Value(0, fields)
            changed = True
        ids[program] = number(fields['appid'])
    return ids, changed


def atomic_write(path, raw):
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def register(root, user_id, bin_dir, state):
    if not str(user_id).isdecimal() or str(user_id) == '0':
        raise ValueError('Invalid Steam user ID')
    folder = Path(root)/'userdata'/str(user_id)/'config'
    if not folder.parent.is_dir():
        raise ValueError('Launch Steam and sign in once before registering')
    folder.mkdir(exist_ok=True)
    path = folder/'shortcuts.vdf'
    if path.is_symlink() or folder.stat().st_uid != os.getuid():
        raise ValueError('Steam configuration ownership/path could not be verified')
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with (state/'steam-registration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = path.read_bytes() if path.exists() else None
        document = decode(original) if original is not None else {'shortcuts': Value(0, {})}
        ids, changed = update_document(document, bin_dir)
        if not changed:
            return {'changed': False, 'ids': ids, 'backup': None}
        if process_running():
            raise ValueError('Exit Steam completely before registering. Existing shortcuts were not changed.')
        result = encode(document)
        if decode(result) != document:
            raise ValueError('Steam shortcut validation failed')
        backup = None
        if original is not None:
            backups = state/'steam-backups'
            backups.mkdir(exist_ok=True)
            backup = backups/(str(time.time_ns())+'-'+str(user_id)+'-shortcuts.vdf')
            atomic_write(backup, original)
        # Never overwrite a concurrent Steam/tool edit.
        if process_running() or (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('Steam configuration changed concurrently; registration cancelled')
        atomic_write(path, result)
        return {'changed': True, 'ids': ids, 'backup': str(backup) if backup else None}

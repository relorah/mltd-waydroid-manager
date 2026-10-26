# SPDX-License-Identifier: MIT
"""Desktop integration used identically by Ubuntu and CachyOS Lite sessions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

UUID = 'mwm-lite-fullscreen@relorah.github.io'


def desktop_kind():
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    if os.environ.get('XDG_SESSION_DESKTOP','').lower() in ('gamescope','steam') or os.environ.get('GAMESCOPE_WAYLAND_DISPLAY'):
        return 'steam'
    if 'KDE' in desktop:
        return 'plasma'
    if 'GNOME' in desktop or 'UBUNTU' in desktop:
        return 'gnome'
    return 'other'


def gnome_ready():
    if not shutil.which('gnome-extensions'):
        return False
    result = subprocess.run(['gnome-extensions','info',UUID],text=True,capture_output=True,
                            timeout=5,env={**os.environ,'LC_ALL':'C'})
    return result.returncode == 0 and any(line.strip() in ('State: ENABLED','State: ACTIVE') for line in result.stdout.splitlines())


def check_fullscreen():
    kind = desktop_kind()
    if kind == 'plasma' and not shutil.which('kdotool'):
        raise RuntimeError('Plasma fullscreen requires kdotool')
    if kind == 'gnome' and not gnome_ready():
        raise RuntimeError('Open MWM Lite Steam Setup and enable GNOME fullscreen support. After first installation, log out and back in, then enable the extension.')
    if kind == 'other':
        raise RuntimeError('Use Plasma Wayland, GNOME with MWM Lite Fullscreen, or a Steam game session')
    return kind


def install_gnome_extension(source):
    metadata = json.loads((Path(source)/'metadata.json').read_text())
    if metadata.get('uuid') != UUID:
        raise ValueError('Invalid MWM Lite GNOME extension metadata')
    destination = Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'gnome-shell/extensions'/UUID
    destination.mkdir(parents=True,exist_ok=True)
    if destination.is_symlink():
        raise ValueError('GNOME extension directory must not be a symbolic link')
    # Only two project-owned files; no shell commands or user input at root.
    for name in ('metadata.json','extension.js'):
        raw = (Path(source)/name).read_bytes()
        fd, temporary = tempfile.mkstemp(prefix='.'+name,dir=destination)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(raw)
            os.chmod(temporary,0o644)
            os.replace(temporary,destination/name)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if shutil.which('gnome-extensions'):
        subprocess.run(['gnome-extensions','enable',UUID],capture_output=True,timeout=5)
    return gnome_ready()


def remove_gnome_extension(source):
    destination = Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'gnome-shell/extensions'/UUID
    if not destination.exists():
        return
    if destination.is_symlink():
        raise ValueError('GNOME extension directory must not be a symbolic link')
    if shutil.which('gnome-extensions'):
        subprocess.run(['gnome-extensions','disable',UUID],capture_output=True,timeout=5)
    for name in ('metadata.json','extension.js'):
        target = destination/name
        if target.is_file() and not target.is_symlink() and target.read_bytes() == (Path(source)/name).read_bytes():
            target.unlink()
    if not any(destination.iterdir()):
        destination.rmdir()

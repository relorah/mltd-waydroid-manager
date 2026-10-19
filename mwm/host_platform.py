# SPDX-License-Identifier: MIT
"""Host feature restrictions shared by the GUI and runtime controller."""
import platform
import os
from pathlib import Path
import shutil
import subprocess


def is_ubuntu():
    try:
        return platform.freedesktop_os_release().get('ID') == 'ubuntu'
    except OSError:
        return False


def mangoapp_program(root, name='mangoapp'):
    if name not in ('mangoapp', 'mangohudctl'):
        raise ValueError('Unsupported MangoApp program')
    if is_ubuntu():
        path = Path(root) / '.runtime/bin' / name
    else:
        found = shutil.which(name)
        if not found:
            return None
        path = Path(found)
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    if not is_ubuntu():
        return path
    try:
        result = subprocess.run(['ldd', str(path)], capture_output=True, text=True,
                                timeout=5, env={**os.environ, 'LC_ALL': 'C'})
        if result.returncode or 'not found' in result.stdout + result.stderr:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return path

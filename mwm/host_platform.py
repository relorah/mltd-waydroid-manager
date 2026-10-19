# SPDX-License-Identifier: MIT
"""Host feature restrictions shared by the GUI and runtime controller."""
import platform


def is_ubuntu():
    try:
        return platform.freedesktop_os_release().get('ID') == 'ubuntu'
    except OSError:
        return False

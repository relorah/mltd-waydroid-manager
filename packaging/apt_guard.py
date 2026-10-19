#!/usr/bin/env python3
"""Reject protected host-stack packages in APT plans and actual deb inputs.

Default is APT Pre-Install-Pkgs protocol version 1 (one .deb path per line).
A hook failure aborts APT before dpkg; --no-remove separately forbids removals.
"""
import re
import subprocess
import sys


def protected(name):
    name = name.split(':', 1)[0].lower()
    if name in ('libglfw3', 'libglfw3-dev', 'libglx-dev', 'libgl-dev', 'libegl-dev', 'libglvnd-dev', 'libdrm-dev', 'libgbm-dev', 'libvulkan-dev', 'libopengl-dev', 'libgles-dev'):
        return False
    return (name.startswith(('linux-', 'kernel', 'firmware-', 'linuxfirmware',
                             'amdgpu', 'rocm', 'libdrm', 'libllvm', 'llvm-',
                             'libgl', 'libegl', 'libgbm', 'libvulkan',
                             'xserver-xorg-video-', 'vulkan-'))
            or any(word in name for word in ('mesa', 'ps5', 'firmware')))


def validate_plan(lines):
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if fields[0] in ('Remv', 'Purg'):
            raise ValueError('APT removal rejected: ' + line.rstrip())
        if fields[0] in ('Inst', 'Conf') and (len(fields) < 2 or protected(fields[1])):
            raise ValueError('Protected package rejected: ' + line.rstrip())


def main():
    if sys.argv[1:] == ['--plan']:
        validate_plan(sys.stdin)
        return
    if sys.argv[1:]:
        raise ValueError('Unsupported hook arguments')
    for line in sys.stdin:
        path = line.rstrip('\n')
        if not path:
            continue
        if not path.startswith('/') or not path.endswith('.deb'):
            raise ValueError('Unexpected APT hook protocol: ' + path)
        name = subprocess.check_output(
            ['dpkg-deb', '--field', path, 'Package'], text=True).strip()
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', name) or protected(name):
            raise ValueError('Protected/invalid package rejected: ' + name)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('MWI APT guard: ' + str(exc), file=sys.stderr)
        sys.exit(1)

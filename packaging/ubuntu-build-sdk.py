#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract Ubuntu build dependencies privately; never install host packages."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig

PACKAGES = '''build-essential meson ninja-build pkg-config python3-mako git
libgl-dev libegl-dev libglfw3-dev libx11-dev libxrandr-dev libwayland-dev libxkbcommon-dev
libdbus-1-dev libdrm-dev glslang-tools patchelf'''.split()


def candidates(plan):
    result = []
    for line in plan.splitlines():
        if line.startswith(('Remv ', 'Purg ')):
            raise ValueError('Build dependency resolution requests removals')
        if not line.startswith('Inst '):
            continue
        match = re.match(r'^Inst ([a-z0-9][a-z0-9+.:_-]*) (?:\[[^]]+\] )?\(([^ ]+)', line)
        if not match:
            raise ValueError('Unknown APT simulation row: ' + line)
        result.append(match[1] + '=' + match[2])
    return result


def prepare(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'LC_ALL': 'C'}
    plan = subprocess.check_output(['apt-get', '--simulate', '--no-remove', '--no-upgrade',
                                   '--no-install-recommends', 'install', *PACKAGES], text=True, env=env)
    wanted = candidates(plan)
    revision = hashlib.sha256(plan.encode()).hexdigest()[:16]
    directory = directory / revision
    directory.mkdir(parents=True, exist_ok=True)
    debs = directory / 'debs'; debs.mkdir(exist_ok=True)
    root = directory / 'root'; root.mkdir(exist_ok=True)
    if wanted:
        subprocess.run(['apt-get', 'download', *wanted], cwd=debs, env=env, check=True, stdout=sys.stderr)
    records = []
    for deb in sorted(debs.glob('*.deb')):
        subprocess.run(['dpkg-deb', '-x', str(deb), str(root)], check=True)
        records.append({'file': deb.name, 'sha256': hashlib.sha256(deb.read_bytes()).hexdigest()})
    # Development linker symlinks may target libraries already on the host.
    # Add links only inside the private SDK; never alter /usr.
    multiarch = sysconfig.get_config_var('MULTIARCH')
    if not multiarch or not re.fullmatch(r'[a-zA-Z0-9_-]+', multiarch):
        raise RuntimeError('Python did not report a valid native library architecture')
    for link in (root / 'usr/lib' / multiarch).glob('*.so'):
        if link.is_symlink() and not link.exists():
            target = (link.parent / os.readlink(link)).resolve()
            host = Path('/usr/lib') / multiarch / target.name
            if target.is_relative_to(root) and host.exists() and not target.exists():
                target.symlink_to(host)
    (directory / 'apt-plan.txt').write_text(plan)
    (directory / 'packages.json').write_text(json.dumps(records, indent=2))
    print('Ubuntu build SDK: ' + str(root), file=sys.stderr)
    return root


if __name__ == '__main__':
    if os.geteuid() == 0:
        raise SystemExit('Build SDK must run as the desktop user')
    print(prepare(sys.argv[1]))

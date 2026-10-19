#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve host-compatible renderer/control binaries without starting a GUI."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from host_platform import mangoapp_program

if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) == 2 else 'mangoapp'
    path = mangoapp_program(ROOT, name)
    if path is None:
        sys.exit(1)
    print(path)

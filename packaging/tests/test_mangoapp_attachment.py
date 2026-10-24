"""MangoApp uses the managed live attach path instead of Gamescope respawns."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]

class AttachmentTests(unittest.TestCase):
    def test_modes(self):
        source = (ROOT/'mwm/scripts/gamescope-control.sh').read_text()
        function = 'launch_outer() {' + source.split('launch_outer() {',1)[1].split('\nouter_backend()',1)[0]
        for mode in ('off','minimal','detailed','mangoapp'):
            for dual in (False,True):
                with self.subTest(mode=mode,dual=dual), tempfile.TemporaryDirectory() as directory:
                    script = '''set -eu
gamescope() { printf '%s\n' '--mangoapp'; }
mangoapp() { :; }
setsid() { printf '%s\n' "$@" > "$CALLS"; }
''' + function + '\nlaunch_outer off "$MODE" gamescope ' + ('-- bash mwm-inner --backend sdl' if dual else '--backend wayland') + '\nwait\n'
                    env = dict(os.environ,MODE=mode,STATE_DIR=directory,SCRIPT_DIR=directory,LOG_FILE=directory+'/log',RUN_EXIT_FILE=directory+'/exit',CALLS=directory+'/calls')
                    subprocess.run(['bash','-c',script],env=env,check=True,capture_output=True)
                    args = Path(directory+'/calls').read_text().splitlines()
                    self.assertEqual(args.count('--mangoapp'),0)
                    self.assertEqual(Path(directory+'/mangoapp-active').exists(), mode=='mangoapp')

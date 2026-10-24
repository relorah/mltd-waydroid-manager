"""The game shortcut initializes Gamescope and reuses a live display."""
from pathlib import Path
import os,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
class LauncherTests(unittest.TestCase):
    def test_fresh_running_and_stopped_settings(self):
        for running in (True,False):
            with self.subTest(running=running),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);scripts=root/'scripts';scripts.mkdir();bin_=root/'bin';bin_.mkdir()
                shutil.copy2(ROOT/'mwm/scripts/launch-mirishita.sh',scripts/'launch-mirishita.sh')
                (scripts/'gamescope-control.sh').write_text('#!/bin/bash\necho '+('running pid=123' if running else 'stopped')+'\n')
                (scripts/'waydroid-control.sh').write_text('#!/bin/bash\necho "$1" >> "$CALLS"\n')
                p=bin_/'waydroid';p.write_text('#!/bin/bash\necho "Session: RUNNING"\n');p.chmod(0o755)
                env=dict(os.environ,XDG_CONFIG_HOME=str(root/'cfg'),XDG_STATE_HOME=str(root/'state'),CALLS=str(root/'calls'),PATH=str(bin_)+':'+os.environ['PATH'])
                subprocess.run(['bash',str(scripts/'launch-mirishita.sh')],env=env,check=True)
                self.assertEqual((root/'cfg/mwm/display-backend').read_text().strip(),'gamescope')
                self.assertEqual((root/'calls').read_text().splitlines(),['launch'] if running else ['start','launch'])
                existing=root/'cfg/mwm/aspect-ratio';existing.write_text('32:9\n')
                subprocess.run(['bash',str(scripts/'launch-mirishita.sh')],env=env,check=True)
                self.assertEqual(existing.read_text(),'32:9\n')

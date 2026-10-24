"""Exercise the actual shell startup policy without starting a compositor."""
from pathlib import Path
import subprocess,unittest
ROOT=Path(__file__).parents[2]
class StartupWindowModeTests(unittest.TestCase):
 def test_dual_is_windowed_on_native_wayland_and_single_stays_fullscreen(self):
  text=(ROOT/'mwm/scripts/gamescope-control.sh').read_text()
  window=text.split('read_window_mode() {',1)[1].split('\n\nread_fg_mode()',1)[0]
  backend=text.split('outer_backend() {',1)[1].split('\n\n# Request',1)[0]
  for enabled,expected in [('0','windowed\nwayland'),('1','fullscreen\nwayland')]:
   script='gamescope_span_enabled() { return '+enabled+'; }\nread_window_mode() {'+window+'\nouter_backend() {'+backend+'\nread_window_mode\nouter_backend off'
   self.assertEqual(subprocess.check_output(['bash','-c',script],text=True).strip(),expected)
if __name__=='__main__':unittest.main()

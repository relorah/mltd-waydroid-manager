import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/"mwm"))
from hud_position import monitor_position
class HUDPositionTests(unittest.TestCase):
    def test_window_on_nonprimary_and_negative_coordinates(self):
        rects=[(0,0,1920,1080),(-2560,-200,2560,1440)]
        self.assertEqual(monitor_position(rects,-2300,-100,200,150),(1,260,100))
        self.assertEqual(monitor_position(rects,100,200,200,150),(0,100,200))
    def test_three_monitors_and_desktop_gap(self):
        rects=[(0,0,2451,1379),(2452,90,2133,1200),(4585,0,1920,1080)]
        self.assertEqual(monitor_position(rects,4600,10,200,150),(2,15,10))
        self.assertEqual(monitor_position(rects,2462,10,200,150),(1,10,0))
    def test_clamp_and_empty(self):
        self.assertEqual(monitor_position([(0,0,1920,1080)],1910,1070,200,150),(0,1720,930))
        with self.assertRaises(ValueError):monitor_position([],0,0,200,150)

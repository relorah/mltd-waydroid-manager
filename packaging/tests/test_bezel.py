import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/'mwm'))
from bezel import display_plan,shader,fingerprint
from settings_safety import validate

def output(name,x,y,w,h,mm):
 return dict(name=name,enabled=True,connected=True,size=dict(width=w,height=h),pos=dict(x=x,y=y),scale=1,physical_mm=mm)
class BezelTests(unittest.TestCase):
 def test_hidden_strip_and_bottom_physical_geometry(self):
  p=display_plan([output('left',0,0,2000,1000,[710,400]),output('right',2000,200,1600,800,[600,340])],17.5)
  self.assertEqual(p['width_mm'],1327.5)
  self.assertEqual(p['screens'][1]['physical'],[727.5,60.,600.,340.])
  self.assertIn('pass CopySource',shader(p));self.assertIn('uniform float',shader(p))
 def test_fingerprint_changes_with_layout(self):
  a=[output('a',0,0,1000,1000,[400,400]),output('b',1000,0,1000,1000,[400,400])]
  self.assertNotEqual(fingerprint(display_plan(a,17.5)),fingerprint(display_plan(a,20)))
 def test_reject_invalid_geometry_and_settings(self):
  with self.assertRaises(ValueError):display_plan([output('a',0,0,1000,1000,[400,400]),output('b',1000,0,1000,800,[400,300])],17.5)
  for value in ('nan','inf','-1','101'):
   with self.assertRaises(ValueError):validate({'bezel-width-mm':value})
  validate({'bezel-compensation-enabled':'on','bezel-width-mm':'17.5'})
if __name__=='__main__':unittest.main()

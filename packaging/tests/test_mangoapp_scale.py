"""Final display size remains constant across nested FSR targets."""
from pathlib import Path
import tempfile
import unittest
from test_mangoapp_fps import fps

class ScaleTests(unittest.TestCase):
    def test_actual_canvas_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory)/'session'
            for percent in (125,150,175,200):
                session.write_text(f'pipeline=fsr-dual\nfsr_target_width={1920*percent//100}\nfsr_target_height={1080*percent//100}\noutput_width=1920\noutput_height=1080\n')
                scale=fps.ui_scale(session)
                self.assertEqual(scale,percent/100)
                config=dict(line.split('=',1) for line in fps.render_config(True,scale=scale).splitlines() if '=' in line and not line.startswith('#'))
                for key,base in [('font_size',29),('font_size_secondary',29),('font_size_text',22),('width',245),('height',200)]:
                    self.assertAlmostEqual(float(config[key])/scale,base * 0.4725)
                self.assertEqual(config['no_display'],'0')

    def test_fit_and_single_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory)/'session'
            session.write_text('pipeline=fsr-dual\nfsr_target_width=2560\nfsr_target_height=2160\noutput_width=1920\noutput_height=1080\n')
            self.assertEqual(fps.ui_scale(session),2)
            session.write_text('pipeline=fsr-direct\nfsr_target_width=3840\nfsr_target_height=2160\noutput_width=1920\noutput_height=1080\n')
            self.assertEqual(fps.ui_scale(session),1)

    def test_invalid_or_missing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory)/'session'
            self.assertEqual(fps.ui_scale(session),1)
            for text in ('pipeline=fsr-dual', 'pipeline=fsr-dual\nfsr_target_width=$(touch never)', 'pipeline=fsr-dual\nfsr_target_width=0\nfsr_target_height=2160\noutput_width=1920\noutput_height=1080'):
                session.write_text(text)
                self.assertEqual(fps.ui_scale(session),1)

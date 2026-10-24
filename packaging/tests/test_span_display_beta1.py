import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "mwm"))
from span_display_info import edid_physical_mm, inventory, logical_rect, parse_edid, union_bounds, physical_scale_plan, matched_scale_layout
from settings_safety import validate


def sample_edid(width_cm=53, height_cm=30, model="ACME 24.5"):
    data = bytearray(128)
    data[:8] = bytes.fromhex("00ffffffffffff00")
    data[8:10] = ((1 << 10) | (3 << 5) | 13).to_bytes(2, "big")  # ABC
    data[10:12] = (0x1234).to_bytes(2, "little")
    data[21], data[22] = width_cm, height_cm
    data[54:72] = bytes([0, 0, 0, 0xFC, 0]) + model.encode("ascii")[:13].ljust(13, b" ")
    data[127] = (-sum(data[:127])) % 256
    return bytes(data)


class SpanDisplayInventoryTests(unittest.TestCase):
    def test_physical_matching_different_density_and_missing_size(self):
        a = dict(name="HDMI-A-1", enabled=True, connected=True, physical_mm=(540,300),
                 size=dict(width=1920,height=1080), scale=1)
        b = dict(name="DP-2", enabled=True, connected=True, physical_mm=(600,340),
                 size=dict(width=2560,height=1440), scale=1)
        plan = physical_scale_plan([a,b])
        self.assertEqual([p["scale"] for p in plan], [1,1.2])
        self.assertLess(abs(plan[1]["residual_percent"]), 1)
        self.assertEqual(plan[1]["logical_height"], 1200)
        with self.assertRaises(ValueError):
            physical_scale_plan([a,dict(b,physical_mm=None)])

    def test_match_keeps_reference_scale_and_centers_three_displays(self):
        a=dict(name="a",enabled=True,connected=True,size=dict(width=1920,height=1080),
               physical_mm=(540,300),scale=1.2,pos=dict(x=0,y=0))
        b=dict(a,name="b",size=dict(width=2560,height=1440),physical_mm=(600,340),pos=dict(x=1600,y=0))
        c=dict(a,name="c",pos=dict(x=3733,y=0))
        plan=matched_scale_layout([a,b,c], alignment="center")
        self.assertEqual([o["scale"] for o in plan],[1.2,1.45,1.2])
        self.assertEqual(plan[0]["y"],plan[2]["y"])
        self.assertEqual(plan[1]["y"],0)
        bottom=matched_scale_layout([a,b,c])
        self.assertEqual(len({o["y"]+o["logical_height"] for o in bottom}),1)
        self.assertEqual(plan[1]["x"],plan[0]["logical_width"])
        with self.assertRaises(ValueError):
            matched_scale_layout([a,dict(b,pos=dict(x=0,y=1000))])

    def test_edid_reports_mm_and_model_without_serial(self):
        info = parse_edid(sample_edid())
        self.assertEqual(info["physical_mm"], (530, 300))
        self.assertEqual(info["vendor"], "ACM")
        self.assertTrue(info["model"].startswith("ACME 24.5"))
        self.assertNotIn("serial", info)

    def test_edid_size_missing_or_checksum_invalid_is_unknown(self):
        self.assertIsNone(edid_physical_mm(sample_edid(0, 0)))
        corrupt = bytearray(sample_edid()); corrupt[30] ^= 1
        self.assertIsNone(edid_physical_mm(corrupt))

    def test_scaled_logical_rect_and_rotated_rect(self):
        left = {"size":{"width":3840,"height":2160},"scale":1.5,"pos":{"x":0,"y":0},"rotation":1}
        right = {"size":{"width":1920,"height":1080},"scale":1,"pos":{"x":2560,"y":180},"rotation":1}
        rotated = {"size":{"width":1080,"height":1920},"scale":1,"pos":{"x":0,"y":0},"rotation":2}
        self.assertEqual(logical_rect(left), (0,0,2560,1440))
        self.assertEqual(logical_rect(rotated), (0,0,1920,1080))
        self.assertEqual(union_bounds([left | {"connected":True,"enabled":True}, right | {"connected":True,"enabled":True}]),
                         {"x":0,"y":0,"width":4480,"height":1440})

    def test_inventory_auto_reads_per_output_edid(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "packaging/tests") as tmp:
            edid = Path(tmp) / "card0-DP-1" / "edid"
            edid.parent.mkdir(); edid.write_bytes(sample_edid())
            payload = {"outputs":[{"name":"DP-1","connected":True,"enabled":True,
                "size":{"width":1920,"height":1080},"scale":1,"pos":{"x":0,"y":0},
                "rotation":1,"modeId":"m1","modes":[{"id":"m1","refreshRate":59.94}]}]}
            result = inventory(json.dumps(payload), tmp)
            self.assertEqual(result[0]["physical_mm"], (530,300))
            self.assertEqual(result[0]["refresh_hz"], 59.94)
            self.assertEqual(result[0]["logical_rect"], (0,0,1920,1080))

    def test_physical_override_validation_and_bounds(self):
        validate({"gamescope-span-physical-overrides": '{"DP-1":[530,300]}'})
        with self.assertRaises(ValueError):
            validate({"gamescope-span-physical-overrides": '{"DP-1":[0,300]}'})
        with self.assertRaises(ValueError):
            validate({"gamescope-span-physical-overrides": '{"../bad":[530,300]}'})

    def test_gamescope_tab_is_separate_and_reads_outputs_automatically(self):
        ui = (ROOT / "mwm" / "mwm.py").read_text(encoding="utf-8")
        self.assertIn('self.tabs.addTab(span_page, "Span Display")', ui)
        self.assertIn('self._span_probe.start("kscreen-doctor", ["-j"])', ui)
        self.assertIn('"gamescope-span-enabled": "on" if self.span_displays.isChecked() else "off"', ui)


if __name__ == "__main__":
    unittest.main()

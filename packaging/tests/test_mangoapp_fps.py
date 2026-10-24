import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mwm/scripts/mangoapp_fps.py"
spec = importlib.util.spec_from_file_location("mangoapp_fps", SCRIPT)
fps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fps)


class MangoAppFPS(unittest.TestCase):
    def test_cache_values_and_age(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "mirishita-fps"
            for value, age, expected in [
                ("60.06", 0, "60.06"), ("14.17", 1, "14.17"),
                ("240", 2, "240.00"), ("0", 0, "--.--"),
                ("241", 0, "--.--"), ("nan", 0, "--.--"),
                ("inf", 0, "--.--"), ("bad", 0, "--.--"),
                ("", 0, "--.--"), ("60", 2.01, "--.--"),
                ("60", -1, "--.--"),
            ]:
                with self.subTest(value=value, age=age):
                    cache.write_text(value)
                    os.utime(cache, (100, 100))
                    self.assertEqual(fps.fps_text(cache, 100 + age), expected)
            self.assertEqual(fps.fps_text(Path(directory) / "missing", 100), "--.--")

    def test_generated_config_and_live_command(self):
        for visible in (False, True):
            config = fps.render_config(visible, scale=1)
            lines = [line for line in config.splitlines() if line and not line.startswith("#")]
            settings = dict(line.split("=", 1) for line in lines if "=" in line)
            self.assertEqual(settings["no_display"], str(int(not visible)))
            self.assertEqual(settings["fps"], "0")
            self.assertEqual(settings["legacy_layout"], "0")
            self.assertEqual(settings["font_size_secondary"], settings["font_size"])
            self.assertEqual((settings["width"], settings["height"], settings["font_size"]), ("115.7625", "94.5", "13.7025"))
            self.assertEqual(lines[lines.index("custom_text=FPS") + 1].split("=", 1)[0], "exec")
            self.assertIn("frame_timing", lines)
            self.assertLess(lines.index("gpu_stats"), lines.index("cpu_stats"))
            self.assertLess(lines.index("cpu_stats"), lines.index("custom_text=FPS"))
            self.assertLess(lines.index("custom_text=FPS"), lines.index("frame_timing"))
            self.assertNotIn("@MWM_GAME_FPS@", config)
            with tempfile.TemporaryDirectory(prefix="mwm test ") as directory:
                state = Path(directory) / "mwm"
                state.mkdir()
                (state / "mirishita-fps").write_text("60.06")
                result = subprocess.run(shlex.split(settings["exec"]), env={**os.environ, "XDG_STATE_HOME": directory}, capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, "60.06\n")

    def test_fast_reader(self):
        import time
        reader = ROOT / "mwm/scripts/mangoapp-fps-text.sh"
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            for value, age, expected in [
                ("60.06 16.65", 0, "60.06"), ("14.17 70.57", 0, "14.17"),
                ("240.00 4.16", 0, "240.00"), ("0.00 0.00", 0, "--.--"),
                ("241.00 0.00", 0, "--.--"), ("nan", 0, "--.--"),
                ("bad", 0, "--.--"), ("", 0, "--.--"),
                ("60.06 16.65", 3, "--.--"), ("60.06 16.65", -3, "--.--"),
            ]:
                with self.subTest(value=value, age=age):
                    cache.write_text(value + "\n")
                    stamp = time.time() - age
                    os.utime(cache, (stamp, stamp))
                    result = subprocess.run(["/bin/bash", str(reader), str(cache)], capture_output=True, text=True, check=True)
                    self.assertEqual(result.stdout, expected + "\n")
            result = subprocess.run(["/bin/bash", str(reader), str(cache.with_name("missing"))], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, "--.--\n")

    def test_wrapper_selects_patched_binary(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            scripts = base / "app/scripts"
            (scripts / "mangoapp-bin").mkdir(parents=True)
            (scripts / "mangoapp-native").mkdir()
            (base / "app/config").mkdir()
            shutil.copy2(ROOT / "mwm/scripts/mangoapp-bin/mangoapp", scripts / "mangoapp-bin/mangoapp")
            shutil.copy2(SCRIPT, scripts / "mangoapp_fps.py")
            shutil.copy2(ROOT / "mwm/config/MangoApp.conf", base / "app/config/MangoApp.conf")
            collector = scripts / "fps-collector.sh"
            collector.write_text("#!/usr/bin/env bash\nexec sleep 100\n")
            collector.chmod(0o755)
            native = scripts / "mangoapp-native/mangoapp"
            native.write_text('#!/usr/bin/env bash\n[[ "$MWM_MANGOAPP_FPS_INTEGER_ALIGN" == 1 ]] || exit 10\nprintf patched\n')
            native.chmod(0o755)
            result = subprocess.run(["bash", str(scripts / "mangoapp-bin/mangoapp")], env={**os.environ, "MWM_REAL_MANGOAPP": str(native), "XDG_CONFIG_HOME": str(base / "config"), "XDG_STATE_HOME": str(base / "state")}, capture_output=True, text=True, timeout=10, check=True)
            self.assertEqual(result.stdout, "patched")

    def test_command_quotes_script_path(self):
        with tempfile.TemporaryDirectory(prefix="mwm test '") as directory:
            old = fps.__file__
            try:
                fps.__file__ = str(Path(directory) / "mangoapp_fps.py")
                config = fps.render_config(True)
                command = next(line[5:] for line in config.splitlines() if line.startswith("exec="))
                self.assertEqual(shlex.split(command)[1], str(Path(fps.__file__).with_name("mangoapp-fps-text.sh")))
            finally:
                fps.__file__ = old


if __name__ == "__main__":
    unittest.main()

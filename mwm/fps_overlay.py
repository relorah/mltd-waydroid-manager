#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""MWM performance overlay styled after MangoApp/MangoHud.

The layer-shell HUD works for both KWin and Gamescope. It avoids injecting a
Vulkan overlay into Waydroid and provides a fallback where MangoApp cannot run
alongside Gamescope's exposed Wayland socket.
"""
import argparse
import fcntl
import os
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from shutil import which
import bc250_gpu
from overlay_owner import hud_should_run

# The desktop may export GDK_BACKEND=x11 for other applications. The HUD
# needs the host Wayland connection for layer-shell above fullscreen windows.
if os.environ.get("WAYLAND_DISPLAY"):
    os.environ["GDK_BACKEND"] = "wayland"

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib
from gi.repository import GtkLayerShell

ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / "scripts" / "fps-collector.sh"
GEOMETRY = ROOT / "scripts" / "kwin-waydroid-geometry.sh"

FOLLOW_INTERVAL_MS = 750
HIDE_AFTER_MISSES = 3
HISTORY_SAMPLES = 120

# MangoHud-inspired palette (not a copy of its renderer).
COLORS = {
    "text": (0.93, 0.93, 0.93, 1.0),
    "muted": (0.72, 0.72, 0.72, 1.0),
    "fps": (0.92, 0.36, 0.36, 1.0),
    "cpu": (0.18, 0.59, 0.80, 1.0),
    "gpu": (0.18, 0.59, 0.38, 1.0),
    "graph": (0.25, 0.95, 0.36, 1.0),
    "grid": (1.0, 1.0, 1.0, 0.13),
    "bg": (0.01, 0.01, 0.01, 0.62),
}


def acquire_single_instance_lock():
    cache_dir = Path.home() / ".cache" / "mwm"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / "performance-overlay.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
    return fd


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--style", choices=("minimal", "detailed", "text", "graph"), default="minimal")
    p.add_argument("--size", choices=("small", "medium", "large"), default="small")
    p.add_argument("--position", choices=("top-left", "top-right"), default="top-left")
    p.add_argument("--interval", type=float, default=0.2)
    p.add_argument("--follow-window", action="store_true")
    args = p.parse_args()
    # Compatibility with pre-v0.5.52 manual invocations.
    if args.style == "text":
        args.style = "minimal"
    elif args.style == "graph":
        args.style = "detailed"
    return args


class CPUSampler:
    def __init__(self):
        self.previous = None
        self.temp_path = None

    @staticmethod
    def read_totals():
        try:
            parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
            if not parts or parts[0] != "cpu":
                return None
            values = [int(v) for v in parts[1:]]
            while len(values) < 8:
                values.append(0)
            user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
            idle_all = idle + iowait
            non_idle = user + nice + system + irq + softirq + steal
            return idle_all + non_idle, idle_all
        except Exception:
            return None

    @staticmethod
    def _find_temp_path():
        preferred_names = ("k10temp", "coretemp", "zenpower")
        candidates = []
        for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            try:
                name = (hwmon / "name").read_text().strip().lower()
            except Exception:
                name = ""
            priority = preferred_names.index(name) if name in preferred_names else 99
            for inp in sorted(hwmon.glob("temp*_input")):
                label_path = inp.with_name(inp.name.replace("_input", "_label"))
                try:
                    label = label_path.read_text().strip().lower()
                except Exception:
                    label = ""
                label_priority = 0 if any(x in label for x in ("tctl", "tdie", "package")) else 1
                candidates.append((priority, label_priority, inp))
        candidates.sort(key=lambda x: (x[0], x[1], str(x[2])))
        return candidates[0][2] if candidates else None

    def sample_load(self):
        current = self.read_totals()
        if current is None:
            return None
        if self.previous is None:
            self.previous = current
            return None
        total_delta = current[0] - self.previous[0]
        idle_delta = current[1] - self.previous[1]
        self.previous = current
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))

    def sample_temp(self):
        if self.temp_path is None:
            self.temp_path = self._find_temp_path()
        if self.temp_path is None:
            return None
        try:
            value = float(self.temp_path.read_text().strip()) / 1000.0
            if -10.0 <= value <= 125.0:
                return value
        except Exception:
            pass
        self.temp_path = None
        return None


class AMDGPUSampler:
    def __init__(self):
        self.busy_path = None
        self.device_path = None
        self.temp_path = None
        self._discover()
        bc250_gpu.ensure_collector()

    def _discover(self):
        candidates = []
        for path in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
            device = path.parent
            try:
                driver = (device / "driver").resolve().name
            except Exception:
                driver = ""
            if driver and driver != "amdgpu":
                continue
            try:
                boot_vga = int((device / "boot_vga").read_text().strip())
            except Exception:
                boot_vga = 0
            try:
                card_num = int(path.parents[1].name.replace("card", ""))
            except Exception:
                card_num = 999
            candidates.append((-boot_vga, card_num, path, device))
        if not candidates:
            self.busy_path = self.device_path = self.temp_path = None
            return
        candidates.sort(key=lambda x: (x[0], x[1]))
        _a, _b, self.busy_path, self.device_path = candidates[0]
        self.temp_path = self._find_temp_path(self.device_path)

    @staticmethod
    def _find_temp_path(device):
        candidates = []
        for inp in sorted(device.glob("hwmon/hwmon*/temp*_input")):
            label_path = inp.with_name(inp.name.replace("_input", "_label"))
            try:
                label = label_path.read_text().strip().lower()
            except Exception:
                label = ""
            priority = 0 if label == "edge" else (1 if "junction" in label else 2)
            candidates.append((priority, inp))
        candidates.sort(key=lambda x: (x[0], str(x[1])))
        return candidates[0][1] if candidates else None

    def sample_load(self):
        if bc250_gpu.enabled() and self.device_path is not None:
            try:
                if int((self.device_path / "device").read_text().strip(), 16) == 0x13fe:
                    return bc250_gpu.read_load(self.device_path.resolve().name)
            except (OSError, ValueError):
                return None
        if self.busy_path is None:
            self._discover()
        if self.busy_path is None:
            return None
        try:
            return max(0.0, min(100.0, float(self.busy_path.read_text().strip())))
        except Exception:
            self._discover()
            return None

    def sample_temp(self):
        if self.temp_path is None and self.device_path is not None:
            self.temp_path = self._find_temp_path(self.device_path)
        if self.temp_path is None:
            return None
        try:
            value = float(self.temp_path.read_text().strip()) / 1000.0
            if -10.0 <= value <= 125.0:
                return value
        except Exception:
            pass
        self.temp_path = None
        return None


class PerformanceOverlay:
    def __init__(self, args):
        self.args = args
        size_scale = {"small": 1.0, "medium": 1.2, "large": 1.5}[args.size]
        style_scale = 1.2 if args.style == "detailed" else 1.0
        scale = size_scale * style_scale
        self.size_scale = scale
        # Compact MangoHud/MangoApp-like geometry. Detailed scales the whole
        # HUD uniformly so its typography, columns, margins and graph keep
        # their existing proportions while Compact retains its current size.
        self.padding = 10.0 * scale
        self.font = 16.0 * scale
        self.small_font = 12.0 * scale
        self.overlay_width = int((110 if args.style == "minimal" else 168) * scale)
        self.overlay_height = int((108 if args.style == "minimal" else 132) * scale)
        self.collector = None
        self.stop_event = threading.Event()
        self.follow_available = bool(args.follow_window and which("kdotool") and GEOMETRY.exists())
        self.target_visible = not self.follow_available
        self.overlay_visible = False
        self.target_misses = 0
        self.last_geometry = None
        self.pending_metrics = None
        self.pending_idle = False
        self.pending_lock = threading.Lock()

        self.cpu_sampler = CPUSampler()
        self.gpu_sampler = AMDGPUSampler()
        self.metrics = {
            "fps": 0.0, "frametime": 0.0,
            "cpu": None, "gpu": None, "cpu_temp": None, "gpu_temp": None,
        }
        self.fps_history = deque(maxlen=HISTORY_SAMPLES)

        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("MWM Performance Overlay")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        try:
            self.window.set_can_focus(False)
        except Exception:
            pass
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.window.set_app_paintable(True)
        self.window.set_opacity(0.0)
        self.window.set_default_size(self.overlay_width, self.overlay_height)

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)

        if GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self.window)
            GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(self.window, 0)
            GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.TOP, 16)
            GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.LEFT, 16)

        self.area = Gtk.DrawingArea()
        self.area.set_size_request(self.overlay_width, self.overlay_height)
        self.area.connect("draw", self.draw)
        self.window.add(self.area)

        self.window.connect("realize", self.apply_click_through)
        self.window.connect("map-event", self.apply_click_through)
        self.window.connect("size-allocate", self.apply_click_through)
        self.window.connect("destroy", self.shutdown)
        self.window.show_all()
        GLib.timeout_add(250, self.enforce_saved_mode)
        GLib.idle_add(self.apply_click_through)
        self.start_collector()
        self._switcher_attempts = 0
        GLib.timeout_add(500, self.exclude_from_switcher)

        if self.follow_available:
            GLib.timeout_add(FOLLOW_INTERVAL_MS, self.follow_target_window)
        else:
            self.set_fallback_position()

    def enforce_saved_mode(self):
        cfg = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'mwm'
        if not hud_should_run(self.args.style, cfg):
            self.shutdown()
            return False
        return not self.stop_event.is_set()

    def set_fallback_position(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        geometry = monitor.get_geometry() if monitor else None
        x = 16
        if self.args.position == "top-right" and geometry:
            x = max(0, geometry.width - self.overlay_width - 16)
        self.place_hud(x, 16)
        self.target_visible = True
        self.update_visibility()

    def update_visibility(self):
        if self.target_visible == self.overlay_visible:
            return False
        self.overlay_visible = self.target_visible
        self.window.set_opacity(1.0 if self.target_visible else 0.0)
        return False

    def exclude_from_switcher(self):
        """KWin's switcher exclusion is separate from GTK's taskbar hint."""
        self._switcher_attempts += 1
        if not which("kdotool"):
            return False
        js = """
var list = workspace.stackingOrder || [];
for (var i=0; i<list.length; i++) {
 var w=list[i];
 if (Number(w.pid) !== PID || String(w.caption) !== "MWM Performance Overlay") continue;
 w.skipSwitcher=true; w.skipTaskbar=true; w.skipPager=true;
 output_result("MWM_HUD_EXCLUDED");
}
""".replace("PID", str(os.getpid()))
        try:
            result = subprocess.run(["kdotool", "kwinscript", "--inline", js],
                                    capture_output=True, text=True, timeout=2)
            if "MWM_HUD_EXCLUDED" in result.stdout:
                return False
        except (OSError, subprocess.TimeoutExpired):
            pass
        return self._switcher_attempts < 8

    def place_hud(self, x, y):
        if GtkLayerShell.is_layer_window(self.window):
            GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.LEFT, max(0, x))
            GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.TOP, max(0, y))
            return True
        # GTK may fall back to a normal Wayland window. Layer-shell margins
        # then do nothing, so move only our HUD through KWin instead.
        js = """
var list=workspace.stackingOrder || [];
for(var i=0;i<list.length;i++) {
 var w=list[i];
 if(Number(w.pid)!==PID || String(w.caption)!=="MWM Performance Overlay") continue;
 w.skipSwitcher=true; w.skipTaskbar=true; w.skipPager=true; w.keepAbove=true;
 var g=w.frameGeometry;
 w.frameGeometry={x:XPOS,y:YPOS,width:g.width,height:g.height};
 output_result("MWM_HUD_POSITIONED");
}
""".replace("PID",str(os.getpid())).replace("XPOS",str(int(x))).replace("YPOS",str(int(y)))
        try:
            p=subprocess.run(["kdotool","kwinscript","--inline",js],capture_output=True,text=True,timeout=1.5)
            return "MWM_HUD_POSITIONED" in p.stdout
        except (OSError,subprocess.TimeoutExpired):
            return False

    def follow_target_window(self):
        if self.stop_event.is_set():
            return False
        geometry = None
        try:
            p = subprocess.run([str(GEOMETRY)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, timeout=1.5)
            parts = p.stdout.strip().split()
            if p.returncode == 0 and len(parts) in (4, 5):
                geometry = tuple(map(int, parts))
        except Exception:
            pass
        active = geometry is not None and (len(geometry) == 4 or geometry[4] == 1)
        if geometry is not None and not active:
            # A KWin layer-shell HUD on the OVERLAY layer otherwise remains
            # above Alt+Tab and other windows while Mirishita is inactive.
            self.target_misses = HIDE_AFTER_MISSES
            self.last_geometry = None
            if self.target_visible:
                self.target_visible = False
                self.update_visibility()
        elif active:
            self.target_misses = 0
            position = geometry[:4]
            if position != self.last_geometry:
                x, y, w, _h = position
                margin = 10
                ox = x + margin if self.args.position == "top-left" else x + max(0, w - self.overlay_width - margin)
                if self.place_hud(ox, y + margin):
                    self.last_geometry = position
            if not self.target_visible:
                self.target_visible = True
                self.update_visibility()
        else:
            self.target_misses += 1
            if self.target_misses >= HIDE_AFTER_MISSES and self.target_visible:
                self.target_visible = False
                self.last_geometry = None
                self.update_visibility()
        return True

    def apply_click_through(self, *_args):
        gdk_window = self.window.get_window()
        if gdk_window is None:
            return False
        try:
            gdk_window.set_pass_through(True)
        except Exception:
            pass
        try:
            gdk_window.input_shape_combine_region(cairo.Region(), 0, 0)
        except Exception:
            pass
        return False

    @staticmethod
    def _valid(value, maximum):
        try:
            value = float(value)
        except Exception:
            return 0.0
        return value if 0.0 < value <= maximum else 0.0

    def set_metrics(self, fps, frametime):
        self.metrics["fps"] = self._valid(fps, 240.0)
        self.metrics["frametime"] = self._valid(frametime, 1000.0)
        self.metrics["cpu"] = self.cpu_sampler.sample_load()
        self.metrics["gpu"] = self.gpu_sampler.sample_load()
        if self.args.style == "detailed":
            self.metrics["cpu_temp"] = self.cpu_sampler.sample_temp()
            self.metrics["gpu_temp"] = self.gpu_sampler.sample_temp()
        if self.metrics["fps"] > 0:
            self.fps_history.append(self.metrics["fps"])
        self.area.queue_draw()
        return False

    def queue_metrics(self, fps, frametime):
        with self.pending_lock:
            self.pending_metrics = (fps, frametime)
            if self.pending_idle:
                return
            self.pending_idle = True
        GLib.idle_add(self.apply_pending_metrics)

    def apply_pending_metrics(self):
        with self.pending_lock:
            values = self.pending_metrics or ("0", "0")
            self.pending_metrics = None
            self.pending_idle = False
        self.set_metrics(*values)
        return False

    @staticmethod
    def _text(ctx, x, y, text, size, color, bold=False, align="left"):
        ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(size)
        ext = ctx.text_extents(text)
        if align == "right":
            x -= ext.width
        # Align visible glyph bounds, including the monospace side bearing.
        x -= ext.x_bearing
        ctx.set_source_rgba(*color)
        ctx.move_to(x, y)
        ctx.show_text(text)

    @staticmethod
    def _rounded_rect(ctx, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r, r, -1.5708, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, 1.5708)
        ctx.arc(x + r, y + h - r, r, 1.5708, 3.14159)
        ctx.arc(x + r, y + r, r, 3.14159, 4.71239)
        ctx.close_path()

    @staticmethod
    def _metric(value, decimals=1):
        if value is None:
            return "--"
        return f"{float(value):.{decimals}f}"

    def _decimal_metric(self, ctx, decimal_x, y, text):
        # Anchor the decimal itself; stripping glyph bearings from a padded
        # whole string used to consume its leading spaces and shift 1-digit values.
        integer, point, fraction = text.strip().partition(".")
        if point:
            self._text(ctx, decimal_x, y, integer, self.font, COLORS["text"], True, "right")
            self._text(ctx, decimal_x, y, "." + fraction, self.font, COLORS["text"], True)
        else:
            self._text(ctx, decimal_x, y, text.strip(), self.font, COLORS["text"], True)

    def draw(self, widget, ctx):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.restore()
        ctx.set_operator(cairo.OPERATOR_OVER)

        self._rounded_rect(ctx, 0, 0, w, h, 6 * self.size_scale)
        ctx.set_source_rgba(*COLORS["bg"])
        ctx.fill()

        pad = self.padding
        label_x = pad
        # MangoHud-like compact metric column: keep values visually attached
        # to FPS/CPU/GPU instead of right-aligning them across the whole HUD.
        # Minimal's label/value gap is reduced by half (1.5 -> 0.75 cells).
        decimal_chars = 3.75 if self.args.style == "minimal" else 4.5
        decimal_x = pad + self.font * decimal_chars
        temp_x = w - pad
        row_h = self.font * 1.16
        baseline = pad + self.font
        # Fixed-width numeric fields: all three decimal points line up.
        # Examples: " 1.0%", "13.7%", "29.99".
        gpu = self.metrics["gpu"]
        cpu = self.metrics["cpu"]
        fps = self.metrics["fps"]
        rows = [
            ("GPU", f"{gpu:4.1f}%" if gpu is not None else "  --%", COLORS["gpu"], self.metrics["gpu_temp"]),
            ("CPU", f"{cpu:4.1f}%" if cpu is not None else "  --%", COLORS["cpu"], self.metrics["cpu_temp"]),
            ("FPS", f"{fps:5.2f}" if fps is not None and fps > 0 else " --.--", COLORS["fps"], None),
        ]

        detailed_shift = 0.0
        if self.args.style == "detailed":
            # Halve the open percent-to-temperature gap, shifting the compact
            # group as a whole so left/right outer margins remain balanced.
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(self.font)
            suffix_width = ctx.text_extents(".0%").width
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(self.small_font)
            temp_width = ctx.text_extents("100°C").width
            gap = max(0.0, (w - 2 * pad) - (decimal_x - pad) - suffix_width - temp_width)
            detailed_shift = gap / 4.0
            label_x += detailed_shift
            decimal_x += detailed_shift
            temp_x -= detailed_shift

        for i, (label, metric_text, color, temp) in enumerate(rows):
            y = baseline + i * row_h
            self._text(ctx, label_x, y, label, self.font, color, True)
            self._decimal_metric(ctx, decimal_x, y, metric_text)
            if self.args.style == "detailed" and temp is not None and label in ("CPU", "GPU"):
                self._text(ctx, temp_x, y, f"{temp:.0f}°C", self.small_font,
                           COLORS["muted"], False, "right")

        # Plot the same rolling SurfaceFlinger FPS value shown in the FPS row.
        # Detailed also displays the latest individual frametime as a number.
        graph_top = baseline + len(rows) * row_h + (2 if self.args.style == "detailed" else 1) * self.size_scale
        ft = self.metrics["frametime"]
        if self.args.style == "detailed":
            ft_label = "Frametime"
            ft_value = f"{ft:.2f} ms" if ft > 0 else "--.-- ms"
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(self.small_font)
            label_width = ctx.text_extents(ft_label).width
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            value_width = ctx.text_extents(ft_value).width
            ft_gap = max(0.0, (w - 2 * pad) - label_width - value_width)
            ft_inset = ft_gap / 4.0
            self._text(ctx, pad + ft_inset, graph_top, ft_label, self.small_font, COLORS["muted"], True)
            self._text(ctx, w - pad - ft_inset, graph_top, ft_value,
                       self.small_font, COLORS["text"], False, "right")
            chart_top = graph_top + 5 * self.size_scale
        else:
            chart_top = graph_top
        # Keep the graph as a thin telemetry strip rather than the dominant
        # element of the HUD.
        chart_bottom = h - 6 * self.size_scale
        chart_left = pad
        chart_right = w - pad
        chart_h = max(16 * self.size_scale, min((38 if self.args.style == "minimal" else 34) * self.size_scale,
                              chart_bottom - chart_top))
        chart_top = chart_bottom - chart_h
        chart_w = max(20, chart_right - chart_left)

        values = list(self.fps_history)
        dynamic_max = max([60.0] + [v for v in values if v is not None])
        dynamic_max = min(max(dynamic_max * 1.15, 60.0), 240.0)
        # Mirishita's usual 60 FPS target; the graph rises with the FPS value.
        ref = 60.0
        yref = chart_bottom - min(1.0, ref / dynamic_max) * chart_h
        ctx.set_source_rgba(*COLORS["grid"])
        ctx.set_line_width(1.0 * self.size_scale)
        ctx.move_to(chart_left, yref); ctx.line_to(chart_right, yref); ctx.stroke()

        if len(values) >= 2:
            step = chart_w / max(1, len(values) - 1)
            x0 = chart_left
            ctx.set_source_rgba(*COLORS["graph"])
            ctx.set_line_width(1.6 * self.size_scale)
            drawing = False
            for i, raw in enumerate(values):
                if raw is None or raw <= 0:
                    drawing = False
                    continue
                x = x0 + i * step
                y = chart_bottom - min(1.0, raw / dynamic_max) * chart_h
                if not drawing:
                    ctx.move_to(x, y); drawing = True
                else:
                    ctx.line_to(x, y)
            if drawing:
                ctx.stroke()
        return False

    def start_collector(self):
        interval = str(max(0.2, self.args.interval))
        try:
            self.collector = subprocess.Popen([str(COLLECTOR), interval], stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except Exception:
            GLib.idle_add(self.set_metrics, "0", "0")
            return

        def reader():
            try:
                for line in self.collector.stdout:
                    if self.stop_event.is_set():
                        break
                    parts = line.strip().split()
                    fps = parts[0] if parts else "0"
                    ft = parts[1] if len(parts) > 1 else "0"
                    self.queue_metrics(fps, ft)
            finally:
                if not self.stop_event.is_set():
                    self.queue_metrics("0", "0")
        threading.Thread(target=reader, daemon=True).start()

    def shutdown(self, *_args):
        self.stop_event.set()
        if self.collector and self.collector.poll() is None:
            try:
                self.collector.terminate(); self.collector.wait(timeout=1)
            except Exception:
                try:
                    self.collector.kill()
                except Exception:
                    pass
        Gtk.main_quit()


def main():
    args = parse_args()
    cfg = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'mwm'
    if not hud_should_run(args.style, cfg):
        return
    lock_fd = acquire_single_instance_lock()
    if lock_fd is None:
        return
    overlay = PerformanceOverlay(args)

    def stop_signal(*_):
        overlay.window.destroy()
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    Gtk.main()
    os.close(lock_fd)


if __name__ == "__main__":
    main()

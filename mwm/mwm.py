#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import json
from settings_safety import commit as commit_settings, recover as recover_settings
import os
import signal
import stat
import shutil
import subprocess
import sys
import time
from pathlib import Path
from version import __version__ as APP_VERSION
from display_settings import dimensions, ratio_width, legacy_ratio
from ui_help import help_row, local
from host_platform import is_ubuntu

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QLockFile, QStandardPaths, QProcess, QLocale
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout,
    QWidget, QInputDialog, QSpinBox, QSlider,
)

from popup_language import LocalizedMessageBox
QMessageBox = LocalizedMessageBox(QMessageBox, QLocale.system().language() == QLocale.Language.Japanese)

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
PROFILES = ROOT / "config" / "game_profiles.json"
APP_ID = "com.bandainamcoent.imas_millionlive_theaterdays"
OBSOLETE_SETTINGS = ("gamescope-rtscale-fsr-enabled", "gamescope-window-mode", "gamescope-frame-generation", "mako-gamescope-fg.toml", "kwin-window-mode", "kwin-window-geometry", "kwin-window-state")
KNOWN_NAMES = {
    APP_ID: "Mirishita",
    "jp.co.bandainamcoent.BNEI0242": "Deresute",
}


def run(cmd, timeout=30):
    p = subprocess.Popen(
        [str(x) for x in cmd], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole command group so child processes cannot hold the
        # output pipe open forever after a timeout. Gamescope owns its session.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, _ = p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            p.stdout.close()
            out = ""
        return 124, f"Operation timed out ({timeout}s)。\n{out or ''}".strip()
    return p.returncode, (out or "").strip()


class PreparationDialog(QDialog):
    """Keep the preparation notice visible while the worker is running."""
    def __init__(self, parent):
        super().__init__(parent)
        self.busy = True
        self.setWindowTitle(local("Preparing Waydroid", "Waydroidを準備しています"))
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        label = QLabel(local("Please wait while Waydroid starts and saved settings are applied. Do not launch Mirishita until preparation finishes.",
                             "Waydroidの準備が完了するまでお待ちください。\nAndroidの起動、解像度の確認、保存設定の反映を行っています。\n準備が完了するまでミリシタを起動しないでください。"))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.resize(440, 170)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def finish(self):
        self.busy = False
        self.accept()


class Worker(QThread):
    done = Signal(int, str)

    def __init__(self, cmd, timeout=30):
        super().__init__()
        self.cmd = [str(x) for x in cmd]
        self.timeout = timeout

    def run(self):
        try:
            rc, out = run(self.cmd, self.timeout)
        except Exception as e:
            rc, out = 99, f"{type(e).__name__}: {e}"
        self.done.emit(rc, out)


class Card(QFrame):
    def __init__(self, title, subtitle=""):
        super().__init__()
        self.setObjectName("Card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(10, 8, 10, 8)
        self.v.setSpacing(7)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        self.v.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            self.v.addWidget(sub)


class CollapsibleCard(QFrame):
    def __init__(self, title, expanded=False):
        super().__init__()
        self.setObjectName("Card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(10, 7, 10, 9)
        self.v.setSpacing(6)

        self.header = QToolButton()
        self.header.setText(title)
        self.header.setObjectName("CollapseHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setAutoRaise(True)
        self.header.toggled.connect(self._set_expanded)
        self.v.addWidget(self.header)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 2, 4, 1)
        self.content_layout.setSpacing(6)
        self.content.setVisible(expanded)
        self.v.addWidget(self.content)

    def _set_expanded(self, expanded):
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)

    def setExpanded(self, expanded):
        self.header.setChecked(bool(expanded))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MWM v{APP_VERSION}")
        self.resize(520, 700)
        self.setMinimumSize(0, 0)
        self.worker = None
        self.fps_overlay_proc = None
        self.applied_once = False
        self._initial_loading = True
        self._needs_backend_migration = False
        self._kwin_scale_cache = "3"
        self._reset_requested = False
        self._refresh_in_progress = False
        self._apply_delay_pending = False
        self._settings_ready_at = 0.0

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(9)

        title = QLabel("MLTD Waydroid Manager")
        title.setObjectName("AppTitle")
        main.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        main.addWidget(self.tabs, 1)

        # ===== Home =====
        home = QWidget()
        hv = QVBoxLayout(home)
        hv.setContentsMargins(2, 8, 2, 2)
        hv.setSpacing(9)

        self.backend = QComboBox()
        self.backend.addItem("Gamescope", "gamescope")
        self.backend.setMinimumWidth(self.backend.sizeHint().width())
        self.backend.currentIndexChanged.connect(self.update_backend_controls)
        render_card = Card("Render Settings")
        render_card.v.setContentsMargins(10, 8, 10, 8)
        render_card.v.setSpacing(2)
        render_card.v.setAlignment(Qt.AlignTop)
        label_column_width = QLabel("MSAA Sample Limit (?)").sizeHint().width() + 6
        self._field_labels = []
        render_grid = QGridLayout()
        render_grid.setColumnMinimumWidth(0, label_column_width)
        render_grid.setContentsMargins(0, 0, 0, 0)
        render_grid.setHorizontalSpacing(10)
        render_grid.setVerticalSpacing(7)
        self.backend.hide()
        self.scale = QComboBox()
        self.scale.addItem("OFF", "off")
        for i in range(1, 9):
            self.scale.addItem(f"x{i}", str(i))
        self.scale.setCurrentText("OFF")
        self.scale_label = QLabel("RTScale")
        self.scale.setToolTip("")
        scale_row = help_row(self.scale_label, "RTScale")
        self._field_labels.append(scale_row)
        render_grid.addWidget(scale_row, 1, 0)
        render_grid.addWidget(self.scale, 1, 1, 1, 2)
        self.msaa_samples = QComboBox()
        self.msaa_samples.addItem("Original (Quality)", "0")
        self.msaa_samples.addItem("2 Samples (Performance)", "2")
        try:
            msaa_value = (self.config_dir() / "rtscale-msaa-samples").read_text().strip()
        except OSError:
            msaa_value = "0"
        self.msaa_samples.setCurrentIndex(max(0, self.msaa_samples.findData(msaa_value)))
        msaa_row = help_row(QLabel("MSAA Sample Limit"), "MSAA Sample Limit")
        self._field_labels.append(msaa_row)
        render_grid.addWidget(msaa_row, 2, 0)
        render_grid.addWidget(self.msaa_samples, 2, 1, 1, 2)
        self.gamescope_fsr_scale = QComboBox()
        self.gamescope_fsr_scale.addItem("125%", 125)
        self.gamescope_fsr_scale.addItem("150%", 150)
        self.gamescope_fsr_scale.addItem("175%", 175)
        self.gamescope_fsr_scale.addItem("200%", 200)
        self.gamescope_fsr_scale.currentIndexChanged.connect(self.update_gamescope_sharpness_label)
        self.gamescope_fsr_sharpness_enabled = QCheckBox("FSR Sharpness")
        self.gamescope_fsr_sharpness_enabled.setChecked(False)
        self.gamescope_fsr_sharpness_enabled.toggled.connect(self.update_gamescope_sharpness_label)
        self.gamescope_fsr_sharpness_enabled.setToolTip("")
        self.gamescope_sharpness_label = QLabel("Sharpness")
        self.gamescope_sharpness = QSlider(Qt.Horizontal)
        self.gamescope_sharpness.setRange(1, 21)
        self.gamescope_sharpness.setSingleStep(1)
        self.gamescope_sharpness.setPageStep(1)
        self.gamescope_sharpness.setTickInterval(5)
        self.gamescope_sharpness.setValue(11)
        self.gamescope_sharpness_value = QLabel("11")
        self.gamescope_sharpness.valueChanged.connect(self.on_gamescope_sharpness_changed)
        self.fsr_scale_label = QLabel("Upscale")
        self.rtscale_fsr_enabled = QCheckBox("AMD FSR1")
        self.rtscale_fsr_enabled.setToolTip("")
        self.rtscale_fsr_enabled.toggled.connect(self.update_gamescope_sharpness_label)
        self.scale.currentIndexChanged.connect(self.update_backend_controls)
        upscale_row = help_row(self.fsr_scale_label, "Upscale")
        self._field_labels.append(upscale_row)
        render_grid.addWidget(upscale_row, 4, 0)
        render_grid.addWidget(help_row(self.rtscale_fsr_enabled, "AMD FSR1"), 3, 0, 1, 3)
        render_grid.addWidget(self.gamescope_fsr_scale, 4, 1, 1, 2)
        sharp_row = help_row(self.gamescope_sharpness_label, "Sharpness")
        self._field_labels.append(sharp_row)
        render_grid.addWidget(sharp_row, 5, 0)
        render_grid.addWidget(self.gamescope_sharpness, 5, 1)
        render_grid.addWidget(self.gamescope_sharpness_value, 5, 2)
        self.cas_enabled = QCheckBox("CAS")
        self.cas_strength = QSlider(Qt.Horizontal)
        self.cas_strength.setRange(0, 100)
        self.cas_strength.setSingleStep(5)
        self.cas_strength.setValue(50)
        self.cas_value = QLabel("50%")
        self.cas_strength.valueChanged.connect(lambda value: self.cas_value.setText(f"{value}%"))
        self.cas_enabled.toggled.connect(self.update_gamescope_sharpness_label)
        pass # Legacy CAS controls are not part of the UI.
        pass # Legacy CAS controls are not part of the UI.
        pass # Legacy CAS controls are not part of the UI.
        self.gamescope_fsr_sharpness_enabled.hide()
        self.cas_enabled.hide()
        self.cas_strength.hide()
        self.cas_value.hide()
        render_grid.setColumnStretch(0, 0)
        render_grid.setColumnStretch(1, 3)
        render_grid.setColumnStretch(2, 0)
        render_card.v.addLayout(render_grid)
        hv.addWidget(render_card)
        self._render_card = render_card

        display = Card("Display")
        dgrid = QGridLayout()
        dgrid.setContentsMargins(0, 0, 0, 0)
        dgrid.setColumnMinimumWidth(0, label_column_width)
        dgrid.setHorizontalSpacing(10)
        dgrid.setVerticalSpacing(6)
        self.aspect = QComboBox()
        for label, value in [
            ("Auto", "auto"),
            ("32:9", "32:9"),
            ("21:9", "21:9"),
            ("16:9", "16:9"),
            ("4:3", "4:3"),
            ("3:2", "3:2"),
            ("Custom", "custom"),
        ]:
            self.aspect.addItem(label, value)
        self.aspect.currentIndexChanged.connect(self.update_custom_aspect_visibility)
        self.aspect.setToolTip("")
        aspect_row = help_row(QLabel("Aspect Ratio"), "Aspect Ratio")
        self._field_labels.append(aspect_row)
        dgrid.addWidget(aspect_row, 0, 0)
        dgrid.addWidget(self.aspect, 0, 1)

        self.overlay_mode = QComboBox()
        self.overlay_mode.addItem("Off", "off")
        self.overlay_mode.addItem("Minimal", "minimal")
        self.overlay_mode.addItem("Detailed", "detailed")
        self.overlay_mode.addItem("MangoApp", "mangoapp")
        if is_ubuntu():
            self.overlay_mode.model().item(3).setToolTip(local("Uses the MWM MangoApp built during installation on Ubuntu.", "インストール時にUbuntu上でビルドしたMWM版MangoAppを使用します。"))
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
        if "gnome" in desktop:
            for index in (1, 2):
                item = self.overlay_mode.model().item(index)
                item.setEnabled(False)
                item.setToolTip(local("Requires a layer-shell compositor, such as KDE.", "KDEなどのlayer-shell対応環境が必要です。"))
        self.overlay_mode.setToolTip("")
        fps_row = help_row(QLabel("FPS Counter"), "FPS Counter")
        self._field_labels.append(fps_row)
        dgrid.addWidget(fps_row, 2, 0)
        dgrid.addWidget(self.overlay_mode, 2, 1)

        self.span_displays = QCheckBox("Span Displays (Experimental)")
        if "gnome" in desktop:
            self.span_displays.setEnabled(False)
        self.span_displays.setToolTip("")
        try:
            self.span_displays.setChecked((self.config_dir() / "gamescope-span-enabled").read_text().strip() == "on")
        except FileNotFoundError:
            pass
        self.span_displays.toggled.connect(self.update_resolution_preview)
        if "gnome" in desktop:
            self.span_displays.setChecked(False)

        self.custom_w = QSpinBox()
        self.custom_h = QSpinBox()
        for box, value in ((self.custom_w, 16), (self.custom_h, 9)):
            box.setRange(1, 99)
            box.setValue(value)
            box.setFixedWidth(box.sizeHint().width())
            box.valueChanged.connect(self.update_resolution_preview)
        self.custom_w.setAccessibleName("Aspect ratio width")
        self.custom_h.setAccessibleName("Aspect ratio height")
        self.custom_sep = QLabel(":")
        self.resolution = QLabel("Resolution: --")
        self.resolution.setMinimumWidth(self.resolution.fontMetrics().horizontalAdvance("Resolution: 11520x1080"))
        self.ratio_line = QWidget()
        ratio_layout = QHBoxLayout(self.ratio_line)
        ratio_layout.setContentsMargins(0, 0, 0, 0)
        ratio_layout.setSpacing(4)
        for widget in (self.custom_w, self.custom_sep, self.custom_h):
            ratio_layout.addWidget(widget)
        ratio_layout.addSpacing(6)
        ratio_layout.addWidget(self.resolution)
        ratio_layout.addStretch(1)
        self.ratio_line.setMinimumWidth(self.custom_w.width() + self.custom_h.width()
                                        + self.resolution.minimumWidth() + self.custom_sep.sizeHint().width() + 26)
        dgrid.addWidget(self.ratio_line, 1, 1)
        dgrid.setColumnStretch(0, 0)
        dgrid.setColumnStretch(1, 1)
        display.v.addLayout(dgrid)
        hv.addWidget(display)

        assist = Card("Options")
        self.zoom_fix = QCheckBox("RTScale Zoom Fix")
        self.zoom_fix.setToolTip("")
        self.auto_start = QCheckBox("Auto Launch Mirishita")
        self.auto_start.setToolTip("")
        try:
            auto_value = (self.config_dir() / "auto-start-mirishita").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            auto_value = "on"
        self.auto_start.setChecked(auto_value == "on")
        self.verify_startup = QCheckBox("Verify Waydroid Startup")
        try:
            verify_value = (self.config_dir() / "verify-waydroid-startup").read_text(encoding="utf-8").strip()
        except OSError:
            verify_value = "on"
        self.verify_startup.setChecked(verify_value != "off")
        self.verify_startup.setToolTip("")
        self.verify_startup.toggled.connect(self.auto_start.setEnabled)
        self.auto_start.setEnabled(self.verify_startup.isChecked())
        self.auto_start.setToolTip("")
        assist.v.addWidget(help_row(self.verify_startup, "Verify Waydroid Startup"))

        assist.v.addWidget(help_row(self.auto_start, "Auto Launch Mirishita"))
        self.fake_touch = QCheckBox("Mouse as Touch")
        assist.v.addWidget(help_row(self.fake_touch, "Mouse as Touch"))
        assist.v.addWidget(help_row(self.zoom_fix, "RTScale Zoom Fix"))
        self.zoom_fix.toggled.connect(self.update_msaa_controls)
        hv.addWidget(assist)
        self.ps5_boost = QCheckBox("PS5 Linux Boost Mode")
        self.ps5_boost.setTristate(True)
        self.ps5_boost.setCheckState(Qt.CheckState.PartiallyChecked)
        self.ps5_boost_status = QLabel()
        try:
            ps5_available = stat.S_ISCHR(os.lstat("/dev/mp1").st_mode)
        except OSError:
            ps5_available = False
        self.ps5_boost.setEnabled(ps5_available)
        self.ps5_boost_status.setText(local("State unknown", "状態不明") if ps5_available
                                      else local("Unavailable on this system", "この環境では利用できません"))
        self._ps5_boost_state = Qt.CheckState.PartiallyChecked
        self.ps5_boost.clicked.connect(self.change_ps5_boost)
        boost_row = QHBoxLayout()
        boost_row.addWidget(help_row(self.ps5_boost, "PS5 Linux Boost Mode"))
        boost_row.addStretch(1)
        boost_row.addWidget(self.ps5_boost_status)
        hv.addLayout(boost_row)
        hv.addSpacing(48)
        hv.addStretch(1)
        self.tabs.addTab(home, "Home")

        # ===== Games =====
        games = QWidget()
        gv = QVBoxLayout(games)
        gv.setContentsMargins(2, 8, 2, 2)
        game_card = Card("Game Profiles", "Detect a running Android game and add it to your profiles.")
        row = QHBoxLayout()
        self.game_combo = QComboBox()
        self.reload_profiles()
        self.btn_detect = QPushButton("Detect Running Game")
        self.btn_detect.clicked.connect(self.detect_game)
        row.addWidget(self.game_combo, 1)
        row.addWidget(self.btn_detect)
        game_card.v.addLayout(row)
        gv.addWidget(game_card)
        gv.addStretch(1)
        games_tab_index = self.tabs.addTab(games, "Games")
        self.tabs.setTabVisible(games_tab_index, False)

        # ===== Maintenance =====
        maint = QWidget()
        mv = QVBoxLayout(maint)
        mv.setContentsMargins(2, 8, 2, 2)
        mv.setSpacing(9)

        mcard = Card("Maintenance")
        mbuttons = QHBoxLayout()
        mbuttons.setSpacing(5)
        for label, fn in [
            ("Doctor", self.doctor),
            ("Save Log", self.logs),
            ("Uninstall MWM", self.uninstall),
        ]:
            b = QPushButton(label)
            b.setMinimumHeight(30)
            b.clicked.connect(fn)
            mbuttons.addWidget(b, 1)
        mcard.v.addLayout(mbuttons)
        mcard.v.addWidget(help_row(self.span_displays, "Span Displays (Experimental)"))
        mv.addWidget(mcard)

        debug_card = Card("RTScale Debug")
        debug_top = QHBoxLayout()
        self.debug_view_mode = QComboBox()
        for label, value in [
            ("Summary", "summary"),
            ("Runtime", "runtime"),
            ("Surface / Display", "surface"),
            ("Mesa / Libraries", "libraries"),
            ("Full Log", "log"),
        ]:
            self.debug_view_mode.addItem(label, value)
        self.debug_view_mode.currentIndexChanged.connect(self.refresh_debug_view)
        self.btn_debug_refresh = QPushButton("Refresh")
        self.btn_debug_copy = QPushButton("Copy")
        self.btn_debug_clear = QPushButton("Clear Log")
        self.btn_debug_refresh.clicked.connect(self.refresh_debug_view)
        self.btn_debug_copy.clicked.connect(self.copy_debug_view)
        self.btn_debug_clear.clicked.connect(self.clear_debug_log)
        debug_top.addWidget(self.debug_view_mode, 1)
        debug_top.addWidget(self.btn_debug_refresh)
        debug_top.addWidget(self.btn_debug_copy)
        debug_top.addWidget(self.btn_debug_clear)
        self.debug_output = QPlainTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setPlaceholderText("RTScale diagnostics are collected automatically at runtime events.")
        self.debug_output.setMinimumHeight(150)
        debug_card.v.addLayout(debug_top)
        debug_card.v.addWidget(self.debug_output)
        mv.addWidget(debug_card, 1)

        log_card = Card("Output")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("MWM output")
        self.output.setMinimumHeight(90)
        log_card.v.addWidget(self.output)
        mv.addWidget(log_card)
        self.tabs.addTab(maint, "Maintenance")

        # Bottom row
        bottom = QHBoxLayout()
        self.btn_reset_defaults = QPushButton("Reset to Defaults")
        self.btn_save = QPushButton("Apply")
        self.btn_refresh = QPushButton("Start")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setToolTip("")
        self.btn_refresh.setObjectName("PrimaryButton")
        self.btn_save.setToolTip("")
        self.btn_refresh.setToolTip("")
        self.btn_reset_defaults.clicked.connect(self.reset_ui_defaults)
        self.btn_save.clicked.connect(self.apply_settings)
        self.btn_refresh.clicked.connect(self.refresh_runtime)
        self.btn_cancel.clicked.connect(self.cancel_and_close)
        bottom.addWidget(self.btn_reset_defaults)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_refresh)
        bottom.addWidget(self.btn_cancel)
        main.addLayout(bottom)

        self.load_backend()
        self.load_current_scale()
        self.update_backend_controls()
        self.load_gamescope_settings()
        try:
            zoom_value = (self.config_dir() / "rtscale-zoom-fix").read_text().strip()
        except (OSError, UnicodeError):
            zoom_value = "on"
        self.zoom_fix.setChecked(zoom_value != "off")
        self.load_mouse_as_touch()
        self.load_performance_overlay_mode()
        self.load_current_aspect()
        self.update_backend_controls()
        self.update_custom_aspect_visibility()
        self.check_saved_settings_consistency()
        self.update_msaa_controls()
        self.update_resolution_preview()
        for control in self.findChildren(QWidget):
            control.setToolTip("")
        for label in self._field_labels:
            label.setFixedWidth(label_column_width)
        self._initial_loading = False
        QTimer.singleShot(0, self.fit_initial_size)

        self._runtime_running = False
        self._runtime_probe = QProcess(self)
        self._runtime_probe.finished.connect(self.runtime_status_received)
        self._runtime_probe_timer = QTimer(self)
        self._runtime_probe_timer.timeout.connect(self.poll_runtime_status)
        self._runtime_probe_timer.start(2000)
        QTimer.singleShot(0, self.poll_runtime_status)

        self.saved_snapshot = self.current_settings_snapshot()
        self._dirty_timer = QTimer(self)
        self._dirty_timer.timeout.connect(self.update_action_buttons)
        self._dirty_timer.start(100)
        self.update_action_buttons()
        QTimer.singleShot(0, self.start_performance_overlay)

    def check_saved_settings_consistency(self):
        """Require Apply when legacy/invalid disk values differ from loaded UI."""
        aspect = self.aspect.currentData()
        if aspect == "custom":
            try:
                aspect = f"{ratio_width(self.custom_w.value(), self.custom_h.value())}x720"
            except ValueError:
                self._needs_backend_migration = True
                return
        expected = {
            "gamescope-span-enabled": "on" if self.span_displays.isChecked() else "off",
            "rtscale-zoom-fix": "on" if self.zoom_fix.isChecked() else "off",
            "rtscale-msaa-samples": str(self.msaa_samples.currentData()),
            "custom-aspect": f"{self.custom_w.value()}:{self.custom_h.value()}",
            "display-backend": str(self.backend.currentData()),
            "gamescope-render-mode": self.selected_render_mode(),
            "aspect-ratio": aspect,
            "kwin-rtscale": str(self.scale.currentData()),
            "gamescope-fsr-enabled": "on" if self.rtscale_fsr_enabled.isChecked() else "off",
            "gamescope-fsr-scale": str(self.gamescope_fsr_scale.currentData()),
            "gamescope-sharpness": str(self.sharpness_level_to_gamescope(self.gamescope_sharpness.value())),
            "gamescope-fsr-sharpness-enabled": "on" if self.rtscale_fsr_enabled.isChecked() else "off",
            "gamescope-cas-enabled": "off",
            "gamescope-cas-strength": str(self.cas_strength.value()),
            "performance-overlay-mode": str(self.overlay_mode.currentData()),
            "mouse-as-touch": "on" if self.fake_touch.isChecked() else "off",
            "auto-start-mirishita": "on" if self.auto_start.isChecked() else "off",
            "verify-waydroid-startup": "on" if self.verify_startup.isChecked() else "off",
        }
        changed = []
        for name, value in expected.items():
            try:
                saved = (self.config_dir() / name).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                saved = None
            if name in ("rtscale-zoom-fix", "auto-start-mirishita", "verify-waydroid-startup") and saved is None:
                saved = "on"  # Backward-compatible default, no silent write.
            if name == "rtscale-msaa-samples" and saved is None:
                saved = "0"
            if name == "custom-aspect" and saved is None:
                saved = value
            if name == "gamescope-span-enabled" and saved is None:
                saved = "off"
            if saved != value:
                changed.append(name)
        for obsolete in OBSOLETE_SETTINGS:
            if (self.config_dir() / obsolete).exists():
                changed.append(obsolete)
        if changed:
            self._needs_backend_migration = True
            self.log("Legacy or unsaved settings detected. Save the displayed settings with Apply before Waydroid Refresh: " + ", ".join(changed))

    def config_dir(self):
        return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mwm"

    def backend_state_path(self):
        return self.config_dir() / "display-backend"

    def load_backend(self):
        try:
            value = self.backend_state_path().read_text(encoding="utf-8").strip().lower()
        except Exception:
            value = "gamescope"
        try:
            render_mode = (self.config_dir() / "gamescope-render-mode").read_text(encoding="utf-8").strip().lower()
        except Exception:
            render_mode = "rtscale" if value == "kwin" else "fsr"
        if render_mode not in ("rtscale", "fsr"):
            render_mode = "rtscale" if value == "kwin" else "fsr"
        # v0.70 debug7fix1 stored both profiles as Gamescope. Preserve the
        # old render-mode meaning while migrating to explicit backends.
        if value != "gamescope":
            value = "gamescope"
            self._needs_backend_migration = True
        self._loaded_render_mode = render_mode
        self.backend.setCurrentIndex(0)

    def selected_render_mode(self):
        if self.backend.currentData() == "kwin":
            return "rtscale"
        if hasattr(self, "scale"):
            return "fsr" if self.scale.currentData() == "off" else "rtscale"
        return "fsr"

    def gamescope_sharpness_state_path(self):
        return self.config_dir() / "gamescope-sharpness"

    def gamescope_fsr_scale_state_path(self):
        return self.config_dir() / "gamescope-fsr-scale"

    def gamescope_fsr_sharpness_enabled_state_path(self):
        return self.config_dir() / "gamescope-fsr-sharpness-enabled"

    @staticmethod
    def sharpness_level_to_gamescope(level):
        return 21 - max(1, min(21, int(level)))

    @staticmethod
    def gamescope_to_sharpness_level(value):
        value = max(0, min(20, int(value)))
        return 21 - value

    def on_gamescope_sharpness_changed(self, value):
        snapped = max(1, min(21, int(value)))
        if snapped != value:
            self.gamescope_sharpness.blockSignals(True)
            self.gamescope_sharpness.setValue(snapped)
            self.gamescope_sharpness.blockSignals(False)
        self.gamescope_sharpness_value.setText(str(snapped))

    def update_gamescope_sharpness_label(self, *_args):
        active = self.rtscale_fsr_enabled.isChecked() and self.backend.currentData() == "gamescope"

        for control in (self.gamescope_fsr_scale, self.fsr_scale_label, self.gamescope_sharpness_label, self.gamescope_sharpness, self.gamescope_sharpness_value):
            control.setEnabled(active)

    def load_gamescope_settings(self):
        path = self.config_dir() / "gamescope-fsr-enabled"
        if not path.exists() and self.selected_render_mode() == "rtscale":
            path = self.config_dir() / "gamescope-rtscale-fsr-enabled"
        try:
            enabled = path.read_text(encoding='utf-8').strip() if path.exists() else "off"
        except (OSError, UnicodeError):
            enabled = "off"
        self.rtscale_fsr_enabled.setChecked(enabled == "on")
        try:
            sharpness = int(self.gamescope_sharpness_state_path().read_text(encoding="utf-8").strip())
        except Exception:
            sharpness = 10
        self.gamescope_sharpness.setValue(self.gamescope_to_sharpness_level(sharpness))
        try:
            enabled = self.gamescope_fsr_sharpness_enabled_state_path().read_text(encoding="utf-8").strip().lower()
        except Exception:
            enabled = "off"
        self.gamescope_fsr_sharpness_enabled.setChecked(enabled in ("on", "1", "true", "yes"))
        if enabled not in ("on", "1", "true", "yes"):
            self.gamescope_sharpness.setValue(1)
        try:
            fsr_scale = int(self.gamescope_fsr_scale_state_path().read_text(encoding="utf-8").strip())
        except Exception:
            fsr_scale = 125
        if fsr_scale not in tuple(self.gamescope_fsr_scale.itemData(i) for i in range(self.gamescope_fsr_scale.count())):
            fsr_scale = 125
        idx = self.gamescope_fsr_scale.findData(fsr_scale)
        self.gamescope_fsr_scale.setCurrentIndex(idx if idx >= 0 else 0)
        try:
            cas = (self.config_dir() / "gamescope-cas-enabled").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            # Preserve CAS from the old combined Sharpness control only where
            # the old pipeline actually used CAS.
            cas = "on" if self.gamescope_fsr_sharpness_enabled.isChecked() and (self.selected_render_mode() == "rtscale" or not self.rtscale_fsr_enabled.isChecked() or fsr_scale != 150) else "off"
        self.cas_enabled.setChecked(False)
        try:
            strength = int((self.config_dir() / "gamescope-cas-strength").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            strength = self.gamescope_sharpness.value()
        self.cas_strength.setValue(max(0, min(100, strength)))
        self.update_gamescope_sharpness_label()

    def update_backend_controls(self, *_args):
        if not hasattr(self, "backend"):
            return
        is_kwin = self.backend.currentData() == "kwin"
        current = int(self.gamescope_fsr_scale.currentData() or 125)
        values = (125, 150, 175, 200)
        self.gamescope_fsr_scale.blockSignals(True)
        self.gamescope_fsr_scale.clear()
        for value in values:
            self.gamescope_fsr_scale.addItem(f"{value}%", value)
        self.gamescope_fsr_scale.setCurrentIndex(values.index(current if current in values else 125))
        self.gamescope_fsr_scale.blockSignals(False)
        self.scale_label.setVisible(True)
        self.scale.setVisible(True)
        self.rtscale_fsr_enabled.setVisible(not is_kwin)
        self.gamescope_fsr_scale.setVisible(not is_kwin)
        self.gamescope_fsr_sharpness_enabled.hide()
        self.gamescope_sharpness_label.setVisible(not is_kwin)
        self.gamescope_sharpness.setVisible(not is_kwin)
        self.gamescope_sharpness_value.setVisible(not is_kwin)
        self.fsr_scale_label.setVisible(not is_kwin)
        for control in (self.cas_enabled, self.cas_strength, self.cas_value):
            control.hide()
        self.rtscale_fsr_enabled.setEnabled(not is_kwin)
        self.update_gamescope_sharpness_label()
        self.update_msaa_controls()
        self.update_resolution_preview()

    def fit_initial_size(self):
        self.layout().activate()
        width = self.minimumSizeHint().width()
        self.setMinimumWidth(width)
        self.resize(width, max(700, self.minimumSizeHint().height()))

    def update_msaa_controls(self, *_args):
        if not hasattr(self, "zoom_fix"):
            return
        self.msaa_samples.setEnabled(self.scale.currentData() not in ("off", "1") and self.zoom_fix.isChecked())

    def update_resolution_preview(self, *_args):
        if not hasattr(self, "resolution"):
            return
        screen = QApplication.primaryScreen()
        size = (screen.geometry().width(), screen.geometry().height()) if screen else (0, 0)
        if self.aspect.currentData() == "auto" and self.span_displays.isChecked():
            self.resolution.setText("Resolution: Auto (Span)")
            return
        try:
            width, height = dimensions(self.aspect.currentData(), self.scale.currentData() != "off",
                                       (self.custom_w.value(), self.custom_h.value()), size)
            self.resolution.setText(f"Resolution: {width}x{height}")
        except (ValueError, KeyError):
            self.resolution.setText("Resolution: --")

    def update_custom_aspect_visibility(self, *_args):
        visible = self.aspect.currentData() == "custom"
        if not hasattr(self, "custom_h"):
            return
        for widget in (self.custom_w, self.custom_h, self.custom_sep):
            widget.setVisible(visible)
        self.update_resolution_preview()

    def log(self, text):
        self.output.appendPlainText(text)

    def async_run(self, cmd, title=None, callback=None, timeout=30):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "MWM", "Another operation is in progress.")
            return
        self.log("$ " + " ".join(map(str, cmd)))
        self.worker = Worker(cmd, timeout)

        def finished(rc, out):
            self.log((out or f"(exit {rc})") + "\n")
            if callback:
                callback(rc, out)
            elif rc != 0:
                QMessageBox.warning(self, title or "MWM", out or f"exit code {rc}")

        self.worker.done.connect(finished)
        # done is emitted inside run(); QThread is still running at that point.
        self.worker.finished.connect(self.update_action_buttons)
        self.worker.start()
        self.update_action_buttons()

    def change_ps5_boost(self):
        """Immediate host control, separate from saved Waydroid settings."""
        previous = self._ps5_boost_state
        if self.worker and self.worker.isRunning():
            self.ps5_boost.setCheckState(previous)
            return
        enabled = self.ps5_boost.isChecked()
        self.ps5_boost.setTristate(False)
        self.ps5_boost_status.setText(local("Applying...", "反映中…"))

        def finished(rc, out):
            if rc == 0:
                self._ps5_boost_state = (Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                self.ps5_boost_status.setText("ON" if enabled else "OFF")
            else:
                self.ps5_boost_status.setText(local("Failed; state unknown", "変更失敗・状態不明"))
                self._ps5_boost_state = Qt.CheckState.PartiallyChecked
                self.ps5_boost.setTristate(True)
                QMessageBox.warning(self, "PS5 Linux Boost Mode", local(
                    "Could not change Boost Mode. Update MWM with ./install.sh --update-app and check the log.",
                    "Boost Modeを変更できませんでした。./install.sh --update-appでMWMを更新し、ログをご確認ください。"))
            self.ps5_boost.setCheckState(self._ps5_boost_state)

        self.async_run(["sudo", "-n", "/usr/local/libexec/mwm-root-helper",
                        "ps5-boost", "on" if enabled else "off"], callback=finished, timeout=10)

    def load_current_scale(self):
        if self.backend.currentData() == "gamescope" and getattr(self, "_loaded_render_mode", "fsr") == "fsr":
            self.scale.setCurrentIndex(self.scale.findData("off"))
            return
        try:
            saved = (self.config_dir() / "kwin-rtscale").read_text(encoding="utf-8").strip()
        except Exception:
            saved = "off"
        if saved in ("9", "10"):
            saved = "8"
        if saved not in (["off"] + [str(i) for i in range(1, 9)]):
            saved = "off"
        self._kwin_scale_cache = saved
        idx = self.scale.findData(saved)
        if idx >= 0:
            self.scale.setCurrentIndex(idx)

    def load_current_aspect(self):
        try:
            value = (self.config_dir() / "aspect-ratio").read_text(encoding="utf-8").strip().lower()
        except OSError:
            value = "auto"
        try:
            custom = (self.config_dir() / "custom-aspect").read_text().strip()
        except OSError:
            custom = value if ("x" in value or value not in ("auto", "32:9", "21:9", "16:9", "4:3", "3:2")) else "16:9"
        width, height = legacy_ratio(custom)
        self.custom_w.setValue(width)
        self.custom_h.setValue(height)
        index = self.aspect.findData(value)
        self.aspect.setCurrentIndex(index if index >= 0 else self.aspect.findData("custom"))

    def performance_overlay_mode_state_path(self):
        return self.config_dir() / "performance-overlay-mode"

    def mouse_as_touch_state_path(self):
        return self.config_dir() / "mouse-as-touch"

    def load_performance_overlay_mode(self):
        # v0.5.50 migration: checkbox + Text/Graph -> Off/Minimal/Detailed.
        try:
            value = self.performance_overlay_mode_state_path().read_text(encoding="utf-8").strip().lower()
        except Exception:
            value = ""
        if value not in ("off", "minimal", "detailed", "mangoapp"):
            try:
                enabled = (self.config_dir() / "performance-overlay").read_text(encoding="utf-8").strip().lower() not in ("off", "0", "false", "no")
            except Exception:
                enabled = False
            try:
                old_style = (self.config_dir() / "performance-overlay-style").read_text(encoding="utf-8").strip().lower()
            except Exception:
                old_style = "text"
            value = ("detailed" if old_style == "graph" else "minimal") if enabled else "off"
        idx = self.overlay_mode.findData(value)
        if idx >= 0 and not self.overlay_mode.model().item(idx).isEnabled():
            idx = 0
        self.overlay_mode.setCurrentIndex(idx if idx >= 0 else 0)

    def load_mouse_as_touch(self):
        state = self.mouse_as_touch_state_path()
        if state.exists():
            try:
                value = state.read_text(encoding="utf-8").strip().lower()
                self.fake_touch.setChecked(value not in ("off", "0", "false", "no"))
                return
            except Exception:
                pass
        try:
            rc, out = run([SCRIPTS / "fake-touch.sh", "status"], 5)
            enabled = rc == 0 and out.strip() == "on"
            if out.strip() == "unavailable":
                enabled = True
        except Exception:
            enabled = True
        self.fake_touch.setChecked(enabled)

    def current_settings_snapshot(self):
        return (
            self.backend.currentIndex(), self.backend.currentData(), self.selected_render_mode(), self.scale.currentData(),
            self.aspect.currentData(), int(self.custom_w.value()), int(self.custom_h.value()), self.msaa_samples.currentData(), self.span_displays.isChecked(),
            int(self.gamescope_fsr_scale.currentData()), int(self.gamescope_sharpness.value()),
            bool(self.gamescope_fsr_sharpness_enabled.isChecked()), bool(self.rtscale_fsr_enabled.isChecked()),
            self.overlay_mode.currentData(), bool(self.fake_touch.isChecked()), bool(self.zoom_fix.isChecked()), bool(self.auto_start.isChecked()), bool(self.verify_startup.isChecked()), bool(self.cas_enabled.isChecked()), int(self.cas_strength.value()),
        )

    def poll_runtime_status(self):
        if self._refresh_in_progress or self._runtime_probe.state() != QProcess.NotRunning:
            return
        # Run outside the GUI thread; a slow Waydroid status must not freeze it.
        self._runtime_probe.start("bash", ["-c",
            '"$1" status; waydroid status', "mwm-status", str(SCRIPTS / "gamescope-control.sh")])
        QTimer.singleShot(1500, self.expire_runtime_probe)

    def expire_runtime_probe(self):
        if self._runtime_probe.state() != QProcess.NotRunning:
            self._runtime_probe.kill()

    def runtime_status_received(self, exit_code, exit_status):
        output = bytes(self._runtime_probe.readAllStandardOutput()).decode("utf-8", errors="replace")
        import re
        output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
        if exit_status == QProcess.NormalExit:
            self._runtime_running = any(
                line.startswith("running pid=") or
                (line.strip().startswith("Session:") and "RUNNING" in line)
                for line in output.splitlines()
            )
        self.update_action_buttons()

    def update_action_buttons(self):
        busy = self._refresh_in_progress or self._apply_delay_pending or bool(self.worker and self.worker.isRunning())
        self.tabs.setEnabled(not busy)
        dirty = self._needs_backend_migration or self.current_settings_snapshot() != self.saved_snapshot
        self.btn_save.setEnabled(not busy and dirty)
        self.btn_refresh.setEnabled(not busy and not dirty and time.monotonic() >= self._settings_ready_at)
        self.btn_reset_defaults.setEnabled(not busy)
        self.btn_cancel.setEnabled(not busy)
        label = "Restart" if self._runtime_running else "Start"
        if self._refresh_in_progress:
            try:
                phase_path = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mwm" / "refresh-phase"
                label = phase_path.read_text(encoding="utf-8").strip()[:32] or "Working..."
            except (OSError, UnicodeError):
                label = "Working..."
        elif self._apply_delay_pending:
            label = "Waiting to start..."
        self.btn_refresh.setText(label)

    def reset_ui_defaults(self):
        answer = QMessageBox.question(
            self, local("Reset to Defaults", "初期設定に戻す"),
            local("Reset the displayed settings? Unsaved changes will be lost. Click Apply afterwards to save.",
                  "画面上の設定を初期値に戻しますか？編集中の変更は失われます。保存するにはApplyを押してください。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.span_displays.setChecked(False)
        self._reset_requested = True
        self.verify_startup.setChecked(True)
        self.auto_start.setChecked(True)
        self.backend.setCurrentIndex(0)
        self.rtscale_fsr_enabled.setChecked(False)
        idx = self.scale.findData("off"); self.scale.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.aspect.findData("auto"); self.aspect.setCurrentIndex(idx if idx >= 0 else 0)
        self.custom_w.setValue(16)
        self.custom_h.setValue(9)
        self.msaa_samples.setCurrentIndex(0)
        idx = self.gamescope_fsr_scale.findData(125); self.gamescope_fsr_scale.setCurrentIndex(idx if idx >= 0 else 0)
        self.gamescope_sharpness.setValue(11)
        self.cas_enabled.setChecked(False)
        self.cas_strength.setValue(50)
        self.gamescope_fsr_sharpness_enabled.setChecked(False)
        idx = self.overlay_mode.findData("off"); self.overlay_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.fake_touch.setChecked(True)
        self.zoom_fix.setChecked(True)
        self.update_backend_controls(); self.update_action_buttons()
        self.log("Defaults loaded into the UI. Apply saves them; Waydroid Refresh applies saved settings and leaves Android home ready for manual game launch.")

    def save_settings(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "MWM", "Another operation is in progress.")
            return
        requested_snapshot = self.current_settings_snapshot()
        try:
            aspect = self.aspect.currentData()
            if aspect == "custom":
                aspect = f"{ratio_width(self.custom_w.value(), self.custom_h.value())}x720"
            values = {
                "display-backend": str(self.backend.currentData()),
                "gamescope-render-mode": self.selected_render_mode(),
                "aspect-ratio": aspect,
                "kwin-rtscale": str(self.scale.currentData()),
                "gamescope-fsr-enabled": "on" if self.rtscale_fsr_enabled.isChecked() else "off",
                "gamescope-fsr-scale": str(self.gamescope_fsr_scale.currentData()),
                "gamescope-sharpness": str(self.sharpness_level_to_gamescope(self.gamescope_sharpness.value())),
                "gamescope-fsr-sharpness-enabled": "on" if self.rtscale_fsr_enabled.isChecked() else "off",
            "gamescope-cas-enabled": "off",
            "gamescope-cas-strength": str(self.cas_strength.value()),
                "mouse-as-touch": "on" if self.fake_touch.isChecked() else "off",
                "gamescope-span-enabled": "on" if self.span_displays.isChecked() else "off",
                "rtscale-zoom-fix": "on" if self.zoom_fix.isChecked() else "off",
                "rtscale-msaa-samples": str(self.msaa_samples.currentData()),
                "custom-aspect": f"{self.custom_w.value()}:{self.custom_h.value()}",
                "performance-overlay-mode": str(self.overlay_mode.currentData()),
                "auto-start-mirishita": "on" if self.auto_start.isChecked() else "off",
            "verify-waydroid-startup": "on" if self.verify_startup.isChecked() else "off",
            }
            commit_settings(self.config_dir(), values, OBSOLETE_SETTINGS)
        except Exception as e:
            self._needs_backend_migration = True
            self.update_action_buttons()
            QMessageBox.warning(self, "Apply", f"Could not save settings: {e}")
            return False
        self._settings_ready_at = time.monotonic() + 0.5
        QTimer.singleShot(501, self.update_action_buttons)
        self.saved_snapshot = requested_snapshot
        self._reset_requested = False
        self._needs_backend_migration = False
        self.update_action_buttons()
        label = "KDE / KWin + RTScale" if self.backend.currentData() == "kwin" else ("Gamescope + RTScale" if self.selected_render_mode() == "rtscale" else "Gamescope + FSR1")
        self.log(f"Applied settings saved for {label}. Rendering settings take effect after Waydroid Refresh; FPS Counter applies now.")
        if not self.start_performance_overlay():
            QMessageBox.warning(self, "FPS Counter", "Settings were saved, but the FPS counter could not be updated. Check the log.")
        try:
            run([SCRIPTS / "rtscale-debug.sh", "event", "settings-saved"], 5)
        except Exception:
            pass
        return True

    def apply_settings(self):
        """Commit settings; Refresh remains an explicit separate action."""
        if self._apply_delay_pending or self._refresh_in_progress:
            return
        self.save_settings()

    def _start_apply_refresh(self):
        if not self._apply_delay_pending:
            return
        self._apply_delay_pending = False
        self.update_action_buttons()
        self.refresh_runtime()

    def refresh_runtime(self):
        if self._apply_delay_pending:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "MWM", "Another operation is in progress.")
            return

        # Refresh only applies the last saved settings. Unsaved edits stay in
        # the UI until Apply is pressed, keeping commit and restart distinct.
        requested_snapshot = self.current_settings_snapshot()
        if self._needs_backend_migration or requested_snapshot != self.saved_snapshot:
            QMessageBox.information(self, "MWM", "Save your settings with Apply first.")
            return
        try:
            saved_backend = self.backend_state_path().read_text(encoding="utf-8").strip()
            if saved_backend != self.backend.currentData():
                raise RuntimeError(f"Saved Backend mismatch: UI={self.backend.currentData()} saved={saved_backend}")
        except Exception as e:
            QMessageBox.warning(self, "Waydroid Refresh", f"Could not verify saved settings: {e}")
            return

        remaining = self._settings_ready_at - time.monotonic()
        if remaining > 0:
            self._apply_delay_pending = True
            self.update_action_buttons()
            self.log(f"Waydroid Refresh: waiting {remaining:.2f}s after Apply before restarting...")
            QTimer.singleShot(max(1, int(remaining * 1000) + 1), self._start_apply_refresh)
            return

        # Normal Refresh stops the HUD in stop_all_verified; a fast update keeps it.
        self._refresh_in_progress = True
        try:
            phase_dir = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mwm"
            phase_dir.mkdir(parents=True, exist_ok=True)
            (phase_dir / "refresh-phase").write_text("Preparing...\n", encoding="utf-8")
        except OSError:
            pass
        self.update_action_buttons()
        verification = self.verify_startup.isChecked()
        automatic = verification and self.auto_start.isChecked()
        preparation = PreparationDialog(self) if verification else None
        self._preparation_dialog = preparation
        if preparation is not None:
            preparation.show()
        target = "KDE / KWin + RTScale" if self.backend.currentData() == "kwin" else ("Gamescope + RTScale" if self.selected_render_mode() == "rtscale" else "Gamescope + FSR1")
        self.log(f"Waydroid Refresh: using saved backend={saved_backend}, target={target}; checking fast refresh eligibility...")

        def cb(rc, out):
            if rc == 0 and automatic:
                self.showMinimized()
            if preparation is not None:
                preparation.finish()
            self._preparation_dialog = None
            self._refresh_in_progress = False
            self.update_action_buttons()
            self.poll_runtime_status()
            if rc == 130:
                self.stop_performance_overlay()
                self.log("Waydroid Refresh cancelled: Gamescope was closed.")
                return
            expected_backend = saved_backend
            import re
            reported = re.search(r"(?:Started|Restarted|Refreshed) / backend=(kwin|gamescope)", out or "")
            if rc == 0 and (reported is None or reported.group(1) != expected_backend):
                actual = reported.group(1) if reported else "not confirmed"
                QMessageBox.warning(
                    self, "Backend mismatch",
                    f"Could not verify the selected backend ({expected_backend}) against the restart result ({actual}).\n{out or ''}",
                )
                self.log(f"Backend verification failed: expected={expected_backend}, reported={actual}")
                return
            if rc == 76 or "MWM_REFRESH_EARLY_LAUNCH:" in (out or ""):
                QMessageBox.warning(self, "Waydroid Refresh Interrupted", "Waydroid Refresh was interrupted because Mirishita launched while settings were being applied.\nSome settings may have been applied.\nClose Mirishita and run Waydroid Refresh again.")
                return
            if rc != 0:
                QMessageBox.warning(self, "Waydroid", out or "Waydroid Refresh failed")
                if rc == 124:
                    self.log("Operation interrupted. Gamescope or Waydroid may still be running. Check their status before retrying Refresh.")
                return
            self.applied_once = True
            if self.overlay_mode.currentData() != "off":
                self.start_performance_overlay()
            else:
                self.stop_performance_overlay()
            if not verification:
                self.log("設定反映処理が完了しました。起動確認は省略しています。ミリシタは手動で起動してください。")
                return
            ready_message = "Settings are applied and Mirishita has started." if self.auto_start.isChecked() else "Click OK, then launch Mirishita from the Android home screen."
            self.log(ready_message)
            if not self.auto_start.isChecked():
                QMessageBox.information(self, "Waydroid Ready",
                    "Saved settings have been applied and the display and session have been verified.\n\n" + ready_message)
            if self.tabs.currentIndex() == 2:
                self.refresh_debug_view()

        self.async_run([SCRIPTS / "waydroid-control.sh", "restart"], callback=cb, timeout=180)

    def uninstall(self):
        if self._refresh_in_progress or self._apply_delay_pending or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self, "Uninstall MWM", "Wait for the current operation to finish.")
            return
        script = SCRIPTS / "uninstall.sh"
        if not script.is_file():
            QMessageBox.warning(self, "Uninstall MWM", "Uninstaller files are missing. Update MWM from the distribution ZIP.")
            return
        terminal = next((shutil.which(name) for name in ("konsole", "xterm") if shutil.which(name)), None)
        if terminal is None:
            QMessageBox.information(self, "Uninstall MWM", "Open a terminal and run ./uninstall.sh from the extracted distribution folder.")
            return
        rc, backup = run(["sudo", "-n", "/usr/local/libexec/mwm-root-helper", "backup-status"], 8)
        if rc not in (0, 3):
            QMessageBox.warning(self, "Uninstall MWM", "Could not verify the backup. Check its permissions and status.\n" + (backup or ""))
            return
        app_only = rc == 3
        if app_only:
            title = "No Backup Found"
            message = "No backup was found. Remove MWM only?\n\nCurrent Waydroid settings, graphics files, and game data will be retained.\nMWM settings, logs, launchers, and permission rules will be removed."
            answer = QMessageBox.question(self, title, message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                metadata = json.loads(backup)
                created = metadata.get("created", "Unknown")
            except (ValueError, TypeError):
                QMessageBox.warning(self, "Uninstall MWM", "Could not read the backup metadata.")
                return
            message = "Restore the files and settings modified by MWM, then remove MWM.\n\nBackup date: " + created + "\nOnly MWM modification targets will be restored. Current game data will be retained."
            answer = QMessageBox.question(self, "Uninstall MWM", message, QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Ok:
                return
        # The detached terminal waits for this GUI to exit before checking locks.
        wrapper = 'gui_pid="$1"; shift; for i in {1..200}; do kill -0 "$gui_pid" 2>/dev/null || break; sleep 0.1; done; if kill -0 "$gui_pid" 2>/dev/null; then echo "Could not confirm that MWM has closed."; rc=1; else bash "$@"; rc=$?; fi; printf "\nExit code: %s\nPress Enter to close." "$rc"; read -r answer; exit "$rc"'
        args = ["-e", "bash", "-c", wrapper, "mwm-uninstall", str(os.getpid()), str(script)]
        args.append("--app-only-confirmed" if app_only else "--restore-confirmed")
        started, _ = QProcess.startDetached(terminal, args)
        if not started:
            QMessageBox.warning(self, "Uninstall MWM", "Could not open a terminal.")
            return
        self.close()

    def cancel_and_close(self):
        self.close()

    def performance_overlay_command(self):
        command = [
            sys.executable, str(ROOT / "fps_overlay.py"),
            "--style", self.overlay_mode.currentData(),
            "--size", "small", "--position", "top-left",
            "--interval", "0.2", "--follow-window",
        ]
        return command

    def start_performance_overlay(self):
        rc, out = run([sys.executable, SCRIPTS / "performance-overlay.py", "sync", "--if-running"], 5)
        self.log(out or "FPS Counter: no status returned")
        return rc == 0

    def stop_performance_overlay(self):
        rc, out = run([sys.executable, SCRIPTS / "performance-overlay.py", "stop"], 5)
        self.log(out or "FPS Counter: no status returned")
        return rc == 0

    def load_profiles(self):
        try:
            return json.loads(PROFILES.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_profiles(self, data):
        PROFILES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def reload_profiles(self):
        if not hasattr(self, "game_combo"):
            return
        current = self.game_combo.currentData() if self.game_combo.count() else None
        self.game_combo.clear()
        for pkg, p in self.load_profiles().items():
            self.game_combo.addItem(f'{p.get("name", pkg)}  ({pkg})', pkg)
        if current:
            idx = self.game_combo.findData(current)
            if idx >= 0:
                self.game_combo.setCurrentIndex(idx)

    def detect_game(self):
        def cb(rc, out):
            pkg = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0 or "." not in pkg:
                QMessageBox.warning(self, "Detect Running Game", "Could not detect the foreground Android app.\n\n" + out)
                return
            profiles = self.load_profiles()
            if pkg in profiles:
                QMessageBox.information(self, "MWM", "This app is already registered.")
                return
            suggested = KNOWN_NAMES.get(pkg, pkg)
            name, ok = QInputDialog.getText(self, local("Register Running Game", "起動中のゲームを登録"), local(f"Package: {pkg}\n\nDisplay name:", f"パッケージ：{pkg}\n\n表示名："), text=suggested)
            if not ok:
                return
            profiles[pkg] = {
                "name": name.strip() or suggested,
                "package": pkg,
            }
            self.save_profiles(profiles)
            self.reload_profiles()
        self.async_run([SCRIPTS / "detect-running-app.sh"], callback=cb)

    def on_tab_changed(self, index):
        if index == 2 and not self.debug_output.toPlainText().strip():
            QTimer.singleShot(0, self.refresh_debug_view)

    def refresh_debug_view(self, *_args):
        mode = self.debug_view_mode.currentData() if hasattr(self, "debug_view_mode") else "summary"
        try:
            rc, out = run([SCRIPTS / "rtscale-debug.sh", "view", mode], 12)
        except Exception as e:
            rc, out = 99, f"{type(e).__name__}: {e}"
        self.debug_output.setPlainText(out or f"(exit {rc})")

    def copy_debug_view(self):
        QApplication.clipboard().setText(self.debug_output.toPlainText())

    def clear_debug_log(self):
        rc, out = run([SCRIPTS / "rtscale-debug.sh", "clear"], 5)
        if rc != 0:
            QMessageBox.warning(self, "RTScale Debug", out or "Could not clear log")
        self.refresh_debug_view()

    def doctor(self):
        self.async_run([SCRIPTS / "doctor.sh"], title="Doctor", timeout=30)

    def logs(self):
        path = ROOT / "logs" / f"mwm-{time.strftime('%Y%m%d-%H%M%S')}.log"
        def saved(rc, out):
            if rc != 0:
                QMessageBox.warning(self, "Diagnostic Log", out or "Could not collect diagnostic logs.")
                return
            QMessageBox.information(self, "Diagnostic Log Saved", f"Send this single file when reporting a problem.\n{path}")
        self.async_run([SCRIPTS / "collect-logs.sh", path], callback=saved, timeout=180)

    def closeEvent(self, event):
        if self._refresh_in_progress or self._apply_delay_pending or (self.worker and self.worker.isRunning()):
            event.ignore()
            return
        if self.current_settings_snapshot() != self.saved_snapshot:
            answer = QMessageBox.question(self, "Unsaved Changes", "Discard unsaved changes and close?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._apply_delay_pending = False
        # The HUD belongs to the running display session, not this settings window.
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # One GUI per user, shared by both installed entry points.
    instance_dir = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mwm"
    try:
        instance_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        QMessageBox.warning(None, "MWM", f"Could not create the startup state folder.\n{error}")
        sys.exit(1)
    instance_lock = QLockFile(str(instance_dir / "mwm-gui.lock"))
    # Do not expire a lock just because the GUI has been open a long time.
    # Qt still detects stale locks left by a terminated process.
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        if instance_lock.error() == QLockFile.LockError.LockFailedError:
            message = "MWM is already running. Use the existing MWM window."
        else:
            message = "Could not create the MWM startup lock. Check folder permissions and available disk space."
        QMessageBox.warning(None, "MWM", message)
        sys.exit(1)
    app.aboutToQuit.connect(instance_lock.unlock)
    try:
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mwm"
        if recover_settings(config):
            QMessageBox.information(None, "MWM", "Recovered an interrupted settings save. Please review your settings.")
    except Exception as error:
        QMessageBox.warning(None, "MWM", f"Could not verify the settings state. Start MWM after the current operation finishes or the issue is resolved.\n{error}")
        sys.exit(1)
    app.setStyleSheet("""
        QWidget { font-size: 12px; }
        QMainWindow, QWidget { background: #202124; color: #f2f2f2; }
        #AppTitle { font-size: 19px; font-weight: 700; }
        #Muted { color: #a9adb3; }
        #Card {
            background: #2a2c30;
            border: 1px solid #3a3d43;
            border-radius: 9px;
        }
        #CardTitle { font-size: 14px; font-weight: 700; }
        #CollapseHeader {
            font-size: 14px;
            font-weight: 700;
            color: #f2f2f2;
            padding: 2px;
        }
        QPushButton {
            background: #35383e;
            border: 1px solid #4a4d54;
            border-radius: 6px;
            padding: 6px 12px;
            min-height: 22px;
        }
        QPushButton:hover { background: #41454c; }
        QPushButton:disabled { color: #70747a; background: #292b2f; border-color: #34363a; }
        #PrimaryButton { font-weight: 700; }
        QComboBox, QSpinBox {
            background: #17181b;
            border: 1px solid #45484f;
            border-radius: 6px;
            padding: 5px 7px;
            min-height: 22px;
        }
        QTabWidget::pane { border: none; }
        QTabBar::tab { background: transparent; padding: 7px 14px; color: #aeb2b8; }
        QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #ffffff; }
        QPlainTextEdit {
            background: #141518;
            border: 1px solid #3b3e44;
            border-radius: 7px;
            padding: 7px;
            font-family: monospace;
        }
    """)
    w = MainWindow()
    # Show the settings window without requesting activation from KWin.
    # Users can still focus it normally by clicking the window or taskbar.
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    w.show()
    sys.exit(app.exec())

"""Exercise settings navigation with Qt keyboard events, including cancel."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mwm'))
try:
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QPushButton
    import lite
    HAVE_QT=True
except ImportError:
    HAVE_QT=False


@unittest.skipUnless(HAVE_QT,'PySide6 is required for settings UI tests')
class SettingsTests(unittest.TestCase):
    def exercise(self,cancel):
        app=QApplication.instance() or QApplication([])
        errors=[]
        def drive():
            try:
                window=next(w for w in app.topLevelWidgets() if w.windowTitle()=='MWM Lite Settings' and w.isVisible())
                scale=window.findChild(QComboBox)
                fps=next(w for w in window.findChildren(QCheckBox) if w.text()=='FPS Counter')
                save=window.findChild(QPushButton)
                QTest.keyClick(scale,Qt.Key.Key_Right)
                self.assertEqual(scale.currentData(),6)
                QTest.keyClick(scale,Qt.Key.Key_Down)
                self.assertEqual(window.focusWidget(),fps)
                QTest.keyClick(fps,Qt.Key.Key_Return)
                self.assertTrue(fps.isChecked())
                if cancel:
                    QTest.keyClick(fps,Qt.Key.Key_Escape)
                else:
                    QTest.keyClick(fps,Qt.Key.Key_Down)
                    self.assertEqual(window.focusWidget(),save)
                    QTest.keyClick(save,Qt.Key.Key_Return)
            except Exception as error:
                errors.append(error);app.quit()
        with tempfile.TemporaryDirectory() as d,patch.object(lite,'CONFIG',Path(d)/'settings.json'),patch.object(lite,'boost_available',return_value=False):
            QTimer.singleShot(50,drive)
            lite.settings_ui()
            if errors:raise errors[0]
            if cancel:
                self.assertFalse(lite.CONFIG.exists())
            else:
                self.assertEqual(lite.load_settings(),dict(scale=6,fps=True,boost=False))

    def test_controller_keyboard_layout_saves(self):self.exercise(False)
    def test_escape_does_not_save(self):self.exercise(True)


if __name__=='__main__':unittest.main()

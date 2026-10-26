#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Small FPS-only counter owned by the Lite launcher."""
import signal
import sys
from pathlib import Path
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication, QLabel


def main():
    app = QApplication(sys.argv)
    label = QLabel('FPS --.--')
    label.setWindowTitle('MWM Lite FPS')
    label.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    label.setStyleSheet('background: #202020; color: white; padding: 8px; font: 18px monospace')
    label.move(12, 12)
    label.show()
    collector = QProcess()
    collector.setProgram('bash')
    collector.setArguments([str(Path(__file__).resolve().parent/'scripts/fps-collector.sh'), '0.2'])
    pending = bytearray()
    def update():
        pending.extend(bytes(collector.readAllStandardOutput()))
        while b'\n' in pending:
            line, _, rest = pending.partition(b'\n')
            pending[:] = rest
            try:
                fps = float(line.split()[0])
                label.setText(f'FPS {fps:.2f}' if 0 < fps <= 240 else 'FPS --.--')
            except (ValueError, IndexError):
                label.setText('FPS --.--')
    collector.readyReadStandardOutput.connect(update)
    collector.finished.connect(app.quit)
    collector.errorOccurred.connect(lambda *_: app.quit())
    collector.start()
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    # Python signal delivery needs regular returns from Qt to the interpreter.
    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)
    try:
        return app.exec()
    finally:
        collector.terminate()
        if not collector.waitForFinished(3000):
            collector.kill()
            collector.waitForFinished(3000)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Register the two MWM Lite entries with native Linux Steam."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from steam_shortcuts import accounts, register
from lite_host import desktop_kind, install_gnome_extension, remove_gnome_extension

STATE = Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'mwm-lite'
BIN = Path.home()/'.local/bin'


def choose(user_id=None, steam_root=None):
    options = accounts()
    if user_id:
        options = [(root, user) for root, user in options if user == user_id]
    if steam_root:
        options = [(root, user) for root, user in options if root == Path(steam_root).resolve()]
    if len(options) != 1:
        raise ValueError('Select one Steam account in the setup window, or use --user-id and --steam-root. Launch native Steam and sign in once if no accounts are listed.')
    return options[0]


def setup_ui():
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle('MWM Lite Steam Setup')
    window.setMinimumSize(640, 520)
    window.setStyleSheet('QWidget {font-size:20px;} QPushButton,QComboBox {padding:10px;}')
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel('MWM Lite — Steam Setup'))
    instructions = QLabel('Launch native Steam and sign in once, then exit Steam completely. Register both entries below. Your other shortcuts and controller settings are preserved.')
    instructions.setWordWrap(True)
    layout.addWidget(instructions)
    account = QComboBox()
    for root, user in accounts():
        account.addItem('Account '+user+' — '+str(root), (root, user))
    layout.addWidget(account)
    status = QLabel('Mirishita (MWM Lite)\nMWM Lite Settings')
    status.setWordWrap(True)
    layout.addWidget(status)
    button = QPushButton('Register both entries')
    button.setEnabled(account.count() > 0)
    def perform():
        try:
            root, user = account.currentData()
            result = register(root, user, BIN, STATE)
            status.setText('Registered. Start Steam Big Picture and open your Library.\nChoose a mouse / keyboard Steam Input layout for both entries.\nGame: right stick → mouse, trigger → left click.\nSettings: D-pad → arrow keys, A → Enter, B → Escape.')
            if result['backup']:
                status.setText(status.text()+'\nBackup: '+result['backup'])
        except Exception as error:
            QMessageBox.warning(window, 'MWM Lite Steam Setup', str(error))
    button.clicked.connect(perform)
    layout.addWidget(button)
    guidance = QLabel('Ubuntu and CachyOS use the same registration. Native Steam is required; Flatpak Steam is not configured by this tool. Initial Waydroid / Mirishita installation belongs to MWI.')
    guidance.setWordWrap(True)
    layout.addWidget(guidance)
    if desktop_kind() == 'gnome':
        gnome = QPushButton('Enable GNOME fullscreen support')
        def enable_gnome():
            try:
                ready = install_gnome_extension(Path(__file__).resolve().parent/'gnome_extension')
                status.setText('GNOME fullscreen support is active.' if ready else
                    'Extension installed. Log out and back in, then use this button again to enable it. Save your work before logging out.')
            except Exception as error:
                QMessageBox.warning(window, 'GNOME fullscreen support', str(error))
        gnome.clicked.connect(enable_gnome)
        layout.addWidget(gnome)
    start = QPushButton('Open Steam Big Picture')
    start.setEnabled(shutil.which('steam') is not None)
    start.clicked.connect(lambda: subprocess.Popen(['steam','-bigpicture']))
    layout.addWidget(start)
    close = QPushButton('Close')
    close.clicked.connect(window.close)
    layout.addWidget(close)
    window.show()
    return app.exec()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--register',action='store_true',help='register without opening the setup window')
    mode.add_argument('--list',action='store_true',help='list detected native Steam accounts')
    mode.add_argument('--enable-gnome', action='store_true',help='install/enable the user GNOME fullscreen extension')
    mode.add_argument('--remove-gnome',action='store_true',help='disable and remove unmodified MWM Lite GNOME extension files')
    parser.add_argument('--user-id')
    parser.add_argument('--steam-root',type=Path)
    args = parser.parse_args()
    try:
        if args.remove_gnome:
            remove_gnome_extension(Path(__file__).resolve().parent/'gnome_extension')
            return 0
        if args.enable_gnome:
            active = install_gnome_extension(Path(__file__).resolve().parent/'gnome_extension')
            print('GNOME fullscreen active' if active else 'Installed: log out/in and rerun --enable-gnome')
            return 0 if active else 2
        if args.list:
            print(json.dumps([{'root':str(root),'user_id':user} for root,user in accounts()]))
            return 0
        if args.register:
            root,user = choose(args.user_id,args.steam_root)
            print(json.dumps(register(root,user,BIN,STATE)))
            return 0
        return setup_ui()
    except Exception as error:
        print('MWM Lite Steam Setup: '+str(error),file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

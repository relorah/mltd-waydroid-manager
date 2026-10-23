# SPDX-License-Identifier: MIT
"""Click-only help bubbles; Japanese OS locales use Japanese, otherwise English."""
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QDialog, QVBoxLayout, QLabel

def local(en, ja):
    return ja if QLocale.system().language() == QLocale.Language.Japanese else en

HELP = {
 'PS5 Linux Boost Mode': ('Immediately switch the PS5 host Boost Mode. Applies system-wide, without Apply or Restart. Initial state is unknown because the driver provides no readback. ON/OFF indicates the last successful request in this MWM session; external changes are not tracked. Closing MWM does not restore it. May increase power use and heat.', 'PS5本体のBoost Modeを即時切り替えます。システム全体に適用され、ApplyやRestartは不要です。状態取得APIがないため初期表示は状態不明です。ON/OFFは今回のMWMで最後に成功した操作を示し、外部からの変更は追跡しません。MWMを閉じても元に戻りません。消費電力や発熱が増える場合があります。'),
 'RTScale': ('Render 3D at a higher resolution. The multiplier applies to width and height; higher values increase GPU load.', '3Dレンダリングを高解像度化します。倍率は幅・高さに適用され、高倍率ほどGPU負荷が増えます。'),
 'MSAA Sample Limit': ('Original preserves the game\'s requested MSAA sample count (four in the measured path). 2 Samples reduces antialiasing quality and GPU load on RTScale-scaled targets. Requires RTScale x2 or higher and Zoom Fix.', 'Originalはゲーム本来のMSAAサンプル数を維持します（確認した描画経路では4）。2 Samplesは対象の輪郭の滑らかさと引き換えにGPU負荷を抑えます。RTScale x2以上・Zoom Fix ONで適用されます。'),
 'AMD FSR1': ('Gamescope applies FSR1 upscaling (EASU) and sharpening (RCAS) to the rendered image, after the RTScale rendering stage.', 'RTScaleによるレンダリング後の画像に、Gamescopeでアップスケーリング（EASU）とシャープニング（RCAS）を適用します。'),
 'Upscale': ('FSR1 EASU upscaling factor. Higher factors increase upscaling workload.', 'FSR1のEASUによるアップスケール倍率です。高倍率ほど拡大処理の負荷が増えます。'),
 'Sharpness': ('FSR1 RCAS sharpening strength: 1 is the minimum and 21 the maximum. Strong sharpening may emphasize edges or shimmering.', 'FSR1のRCASによるシャープニング強度です。1が最小、21が最大です。強くすると輪郭の強調やちらつきが目立つ場合があります。'),
 'Aspect Ratio': ('Choose a preset or enter width and height proportions with Custom. Resolution is calculated automatically.', 'プリセットを選択するか、Customで横と縦の比率を指定します。解像度は自動計算されます。'),
 'FPS Counter': ('Minimal and Detailed use MWM HUD; MangoApp uses the same Android game-layer FPS measurement. Its graph measures Gamescope frame times.', 'MinimalとDetailedはMWM HUDです。MangoAppもAndroid側の同じFPS計測値を表示しますが、グラフはGamescope側のフレーム時間です。'),
 'RTScale Zoom Fix': ('Correct excessive zoom and rendering misalignment, including light compositing, with RTScale. Normally keep this enabled.', 'RTScale使用時の過度な拡大や、光の合成などに生じる描画ずれを補正します。通常はONで使用してください。'),
 'Verify Waydroid Startup': ('Verify Android startup, settings and display stability. OFF skips the final verification and requires manual game launch. Restart stops any running game.', 'Android起動・設定・表示の安定を確認します。OFFでは最後の確認を省略し、ゲームは手動起動になります。Restartではプレイ中のゲームも終了します。'),
 'Auto Launch Mirishita': ('Launch Mirishita after preparation when startup verification is enabled.', '起動確認がONのとき、準備完了後にミリシタを自動起動します。'),
 'Mouse as Touch': ('Treat mouse input as Android touch input.', 'マウス操作をAndroidのタッチ入力として扱います。'),
 'Span Displays (Experimental)': ('Span the Gamescope window across enabled monitors. Auto uses the combined aspect ratio. Experimental; RTScale needs matching calibration.', 'Gamescopeを有効なモニター全体へ表示します。Autoは合成した比率を使用します。試験機能で、RTScaleには対応する計測設定が必要です。'),
}

def help_row(control, key):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(control)
    button = QToolButton(row)
    button.setText('(?)')
    button.setAccessibleName(key + ' help')
    button.setAutoRaise(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet('QToolButton { border: none; padding: 0; color: #9bbbd5; font-size: 10px; }')
    layout.addWidget(button)
    layout.addStretch(1)
    def show():
        bubble = QDialog(row, Qt.Popup)
        bubble.setAttribute(Qt.WA_DeleteOnClose, True)
        text = QLabel(local(*HELP[key]), bubble)
        text.setWordWrap(True)
        text.setMaximumWidth(360)
        box = QVBoxLayout(bubble)
        box.addWidget(text)
        bubble.adjustSize()
        position = button.mapToGlobal(button.rect().bottomLeft())
        screen = button.screen().availableGeometry()
        position.setX(max(screen.left(), min(position.x(), screen.right()-bubble.width())))
        position.setY(max(screen.top(), min(position.y(), screen.bottom()-bubble.height())))
        bubble.move(position)
        row._help_bubble = bubble
        bubble.show()
    button.clicked.connect(show)
    control.setToolTip('')
    return row

# MLTD Waydroid Manager (MWM) 0.92 Setup Guide

MWMは、Waydroid上のミリシタの描画・表示・入力設定を管理するツールです。

## 対象環境

- CachyOS／Arch系LinuxまたはUbuntu 24.04以降、x86_64、AMD GPU、Wayland。
- Waydroid Android 11、Google Play、Native Bridge／ARM変換を導入済みで、ミリシタが正常動作すること。
- sudo権限と、依存パッケージ取得用のネットワーク。

描画バックエンドはGamescopeです。主な動作確認環境はKDE Plasma／WaylandとAMD GPUです。

Ubuntu対応のインストール処理は追加済みですが、Ubuntu実機での動作確認は未実施です。Ubuntu 26.04 LTSではGamescopeを公式multiverseから導入します。24.04 LTSはGamescopeのAPT候補がないため、必要な起動オプションを備えたGamescope 3.16系を先に用意してください。異なるUbuntu版のパッケージを混在させないでください。

UbuntuではPySide6をMWM配下の`.runtime/venv`へ導入します。システムPythonへのpip導入を避け、更新時もこの専用環境を保持します。MWM版MangoAppと表示切替用のmangohudctlはUbuntu上でビルドし、`.runtime/bin`へ配置します。初回はビルド用パッケージと依存ソースの取得が必要です。同じソース・ビルド手順・glibcで作成済みの場合は再ビルドを省略します。

標準GNOMEのWaylandセッションではFPS CounterはMangoAppまたはOffを選択します。MangoAppはGamescope内のXwaylandで表示するため、ホストのGNOMEにlayer-shellは不要です。Minimal／Detailedはlayer-shell対応環境（KDEなど）で使用できます。KDE用のウィンドウ位置・サイズ補助やSpan DisplaysはGNOMEでは利用できません。

MangoAppのビルドに失敗した場合はFPS CounterをOffにして使用できます。通常`~/.local/state/mwm-setup/mangoapp-build.log`を確認し、`./install.sh --update-app`で再試行してください。MangoAppが起動後に異常終了した場合は繰り返し再起動せず、次回Start／Restartまでカウンターを停止します。Ubuntu／PS5用Ubuntuイメージでの実機表示・ゲーム動作は未確認です。

## 導入するもの

ホストへ依存パッケージ、MWM本体、ランチャー、管理処理用のroot helperとsudoers設定を導入します。Waydroidには描画ライブラリをoverlayとして導入し、表示・入力・RTScaleなどの設定を変更します。

RTScaleは、mogareta7731氏が公開した原機能とライブラリの挙動を参考に解析・再構成し、Mesaへ組み込んだMWM独立実装を使用します。描画部品の出典・版は `packaging/payload/manifests/graphics-stack.lock`、ライセンスは `LICENSES/` に記載しています。

修正内容・検証範囲と対応ソースの利用方法は[RTScaleの修正・検証資料](RTSCALE.md)を参照してください。

## インストール・更新

ゲームとMWMを終了し、配布ファイルを展開したフォルダーで実行します。

```bash
chmod +x install.sh
./install.sh
```

既存環境と同梱ファイルを確認し、変更対象をバックアップしてから導入します。更新時は保存設定と初回バックアップを保持します。バックアップ取得に失敗した場合は、描画ファイルを変更する前に中断します。

描画ライブラリも更新する場合は上記を、本体・制御スクリプト・root helperのみ更新する場合は次を使います。

```bash
./install.sh --update-app
```

導入後にGUIを開かない場合は `--no-gui` を追加します。必要な依存パッケージはインストーラーが導入します。

## 基本操作

アプリメニューのMLTD Waydroid Manager、または `~/.local/bin/mwm` で起動します。

1. Homeで描画・表示・Optionsを設定します。
2. **Apply**で保存します。
3. **Start**で起動します。起動中は**Restart**になります。

Applyは設定保存と、起動状態に応じたFPS Counterの更新を行います。AndroidとGamescopeへ描画・表示設定を反映するには、Start／Restartを押してください。Restartはプレイ中のゲームも終了します。未保存の変更がある間はStart／Restartを押せません。

初期値はRTScale OFF、AMD FSR1 OFF、Aspect Ratio Auto、FPS Counter Offです。Optionsの4項目はONです。準備確認後にミリシタを自動起動し、MWMを最小化します。

Reset to Defaultsは画面上の設定を初期値へ戻します。Applyで保存してください。Cancelは設定画面を閉じます。

## 描画・表示設定

| 項目 | 内容 |
| --- | --- |
| RTScale | OFF／x1～x8。対象の内部描画を高解像度化します。高倍率ほどGPU負荷が増えます。 |
| MSAA Sample Limit | MSAA（アンチエイリアス）のサンプル数を設定します。Original (Quality)はゲーム本来の最大4 Samplesを維持します。2 Samples (Performance)はRTScaleで拡大する対象を最大4 Samplesから2 Samplesへ制限して負荷を抑えます。 |
| AMD FSR1 | レンダリング後の画像に、Gamescopeでアップスケーリング（EASU）とシャープニング（RCAS）を適用します。 |
| Upscale | 125%／150%／175%／200%。 |
| Sharpness | 1～21。1が最小強度、21が最大です。 |
| Aspect Ratio | Auto／32:9／21:9／16:9／4:3／3:2／Custom。Customは横・縦の比率を入力します。初期値は16:9です。 |

比率に応じた表示寸法を `Resolution: 1920x1080` の形式で表示します。Customの入力欄は解像度ではなく横：縦の比率です。極端に横長・縦長の比率は指定できません。指定可能な範囲を超えた場合は、表示される案内に従って比率を調整してください。

RTScale ONではWaydroid表示を高さ1080相当とし、RTScaleの基準寸法は別に高さ720で管理します。OSスケール、表示寸法、RTScale倍率は別の設定です。

Super（Windows）＋Fで全画面とウィンドウを切り替えます。複数モニターでは、Waydroid起動時にカーソルがある画面へ表示されます。使用したい画面へカーソルを移してStart／Restartを押し、表示されるまでその画面に置いてください。

## Options

| 項目 | 内容 |
| --- | --- |
| Verify Waydroid Startup | Android起動・設定反映・解像度・表示の継続を確認します。OFFでは必須設定の反映後、表示確認と安定待機を省略します。 |
| Auto Launch Mirishita | 準備確認後にミリシタを自動起動します。Verify OFFではグレーアウトし、手動起動になります。 |
| Mouse as Touch | マウス操作をAndroidのタッチ入力として扱います。 |
| RTScale Zoom Fix | RTScale使用時の過度な拡大や、光の合成などに生じる描画ずれを補正します。通常はONで使用してください。 |

Verify ONの場合、ミリシタの起動処理中はMWMの操作を制限します。途中でミリシタを手動起動すると処理を中断するため、ゲームを終了してStart／Restartをやり直してください。

## FPS Counter

Off／Minimal／Detailed／MangoAppから選択します。MinimalとDetailedはMWM HUD、MangoAppはGamescope内のカウンターです。

| 数値 | 計測対象 |
| --- | --- |
| FPS：全方式 | SurfaceFlingerのミリシタ描画レイヤーの実表示時刻から計算する、Android側の表示更新頻度。MangoAppもMWM HUDと同じ値を表示します。 |
| Frametime：Detailed | Android側の直近の有効なフレーム間隔。 |
| グラフ：MangoApp | Gamescope側のフレーム時間です。Android側のFPS表示とは計測対象が異なるため、一定の時間差（ms）には換算できません。 |
| CPU／GPU | ホスト側の負荷。ミリシタ単体の使用率ではありません。 |

FPS Counterの表示方式は、起動中でも切り替えられます。

### Gamescopeの120 FPS上限（0.92）

Gamescopeの仮想画面を120 Hzで起動し、ゲーム側のFPS上限も既定で120 FPSにします。二段FSRでは内側・外側の両方に仮想120 Hzを指定します。モニタ自体のHzは変更しません。ゲームの描画速度を120 FPSへ引き上げる機能ではありません。

起動直後のFPS低下を拾って上限を下げないよう、自動判定は既定で無効です。検証環境では、再起動後に57 FPSへの張り付きが解消し、モニタ120 Hz／200 Hzで負荷が同じになったことを確認しています。他の環境で同じ結果になる保証はありません。

高度な設定として `~/.config/mwm/gamescope-fps-limit` に `120`、`60`、`off`、`auto` のいずれか1行を書けます。未作成は `120` です。`off` は実行時のFPS上限制御を解除しますが、起動時の仮想120 Hz指定は維持します。設定ファイルの変更は起動中に読み取られます。仮想画面の起動指定を反映するにはStart／Restartが必要です。

`auto` は試験機能です。約5秒間の安定した実測値から60／120 FPSを選び、一時的な低下には追従しません。一度60 FPSに制限すると120 FPSを計測できないため、約10秒間有効なフレームがない場合やGamescope再起動時に判定をやり直します。ゲーム側をプレイ中に120 FPSへ切り替える場合は固定 `120` を使ってください。安定した60／120 FPSを確認できない間は120 FPS上限を維持します。

実行時制御にはGamescope付属の `gamescopectl debug_set_fps_limit` を使用します。利用できない場合はログへ警告し、通常の起動を続けます。仮想120 Hz指定は引き続き有効です。`auto` の計測値はFPS表示と共有し、重複したSurfaceFlinger問い合わせを避けます。

### BC250のGPU使用率（試験機能）

BC250でGPU使用率を正常に取得できない場合に使用する試験機能です。GPUの状態レジスター（GRBM_STATUS）の稼働フラグを一定間隔で読み取り、稼働していた割合からGPU全体の活動率を推定します。

手動で有効にする場合は次を実行し、HUDを起動し直してください。無効にする場合は同じファイルを削除します。

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
touch "${XDG_CONFIG_HOME:-$HOME/.config}/mwm/bc250-gpu-test"
```

## 既知の不具合・未検証事項

- **確認済み**：ガシャの一枚絵が異常に拡大される現象を目視確認しています。
- **未検証**：ガシャ演出中のSSRの3Dモデル表示は未検証です。

RTScale使用時、特定の光源やエフェクトで、処理がキャラクターの前面に重なる、白飛びする、描画位置がずれるなどの異常が発生する場合があります。**RTScale Zoom FixをONにしても、すべての描画異常を解消できるわけではありません。**

RTScaleやFSR1の拡大倍率を高くすると、負荷の増加により描画の乱れやフレーム落ちが発生する場合があります。RCASの強度を上げると、輪郭の強調やちらつきが目立つ場合があります。

## 診断ログ

MaintenanceのDoctorで環境を確認できます。**Save Log**で診断情報をファイルへ保存することができます。

```text
~/.local/share/mwm/logs/mwm-yyyyMMdd-hhmmss.log
```

RTScale Debugでは診断情報の表示・更新・コピー・クリアができます。ログにはユーザー名・ファイルパスなどが含まれるため、共有前に内容をご確認ください。XDGの保存先を変更している場合は、その配下へ保存します。

## バックアップ・アンインストール

初回導入時に、MWMが変更する描画ファイルと表示・入力・音声・RTScale設定を保存します。保存先は `/var/lib/mwm-backups/<UID>/baseline/` です。更新や配布フォルダーの削除後も保持します。復元対象はMWMによる変更箇所で、アプリ・ゲームデータは保持します。

Maintenanceの**Uninstall MWM**を押すか、配布ファイルの展開先で実行します。

```bash
chmod +x uninstall.sh
./uninstall.sh
```

- バックアップあり：変更したファイル・設定を復元し、成功後にMWMを削除します。
- バックアップなし：確認後にMWMのみ削除します。Waydroidの現在の描画環境・設定は保持します。
- バックアップ破損・環境不一致・復元失敗：エラーを表示し、MWMを保持して中断します。

MWM本体、設定、ログ、ランチャー、専用生成物、ユーザー用sudoers設定を削除します。root helperは他ユーザーが利用していなければ削除します。共有の依存パッケージと復旧用バックアップは保持します。

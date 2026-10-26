# MLTD Waydroid Manager (MWM) 0.97 Setup Guide

MWMは、Waydroid上のミリシタの描画・表示・入力設定を管理するツールです。

## 対象環境

- CachyOS／Arch系LinuxまたはUbuntu 26.04 LTS、x86_64、AMD GPU、Wayland。
- Waydroid Android 11、Google Play、Native Bridge／ARM変換を導入済みで、ミリシタが正常動作すること。
- sudo権限と、依存パッケージ取得用のネットワーク。

描画バックエンドはGamescopeです。主な動作確認環境はKDE Plasma／WaylandとAMD GPUです。

PS5 Linux（kernel 7.1.7／Ubuntu 26.04.1／GNOME Wayland）では、MWMからのミリシタ起動とライブMVの動作を確認しています。

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
| Display Mode | Single Display／Dual Display。Dual DisplayはKDE Plasmaで、窓を接続モニタ全体へ拡大します。 |
| FPS Counter | Off／Minimal／Detailed／MangoApp。ゲーム窓の左上へ表示します。 |

比率に応じた表示寸法を `Resolution: 1920x1080` の形式で表示します。Customの入力欄は解像度ではなく横：縦の比率です。極端に横長・縦長の比率は指定できません。指定可能な範囲を超えた場合は、表示される案内に従って比率を調整してください。

RTScale ONではWaydroid表示を高さ1080相当とし、RTScaleの基準寸法は別に高さ720で管理します。OSスケール、表示寸法、RTScale倍率は別の設定です。

Super（Windows）＋Fで全画面とウィンドウを切り替えます。Single Displayでは、Waydroid起動時にカーソルがある画面へ表示されます。使用したい画面へカーソルを移してStart／Restartを押し、表示されるまでその画面に置いてください。

## MWM Lite / Steam Big Picture

MWM Lite は単一画面・常時全画面・Steam Input前提の独立プロファイルです。Ubuntu 24.04以降とCachyOS / Archで共通の実装を使います。Waydroid・ミリシタ・Houdini / test_libnbの初期導入は [MWI](https://github.com/relorah/mltd-waydroid-installer) で行い、ゲームが正常に起動するAndroid 11 / x86_64環境から使用します。

### Liteの導入

```bash
bash install.sh --lite-only
```

既存MWMのアプリ更新は次です。保存済みのDesktop設定とグラフィックスpayloadを保持します。

```bash
bash install.sh --lite-only --update-app
```

Lite専用導入ではGamescope / MangoAppの導入・ビルドを要求しません。通常のMWM Desktopインストール経路は従来のままです。Ubuntuは構成済みのAPT配布元だけを使用し、ホストのカーネル・Mesa・firmware変更を含む依存解決は停止します。

### Steam登録

導入後の `MWM Lite Steam Setup` でアカウントを選択し、Steamを完全終了してから `Register both entries` を実行します。Steamは事前に一度起動・ログインしておく必要があります。

- `Mirishita (MWM Lite)`：ゲーム起動（`~/.local/bin/mwm-lite`）
- `MWM Lite Settings`：全画面の設定画面（`~/.local/bin/mwm-lite-settings`）

登録はネイティブ版Steam用です。Ubuntuの `.steam/debian-installation` とCachyOSの標準保存先を検出します。Flatpak版Steamのサンドボックス設定は対象外です。既存ショートカット・AppID・カスタム引数を保持し、変更前の `shortcuts.vdf` は `~/.local/state/mwm-lite/steam-backups/` に退避します。再実行しても同じ2項目を重複追加しません。Steamが起動中の場合、変更が必要な登録は停止します。

端末からの操作も可能です。

```bash
mwm-lite-steam-setup --list
mwm-lite-steam-setup --register
# 複数アカウントがある場合
mwm-lite-steam-setup --register --user-id ACCOUNT_ID --steam-root /path/to/Steam
```

### デスクトップと全画面

動作するsystemdユーザーセッションとWaylandが必要です。

- Plasma Wayland：`kdotool` でプライマリ画面への全画面配置とFPS位置を維持します。
- Ubuntu / GNOME 46–50：Steam Setupの `Enable GNOME fullscreen support` でユーザー用拡張を導入します。初回はログアウト・再ログイン後、同じボタンで有効化します。拡張は生存確認できるLiteセッション中のWaydroid / FPSウィンドウだけを対象にします。GNOME実機動作は未確認です。
- Steam専用ゲームセッション：セッション側compositorに表示を任せます。MWM専用Gamescopeは起動しません。専用ゲームセッションと実コントローラーでの動作は未確認です。

GNOME拡張の端末操作は `mwm-lite-steam-setup --enable-gnome` です。有効化を確認できないGNOME環境では、Waydroid設定を変更する前に案内して停止します。

起動時のプライマリ画面の論理サイズ・比率を使い、FSRは使用しません。起動中の画面比変更や複数画面への展開は対象外です。ディスプレイを有効にしてから起動してください。

### 設定と入力

`MWM Lite Settings` の保存内容は次回のゲーム起動時に適用します。

- `RTScale`：標準x3、選択x6、復旧用x1。x3がすべての機器や場面で最適という意味ではありません。
- `FPS Counter`：初期OFF。SurfaceFlingerから取得するゲームのFPSだけを表示します。
- `PS5 Boost Mode`：初期OFF。`/dev/icc` と `/dev/mp1` が文字デバイスの場合だけ選択できます。非対応PCでは保存済みONも無効です。デバイスの存在はioctl対応を保証しません。ファン制御を有効にしてシステム全体のBoostを変更し、ONで起動した場合は終了時にOFFを要求します。ファン制御は終了後も有効です。状態取得APIがないため起動前のBoost状態は復元できません。

Steamのコントローラーレイアウトは利用する実機に合わせて選択してください。自動で既存レイアウトを書き換えません。ゲーム用は右スティック／パッド→マウス、トリガー等→左クリックを基本に、Waydroidのタッチ偽装へ渡します。Settings用は上下→上下キー、左右→左右キー、A→Enter、B→Escapeとします。

Settingsでは上下で項目移動、左右でRTScale変更、Enterで選択／切替／保存、Escapeで保存せず終了します。コントローラーから生成されたキーの経路は実機未確認ですが、同じキーイベントによる画面操作はテストしています。

### 終了・分離・復旧

Desktop MWM / Waydroidを停止してからLiteを起動します。Desktopと操作・設定ロックを共有し、同時使用を防ぎます。Liteの設定は `~/.config/mwm-lite/settings.json` に分離し、Desktop設定ファイルには書き込みません。共有Waydroidプロパティと元のAndroid RTScaleファイルは退避して終了時に復元します。Lite設定はDesktopの設定バックアップ対象外です。

終了はSteamライブラリのゲーム詳細の `Exit game` を使用します。CachyOS / Plasmaでは両エントリ起動、ゲームタイトル、マウスのタッチ偽装、FPS表示、実際のExit gameからの復元を確認しています。PlasmaでのShift+Tabによるゲーム内Steam overlayは表示を確認できていません。Guideボタン、Steam Input実コントローラー操作、PS5実機、GNOME全画面は別途検証が必要です。

ゲームと復元処理は `mwm-lite-session` ユーザーサービスが担当します。Steamが追跡するランチャーを強制終了しても、サービスが存続していれば終了を検出して復元します。復元後はWaydroidが停止します。サービス本体のSIGKILL・電源断で復旧情報が残る場合は次を実行します。

```bash
mwm-lite --recover
```

`~/.local/state/mwm-lite/restore.json` は手で削除しないでください。復旧待ちの間はDesktop起動操作・更新・アンインストールを停止します。起動エラーは同じ保存先の `errors.log`、セッション出力は `session.log` に記録します。XDGの指定がある場合はそれに従います。

## デュアルモニター表示

Homeの Display Mode → Dual Display で、ゲームを2台のモニターにまたがって表示します。起動時から枠なしウィンドウが2画面へ広がるため、手動のウィンドウ切り替えは不要です。調整項目は Span Display にあります。

| 項目 | 操作・動作 |
| --- | --- |
| Match Display Size | モニター情報をもとにOSの表示倍率を調整し、見た目のサイズを近づけて下揃えにします。 |
| Undo | サイズ合わせ前のOS設定へ戻します。 |
| Bezel Compensation | ベゼルに隠れる部分を補正します。 |
| Combined bezel width | 境目にある左右のベゼル幅の合計をmmで入力します。合計17.5mmなら `17.5` を指定します。 |
| F12スクリーンショット | ベゼル補正中も、補正前の全体画像をPNGで保存します。保存先は通常 `Pictures/MWM` です。 |

ベゼル補正は Apply で保存し、次回起動時に適用します。実物の設置位置やベゼル幅は自動取得できません。モニターの寸法を取得できない場合や、縦置き・上下配置の場合は、OS側で調整してください。

### 注意点

- サイズ合わせはOS全体に反映されます。ゲーム以外のアプリの表示サイズや配置も変わります。
- 2画面表示ではウィンドウ状態で使用してください。通常のフルスクリーンに切り替えると、1画面のみの表示になります。
- FSRを有効にすると、ちらつきや画面の乱れが発生する場合があります。症状が出る場合はFSRをオフにしてください。
- ベゼル補正中のAlt+Tabで、GPUリセットが発生した事例があります。ゲームや他のアプリも終了する場合があります。原因は調査中です。
- 3画面以上の構成は未検証です。現時点では2画面構成で動作を確認しています。

## Options

| 項目 | 内容 |
| --- | --- |
| Verify Waydroid Startup | Android起動・設定反映・解像度・表示の継続を確認します。OFFでは必須設定の反映後、表示確認と安定待機を省略します。 |
| Auto Launch Mirishita | 準備確認後にミリシタを自動起動します。Verify OFFではグレーアウトし、手動起動になります。 |
| F12 Screenshot | ゲーム窓にフォーカスがあるとき、F12でOSの画像フォルダ内MWMへPNGだけを保存します。 |
| Mouse as Touch | マウス操作をAndroidのタッチ入力として扱います。 |
| RTScale Zoom Fix | RTScale使用時の過度な拡大や、光の合成などに生じる描画ずれを補正します。通常はONで使用してください。 |

Verify ONの場合、ミリシタの起動処理中はMWMの操作を制限します。途中でミリシタを手動起動すると処理を中断するため、ゲームを終了してStart／Restartをやり直してください。

### PS5 Linux Boost Mode

メイン画面下部のチェックでPS5本体のBoost Modeを即時にON／OFFします。ApplyやRestartは不要です。PS5の専用デバイスがない環境では操作できません。

ONではファン制御を有効にしてからCPU・GPUのBoostを有効にします。OFFではCPU・GPUのBoostを解除し、冷却用のファン制御は有効のまま維持します。ファン制御に失敗した場合はBoostの切り替えを中止します。

起動時は「状態不明」と表示します。ON／OFF表示は今回のMWMで最後に成功した操作を示し、外部ツールによる変更は追跡しません。設定はシステム全体に適用され、MWM終了時にも維持されます。ONでは消費電力や発熱が増える場合があります。

## FPS Counter

Off／Minimal／Detailed／MangoAppから選択します。MinimalとDetailedはMWM HUD、MangoAppはGamescope内のカウンターです。

| 数値 | 計測対象 |
| --- | --- |
| FPS：全方式 | SurfaceFlingerのミリシタ描画レイヤーの実表示時刻から計算する、Android側の表示更新頻度。MangoAppもMWM HUDと同じ値を表示します。 |
| Frametime：Detailed | Android側の直近の有効なフレーム間隔。 |
| グラフ：MangoApp | Gamescope側のフレーム時間です。Android側のFPS表示とは計測対象が異なるため、一定の時間差（ms）には換算できません。 |
| CPU／GPU | ホスト側の負荷。ミリシタ単体の使用率ではありません。 |

FPS Counterの表示方式はミリシタ起動中でも変更でき、Applyを押すと即時に切り替わります。

### BC250のGPU使用率（試験機能）

BC250でGPU使用率を正常に取得できない場合に使用する試験機能です。GPUの状態レジスター（GRBM_STATUS）の稼働フラグを一定間隔で読み取り、稼働していた割合からGPU全体の活動率を推定します。

手動で有効にする場合は次を実行し、HUDを起動し直してください。無効にする場合は同じファイルを削除します。

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/mwm"
touch "${XDG_CONFIG_HOME:-$HOME/.config}/mwm/bc250-gpu-test"
```

## 既知の不具合・未検証事項

- **確認済み**：PS5でMSAA x2を使用した際に、画面のちらつきが発生することがあります。
- **確認済み**：ガシャおよびイベント開始の一枚絵が異常に拡大される現象を目視確認しています。
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

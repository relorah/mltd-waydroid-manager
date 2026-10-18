# RTScale 分割描画の修正（v0.91）

MWM独立実装に対するローカル修正です

通常の720px高に加え、その半分の360px高の描画先と対応するScreenParamsを同じ倍率で拡大します。基準幅の上限、形式フィルター、OFF/x1、MSAAの既定方針は維持します。TexelSizeはその設定を有効にした場合だけ変換します。

一旦愛して♡の3D標準では1280×360／640×360と720px高のターゲットを実測しました。分割カットと4人並びを検証用ビルドで確認し、分割カットで修正前の粗い輪郭が改善しました。READMEの実画像はこの検証時の録画から切り出しています。画像加工による補正ではありません。

## ソースと再ビルド

`packaging/source-build.md`（対応ソース配布ではルートのBUILD.md）の順序に従って、既存の統合済みgraphics-sources.tar.zstへMSAA、depth-blit、本パッチを適用します。統合スクリプトの再実行は不要です。

本パッチはMesaソースルートで `patch -p1` により適用します。既存のAndroid API30 / NDK r27c / LLVM21、ABIチェックON、11ドライバの通常ビルド設定を維持しています。検証用の計測コードやCopyImage試作は含みません。

ステージ時にビルド用RPATH/RUNPATHを除去し、`packaging/anonymize-build-paths.py` で診断文字列を正規化してからハッシュを計算します。

```
v0.90 通常ビルド・未変更再ビルド:
f34d06ed52a6576dd1f558fc0c01b503f960e5933acf5be83e1e42611548a773
v0.91 半分の高さへの対応・通常ビルド:
650ec1b6e0cb3ba6491cb3a509c2480e27e8a15c7f03994423176f4123042635
```

v0.91の `packaging/payload/graphics/mesa-rtscale-overlay.tar.zst` は新しいGalliumライブラリを含みます。EGL/GLESラッパーはv0.90と同一です。既存v0.90の公開Release資産は置き換えません。

## 検証

`packaging/tests/graphics/half-height/` に独立したCテストとAndroid GLESプローブを収録しています。

- ホストCテスト：1,368件通過。OFF/x1〜x8、基準幅960/1280/1680/2560、通常／半分の高さ、対象10形式、対象外高さ／形式／幅、ScreenParams、TexelSize有効／無効を確認。
- 通常ビルドの新ライブラリをロードするAndroid GLESプローブ：RX 9060 XTで12件通過。x1/x3/x6、Texture/Renderbuffer、単一サンプル／MSAA4、深度／ステンシルのコピー、物理領域の左右端のピクセルを確認。ログは `device-results.json` に収録。
- 実ゲームの4分割カットと4人並びは、同じ修正を適用した先行の検証用ビルドで確認済み。今回の通常ビルドによるMV再生、他楽曲・他GPU・全倍率の実ゲーム回帰検証は未完了です。

ホストテストはリポジトリルートから、修正済みMesaソースを指定します。

```bash
cc -Wall -Wextra -Werror -I /path/to/mesa/src/mesa/main packaging/tests/graphics/half-height/test-halfheight.c /path/to/mesa/src/mesa/main/gles_rtscale.c -o test-halfheight
./test-halfheight
```

AndroidプローブはAPI30用NDKコンパイラと、対応ステージのEGL/GLESv2でコンパイルします。GLESv2はGLES3.2を公開します。ゲームデータの外で、専用プロセス名だけに一致するRTScale設定をバックアップ付きで使用してください。引数は `scale source_rb destination_rb mask_bits expected_samples requested_samples` です。今回の半分の高さのプローブは1280×360を基準とし、RTScale設定の基準自体は1280×720のままです。CLI終了コードだけでなく、Android内の終了値と `PASS`、ピクセル値を確認します。

パッチ対象の独立実装とテストは0BSDです。Mesa全体のライセンスや第三者ライセンスを置き換えるものではありません。

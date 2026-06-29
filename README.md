# KeyCounter

キーボードとマウスの押下回数・押下時間を可視化する Windows 常駐アプリです。

## ダウンロード

一般ユーザー向けの説明・最新版ダウンロードはこちらです。

https://bunjicompany.com/downloads/KeyCounter/

過去バージョン・更新履歴はこちらです。

https://github.com/bunjicompany/keycounter/releases

## 安心して使うために

KeyCounterはキーロガーではありません。
入力した文章・パスワード・クリップボードの内容を保存しません。
保存するのは、キーやマウスボタンごとの押下回数・押下時間のみです。
外部サーバーへの送信は行いません。

個人開発アプリのため、Windows SmartScreenの警告が表示される場合があります。

![KeyCounter screenshot](assets/screenshot.png)

## 特徴

- キー別の押下回数をランキングと棒グラフで表示
- 日本語配列キーボード風のヒートマップ表示
- マウスの左クリック、右クリック、ホイールクリック、戻る・進むボタンを集計
- 押下時間の合計・平均・最大値を記録
- 集計開始、最終記録、記録稼働時間、1時間あたりの操作ペースを表示
- 統計画面を画像として保存
- タスクトレイに常駐し、一時停止、手動保存、リセット、起動時実行を操作可能

## 保存するデータ

保存するもの:

- キー/マウスボタンの識別子
- 押下回数
- 合計押下時間
- 最大押下時間
- 初回記録日時・最終記録日時
- 記録稼働時間

保存しないもの:

- 入力文字列
- パスワード
- クリップボード内容
- 押下順序・時系列ログ
- マウス座標

アプリ版の統計は `%LOCALAPPDATA%\KeyCounter\keys_stats.json` に保存されます。

## 記録データを削除したいとき

記録データをリセットしたい場合は、アプリ内のリセット機能を使用してください。

手動で削除する場合は、アプリを終了したあと、以下のファイルを削除してください。

`%LOCALAPPDATA%\KeyCounter\keys_stats.json`

次回起動時に、新しい記録ファイルが作成されます。

## うまく記録されないとき

- アプリが一時停止になっていないか確認してください。
- タスクトレイにKeyCounterのアイコンが表示されているか確認してください。
- 管理者権限で起動しているアプリ上の操作は、通常権限のKeyCounterでは記録できない場合があります。
- 記録が反映されない場合は、今すぐ保存またはアプリの再起動を試してください。

## 開発環境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 実行

開発中に直接起動する場合:

```powershell
.\.venv\Scripts\python.exe keycounter_app.py
```

記録ロジックだけをコンソールで動かす場合:

```powershell
.\.venv\Scripts\python.exe key_tracker.py
```

## ビルド

```powershell
.\build_keycounter.ps1
```

ビルドすると、以下が作成されます。

- `release-package\yyyyMMdd-HHmmss\KeyCounter\KeyCounter.exe`
- `dist\KeyCounter.zip`

## ライセンス

MIT License

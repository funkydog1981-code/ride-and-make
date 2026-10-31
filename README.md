# 走って、つくって。 Netlify移行用プロジェクト

2026年10月25日時点のサイトの書き出しです。HTML・インラインCSS・インラインJavaScript・画像・動画を元データのまま含みます。

## Netlifyへの公開

1. ZIPを解凍します。
2. Netlifyの手動デプロイ画面に、`public`フォルダをドラッグ＆ドロップします。
3. 発行されたURLでトップページ、別府の旅の記録、お問い合わせを確認します。

Git連携の場合は、このプロジェクト全体をリポジトリに入れてください。`netlify.toml`で公開フォルダを`public`に指定済みです。ビルドコマンドやパッケージのインストールは不要です。

## 構成

- `public/index.html`：トップページ（CSS・JavaScript内蔵）
- `public/journeys/beppu/index.html`：別府の旅の記録（CSS内蔵）
- `public/contact/index.html`：お問い合わせ（CSS内蔵）
- `public/assets/`：画像・動画
- `netlify.toml`：Netlify設定
- `SHA256SUMS.json`：元ファイルとの一致確認用

CSSとJavaScriptは元サイトと同じくHTMLに含まれています。外部ファイルへの分離やデザイン・機能の変更は行っていません。

## 外部サービス

お問い合わせは既存のTallyフォーム（https://tally.so/r/RWGEgd）をそのまま開きます。通知設定は既存のTally側で継続管理してください。Stravaの埋め込みは従来どおりStrava側のスクリプトと公開設定・サービス提供状況に依存します。これらの外部サービス自体はZIPに含まれません。

## ローカル確認

プロジェクトのフォルダで `python -m http.server 8000 --directory public` を実行し、http://localhost:8000/ を開きます。HTMLを直接ダブルクリックすると、ルート相対リンクは正常に動作しない場合があります。

## 元サイト

https://ride-and-make-notes.duskyhill16384.chatgpt.site/

元サイトの公開・設定・ソースには変更を加えていません。このZIPの公開先とは別に維持されます。元サイトのソースコミット：23e9021b90b561ff23593e84b72820eb82082a94。

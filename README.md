# 走って、つくって。CMS対応版

## 含まれるもの
- 現在のデザイン・画像・動画を維持したサイト
- `/admin/` のDecap CMS管理画面
- `public/content/site.json` でトップページ、道具とものづくり、愛車と装備、このサイトについて、旅の記録を管理
- GitHub `funkydog1981-code/ride-and-make` の `main` ブランチとNetlifyの自動デプロイ

## Netlify公開
Netlifyの公開ディレクトリは `public`。ビルドコマンドは不要です。`netlify.toml` は `/journeys/:slug/` を汎用記事テンプレートへリライトします。

## CMSログインの初期設定（GitHub OAuth）
1. GitHubでOAuth Appを作成し、Authorization callback URLを `https://api.netlify.com/auth/done` に設定します。
2. Netlifyの対象サイトでProject configuration内のAccess / OAuth provider設定を開き、GitHub Client IDとClient Secretを登録して有効化します。名称はNetlifyのUIにより多少異なる場合があります。
3. `/admin/` にアクセスし、GitHubアカウントでログインします。リポジトリへの書き込み権限が必要です。
4. CMS設定は `public/admin/config.yml`。リポジトリは `funkydog1981-code/ride-and-make`、ブランチは `main` です。

## コンテンツ
管理画面は `public/content/site.json` を編集します。画像はCMSから `public/assets/uploads/` に保存されます。記事本文はMarkdown対応です。既存の別府記事は元の動画・表・写真の配置を保持するためHTMLを一部含んでおり、本文を編集する際はHTMLタグを誤って削除しないよう注意してください。

## 注意
このCMS対応版はテストサイトに先に反映してください。管理画面のOAuth設定が完了するまで `/admin/` のログインは利用できません。

# Sales Report App - 営業報告アプリ

音声またはテキストで営業活動を報告し、Gemini AIでデータ抽出してKintoneに自動登録するStreamlitアプリケーションです。

## 機能

- 🎤 **音声入力**: MP3, WAV, M4A形式の音声ファイルをアップロード
- 📝 **テキスト入力**: メモやテキストでの報告入力
- 🤖 **AI処理**: Gemini AIで構造化データに自動変換
- 📤 **Kintone連携**: 抽出データをKintoneに自動登録

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example`をコピーして`.env`を作成し、実際の値を設定:

```bash
cp .env.example .env
```

### 3. アプリの起動

```bash
streamlit run app.py
```

## Kintoneフィールドマッピング

`app.py`の`upload_to_kintone`関数内のフィールドコードを、お使いのKintoneアプリに合わせて変更してください:

| JSONフィールド | Kintoneフィールドコード（デフォルト） |
|---------------|-------------------------------------|
| date | 日付 |
| customer_name | 顧客名 |
| activity_detail | 活動内容 |
| next_action | 次回アクション |

## 使い方

1. 音声ファイルをアップロード、またはテキストメモを入力
2. 「送信・処理開始」ボタンをクリック
3. AIが自動的にデータを抽出・構造化
4. 内容を確認し、「Kintoneに登録する」で保存

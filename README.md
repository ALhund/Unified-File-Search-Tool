# Unified File Search Tool

ファイル内のテキストを横断的に検索するデスクトップアプリケーション。

## 対応形式

- Office: `.docx`, `.xlsx`, `.pptx`
- PDF: `.pdf`
- テキスト: `.txt`, `.md`, `.log`

## 必要要件

- Python 3.11以上
- [uv](https://github.com/astral-sh/uv) (パッケージマネージャ)

## インストール

### uvのインストール

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Linux/Mac:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### アプリケーションの起動

**Windows:**
```batch
run.bat
```

**Linux/Mac:**
```bash
chmod +x run.sh
./run.sh
```

初回起動時は自動的に仮想環境の作成と依存関係のインストールが行われます。

## 使い方

1. **検索対象フォルダ**: 「参照...」ボタンで検索したいフォルダを選択
2. **検索語**: 検索キーワードを入力（正規表現も使用可能）
3. **除外語**: 除外したいキーワードをカンマ区切りで入力（オプション）
4. **対象拡張子**: 検索対象の拡張子を選択
5. **検索ボタン**: クリックして検索を実行

### 正規表現オプション

- **大文字小文字を無視**: チェックすると大文字小文字を区別しない
- **複数行モード**: `^` と `$` が各行の先頭/末尾にマッチ
- **ドットが改行にもマッチ**: `.` が改行文字にもマッチ

### 挿入ボタン

よく使う正規表現パターンをワンクリックで挿入できます:

- `.*` - 任意の文字列
- `\s*` - 0個以上の空白
- `\d+` - 1個以上の数字
- `^` - 行頭
- `$` - 行末
- `|` - または
- `(...)` - キャプチャグループ
- `(?:...)` - 非キャプチャグループ

## プロジェクト構造

```
Unified-File-Search-Tool/
├── src/
│   ├── common/         # 共通モジュール
│   ├── enumeration/    # ファイル列挙
│   ├── extraction/     # テキスト抽出
│   ├── search/         # 検索エンジン
│   ├── metadata/       # メタデータ取得
│   ├── preview/        # プレビューレンダラー
│   └── ui/             # UIコンポーネント
├── Config/
│   └── config.xml      # 設定ファイル
├── logs/               # ログディレクトリ
├── main.py             # エントリーポイント
├── pyproject.toml      # プロジェクト定義
├── run.bat             # Windows起動バッチ
└── run.sh              # Linux/Mac起動スクリプト
```

## 設定

`Config/config.xml` で以下の設定が可能です:

- `large_file_threshold_mb`: 大容量ファイル警告の閾値（デフォルト: 20MB）
- `max_matches`: 検索結果の最大件数（デフォルト: 50）
- `max_log_lines`: ログファイルの最大行数（デフォルト: 1000）
- `target_extensions`: 検索対象の拡張子

## ログ

ログは `logs/` ディレクトリにJSONL形式で保存されます。機能別にファイルが分かれています:

- `search.jsonl` - 検索操作
- `extraction.jsonl` - テキスト抽出
- `ui.jsonl` - UI操作
- `error.jsonl` - エラー

## ライセンス

MIT License

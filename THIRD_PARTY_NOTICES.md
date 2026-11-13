# 第三者ソフトウェアのライセンス

Unified File Search は、以下のオープンソース ソフトウェアを利用しています。
各ソフトウェアの著作権は、それぞれの著作権者に帰属します。

配布用のパッケージを作るときは、`tools/collect_licenses.py` を実行して
各ソフトウェアのライセンス全文を `licenses/` フォルダに集め、配布物に同梱してください
（MIT / BSD / Apache などのライセンスは、配布物への著作権表示とライセンス文の同梱を求めています）。

## アプリに組み込まれるもの

| ソフトウェア | 用途 | ライセンス |
| --- | --- | --- |
| [Qt for Python (PySide6 / shiboken6)](https://www.qt.io/qt-for-python) | 画面（Qt Widgets, Qt WebEngine, Qt Svg） | LGPL-3.0 |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | PDFの表示・文字位置の取得 | Apache-2.0 / BSD-3-Clause |
| [PDFium](https://pdfium.googlesource.com/pdfium/)（pypdfium2 に同梱） | PDFエンジン | BSD-3-Clause / Apache-2.0（同梱ライブラリ: FreeType は FTL を選択、libjpeg-turbo, OpenJPEG, LittleCMS, zlib, ICU など。詳細は pypdfium2 の `BUILD_LICENSES`） |
| [python-docx](https://github.com/python-openxml/python-docx) | Word ファイルの読み取り | MIT |
| [python-pptx](https://github.com/scanny/python-pptx) | PowerPoint ファイルの読み取り | MIT |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) / et_xmlfile | Excel ファイルの読み取り | MIT |
| [lxml](https://lxml.de/) | XML の解析 | BSD-3-Clause |
| [XlsxWriter](https://github.com/jmcnamara/XlsxWriter)（python-pptx が使用） | — | BSD-2-Clause |
| [Pillow](https://python-pillow.org/) | 画像の変換 | MIT-CMU（HPND） |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | 文字コードの判別 | MIT |
| [typing_extensions](https://github.com/python/typing_extensions) | — | PSF-2.0 |
| [pywin32](https://github.com/mhammond/pywin32)（Windows のみ） | Microsoft Office との連携 | PSF-2.0 |
| [Python](https://www.python.org/)（配布用パッケージに同梱する場合） | 実行環境 | PSF-2.0 |

## アプリに組み込まないもの

| ソフトウェア | 扱い |
| --- | --- |
| Microsoft Office | 利用者のパソコンにインストールされているものを呼び出すだけで、同梱しません |
| [LibreOffice](https://www.libreoffice.org/) | 同上（MPL-2.0）。利用者が各自でインストールします |
| Windows のフォント（Segoe UI, Yu Gothic UI など） | OS のものを使い、同梱しません |

アイコン（`assets/`、`src/ui/icons.py`）はすべて本アプリのために作成したものです。

## LGPL（Qt for Python）について

Qt for Python は LGPL-3.0 で提供されています。配布にあたっては次を守ってください。

- Qt のライブラリは改変せず、**差し替え可能な形（DLL のまま）で同梱する**。
  PyInstaller なら `--onedir`（フォルダ形式）で作り、`--onefile`（1ファイル形式）は使わない
- LGPL-3.0 の全文と、Qt のソースコードの入手先（https://download.qt.io/ ）を案内する
- 利用規約で、Qt 部分の解析・差し替えを禁止しない

また、Qt のうち **Qt Charts / Qt Data Visualization / Qt Graphs などは LGPL ではなく GPL か商用ライセンス**です。
本アプリはこれらを使っていないので、配布用パッケージに含めないでください
（`PySide6-Addons` に入っていますが、PyInstaller では本アプリが読み込むモジュールだけが同梱されます）。

## 使用をやめたもの

| ソフトウェア | 理由 |
| --- | --- |
| PyMuPDF / MuPDF | AGPL-3.0（または有償の商用ライセンス）のため。販売するアプリに組み込むと、アプリ全体のソースコード公開が必要になる。pypdfium2 に置き換えた |
| chardet（5.x 以前） | LGPL-2.1 のため。charset-normalizer（MIT）に置き換えた |
| pypdf | 使用していないため依存から削除した |

"""ダイアログ（設定・ショートカット・バージョン情報）"""

import shutil

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.common.config import get_config
from src.common.utils import format_file_size
from src.preview.converter import available_backends, find_libreoffice, has_msoffice_support
from src.ui import icons
from src.ui.settings import MATCH_LIMIT_CHOICES, UserSettings, limit_label
from src.ui.widgets.common import label, primary_button

from src import __version__ as APP_VERSION


def _icon_label(name: str, size: int = 20) -> QLabel:
    from src.ui.theme import palette
    widget = QLabel()
    widget.setPixmap(icons.pixmap(name, palette().accent_fg, size))
    widget.setFixedSize(size + 4, size + 4)
    return widget


class _Group(QFrame):
    """設定のまとまり（見出しつきのカード）"""
    
    def __init__(self, icon_name: str, title: str):
        super().__init__()
        self.setObjectName("SettingsGroup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 14)
        self._layout.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_icon_label(icon_name))
        head.addWidget(label(title, "SectionTitle"))
        head.addStretch(1)
        self._layout.addLayout(head)
    
    def add_row(self, title: str, description: str, control: QWidget) -> None:
        row = QHBoxLayout()
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label(title, "SettingsRowTitle"))
        if description:
            texts.addWidget(label(description, "Secondary", wrap=True))
        row.addLayout(texts, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self._layout.addLayout(row)
    
    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


def _cache_size() -> int:
    path = get_config().cache_path
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and "lo_profile" not in item.parts:
                total += item.stat().st_size
        except OSError:
            pass
    return total


class SettingsDialog(QDialog):
    """設定画面"""
    
    def __init__(self, settings: UserSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("設定")
        self.setMinimumSize(620, 640)
        self.cache_cleared = False
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(14)
        layout.addWidget(label("設定", "DialogTitle"))
        
        config = get_config()
        
        # 外観
        appearance = _Group("palette", "外観")
        self._theme_combo = QComboBox()
        for value, text in (("system", "Windows の設定に合わせる"), ("light", "ライト"), ("dark", "ダーク")):
            self._theme_combo.addItem(text, value)
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(settings.theme)))
        appearance.add_row("テーマ", "画面の明るさ", self._theme_combo)
        self._accent_check = QCheckBox("使う")
        self._accent_check.setChecked(settings.use_system_accent)
        appearance.add_row("Windows のアクセント カラー", "ボタンや選択の色を Windows の設定に合わせます", self._accent_check)
        layout.addWidget(appearance)
        
        # 検索
        search = _Group("search", "検索")
        self._limit_combo = QComboBox()
        for value in MATCH_LIMIT_CHOICES:
            self._limit_combo.addItem(limit_label(value), value)
        current_limit = config.search_max_matches_per_file
        index = self._limit_combo.findData(current_limit)
        if index < 0:
            self._limit_combo.addItem(limit_label(current_limit), current_limit)
            index = self._limit_combo.count() - 1
        self._limit_combo.setCurrentIndex(index)
        search.add_row(
            "1ファイルあたりの上限",
            "これを超えたファイルは「50+」のように表示します。「無制限」はすべて数えます",
            self._limit_combo,
        )
        from src.search import logical_processors
        cpus = logical_processors()
        self._workers_combo = QComboBox()
        self._workers_combo.addItem(f"自動（{max(1, cpus - 1)} 並列・おすすめ）", 0)
        for n in sorted({1, 2, 4, 8, 12, 16, 24, 32, cpus} - {0}):
            if n <= max(32, cpus):
                self._workers_combo.addItem(f"{n} 並列", n)
        self._workers_combo.setCurrentIndex(max(0, self._workers_combo.findData(config.search_workers)))
        search.add_row(
            "同時に処理する数",
            f"このパソコンの論理プロセッサは {cpus} 個です（ハイパースレッディングで増えた分を含む）。"
            "自動では、画面の操作用に1つ残してすべてを検索に使います",
            self._workers_combo,
        )
        layout.addWidget(search)
        
        # 常時インデックス
        index = _Group("database", "常時インデックス")
        self._index_check = QCheckBox("使う")
        self._index_check.setChecked(settings.index_enabled)
        index.add_row(
            "インデックスを常に最新に保つ",
            "下のフォルダを裏で定期的に読み込み、検索を一瞬で終わらせます",
            self._index_check,
        )
        self._index_list = QListWidget()
        self._index_list.setMinimumHeight(72)
        self._index_list.setMaximumHeight(120)
        self._index_list.addItems(settings.index_folders)
        index.add_widget(self._index_list)
        folder_row = QHBoxLayout()
        add_folder = QPushButton("フォルダを追加…")
        add_folder.clicked.connect(self._add_index_folder)
        remove_folder = QPushButton("選んだフォルダを外す")
        remove_folder.clicked.connect(lambda: [self._index_list.takeItem(self._index_list.row(i)) for i in self._index_list.selectedItems()])
        folder_row.addWidget(add_folder)
        folder_row.addWidget(remove_folder)
        folder_row.addStretch(1)
        holder = QWidget()
        holder.setLayout(folder_row)
        folder_row.setContentsMargins(0, 0, 0, 0)
        index.add_widget(holder)
        self._auto_add_check = QCheckBox("加える")
        self._auto_add_check.setChecked(settings.index_auto_add)
        index.add_row("検索したフォルダを自動で加える", "最大 10 フォルダまで", self._auto_add_check)
        self._interval_combo = QComboBox()
        for minutes in (5, 15, 30, 60, 180):
            self._interval_combo.addItem(f"{minutes} 分ごと" if minutes < 60 else f"{minutes // 60} 時間ごと", minutes)
        self._interval_combo.setCurrentIndex(max(0, self._interval_combo.findData(settings.index_interval_min)))
        index.add_row("更新の間隔", "変更のあったファイルだけを読み込み直します", self._interval_combo)
        self._tray_check = QCheckBox("常駐する")
        self._tray_check.setChecked(settings.tray_on_close)
        index.add_row("閉じてもタスクトレイに常駐", "ウィンドウを閉じても、インデックスの更新を続けます", self._tray_check)
        from src.ui.platform import autostart_supported, is_autostart_enabled
        self._autostart_check = QCheckBox("起動する")
        self._autostart_check.setChecked(is_autostart_enabled())
        self._autostart_check.setEnabled(autostart_supported())
        index.add_row(
            "Windows のサインイン時に起動",
            "タスクトレイに常駐した状態で起動し、パソコンを使い始めた時点から最新に保ちます",
            self._autostart_check,
        )
        self.index_update_requested = False
        update_now = QPushButton("今すぐ更新")
        icons.bind(update_now, "database", "text", 16)
        update_now.clicked.connect(self._request_index_update)
        index.add_row("インデックスの更新", "", update_now)
        layout.addWidget(index)
        
        # プレビュー
        preview = _Group("page", "プレビュー（原本表示）")
        self._converter_combo = QComboBox()
        for value, text in (
            ("auto", "自動（Microsoft Office → LibreOffice）"),
            ("msoffice", "Microsoft Office"),
            ("libreoffice", "LibreOffice"),
            ("none", "使わない（常にテキスト表示）"),
        ):
            self._converter_combo.addItem(text, value)
        self._converter_combo.setCurrentIndex(max(0, self._converter_combo.findData(config.office_converter)))
        preview.add_row(
            "Office ファイルの変換",
            "Excel・Word・PowerPoint を、開いたときと同じ見た目で表示するために使います",
            self._converter_combo,
        )
        
        lo_row = QWidget()
        lo_layout = QHBoxLayout(lo_row)
        lo_layout.setContentsMargins(0, 0, 0, 0)
        self._lo_edit = QLineEdit(config.libreoffice_path)
        self._lo_edit.setPlaceholderText("自動で検出（soffice.exe の場所）")
        self._lo_edit.setMinimumWidth(240)
        lo_layout.addWidget(self._lo_edit)
        browse = QPushButton("参照…")
        browse.clicked.connect(self._browse_libreoffice)
        lo_layout.addWidget(browse)
        preview.add_row("LibreOffice の場所", "", lo_row)
        
        status = []
        status.append(("Microsoft Office", has_msoffice_support()))
        status.append(("LibreOffice", find_libreoffice() is not None))
        status_text = "　".join(f"{'✔' if ok else '—'} {name}" for name, ok in status)
        preview.add_widget(label(f"検出状況:　{status_text}", "Secondary"))
        layout.addWidget(preview)
        
        # キャッシュ
        cache = _Group("database", "キャッシュ")
        self._cache_label = label("", "Secondary")
        clear = QPushButton("消去")
        clear.setObjectName("Danger")
        icons.bind(clear, "trash", "danger", 16)
        clear.clicked.connect(self._clear_cache)
        cache.add_row(
            "インデックス・変換結果",
            "検索を速くするための索引と、原本表示用の変換結果です。消去すると次の検索で作り直します",
            clear,
        )
        cache.add_widget(self._cache_label)
        history = QPushButton("消去")
        history.clicked.connect(self._clear_history)
        cache.add_row("検索語とフォルダの履歴", "", history)
        layout.addWidget(cache)
        self._update_cache_label()
        
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        
        buttons = QHBoxLayout()
        buttons.setContentsMargins(24, 10, 24, 18)
        buttons.addStretch(1)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        ok = primary_button("保存")
        ok.clicked.connect(self._save)
        ok.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        outer.addLayout(buttons)
    
    def _add_index_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "常にインデックスするフォルダ")
        if folder:
            existing = [self._index_list.item(i).text() for i in range(self._index_list.count())]
            if folder not in existing:
                self._index_list.addItem(folder)
    
    def _request_index_update(self) -> None:
        self.index_update_requested = True
        QMessageBox.information(self, "インデックス", "設定を保存したあと、インデックスの更新を始めます。")
    
    def _browse_libreoffice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "soffice の場所", "", "soffice (soffice*);;すべてのファイル (*)")
        if path:
            self._lo_edit.setText(path)
    
    def _update_cache_label(self) -> None:
        self._cache_label.setText(f"現在の使用量: {format_file_size(_cache_size())}（{get_config().cache_path}）")
    
    def _clear_cache(self) -> None:
        from src.extraction.cache import get_extraction_cache
        
        cache = get_extraction_cache()
        if cache is not None:
            cache.clear()
        preview_dir = get_config().cache_path / "preview"
        shutil.rmtree(preview_dir, ignore_errors=True)
        self.cache_cleared = True
        self._update_cache_label()
    
    def _clear_history(self) -> None:
        self._settings.clear_history()
        QMessageBox.information(self, "設定", "履歴を消去しました。")
    
    def _save(self) -> None:
        s = self._settings
        s.theme = self._theme_combo.currentData()
        s.use_system_accent = self._accent_check.isChecked()
        if self._limit_combo.currentData() != get_config().search_max_matches_per_file:
            s.match_limit = self._limit_combo.currentData()
        s.workers = self._workers_combo.currentData()
        s.index_enabled = self._index_check.isChecked()
        s.index_folders = [self._index_list.item(i).text() for i in range(self._index_list.count())]
        s.index_auto_add = self._auto_add_check.isChecked()
        s.index_interval_min = self._interval_combo.currentData()
        s.tray_on_close = self._tray_check.isChecked()
        from src.ui.platform import autostart_supported, set_autostart
        if autostart_supported():
            set_autostart(self._autostart_check.isChecked())
        s.converter = self._converter_combo.currentData()
        s.libreoffice_path = self._lo_edit.text().strip()
        s.sync()
        self.accept()


SHORTCUTS = [
    ("検索", [
        ("Enter", "検索する"),
        ("Esc", "検索を中断する"),
        ("Ctrl + F / Ctrl + L", "検索語の入力欄へ"),
        ("Ctrl + O", "フォルダを選ぶ"),
    ]),
    ("結果一覧", [
        ("↑ / ↓", "前後のファイルを表示"),
        ("Enter / ダブルクリック", "アプリで開く"),
        ("Ctrl + E", "エクスプローラーで表示"),
        ("Ctrl + Shift + C", "パスをコピー"),
        ("Ctrl + S", "検索結果を Excel に書き出す"),
    ]),
    ("プレビュー", [
        ("F3 / Shift + F3", "次 / 前のヒットへ"),
        ("Ctrl + 1 / Ctrl + 2", "原本表示 / テキスト表示"),
        ("Ctrl + + / Ctrl + - / Ctrl + 0", "拡大 / 縮小 / 100%"),
        ("Ctrl + ホイール", "拡大・縮小"),
        ("Ctrl + Enter", "アプリで開く"),
    ]),
    ("その他", [
        ("Ctrl + ,", "設定"),
        ("F1", "この一覧"),
    ]),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("キーボード ショートカット")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(label("キーボード ショートカット", "DialogTitle"))
        for section, items in SHORTCUTS:
            group = _Group("keyboard", section)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(6)
            for row, (keys, description) in enumerate(items):
                key_row = QHBoxLayout()
                key_row.setSpacing(4)
                for part in keys.split(" / "):
                    key_label = label(part, "Kbd")
                    key_row.addWidget(key_label)
                key_row.addStretch(1)
                holder = QWidget()
                holder.setLayout(key_row)
                key_row.setContentsMargins(0, 0, 0, 0)
                grid.addWidget(holder, row, 0)
                grid.addWidget(label(description), row, 1)
            grid.setColumnStretch(1, 1)
            wrapper = QWidget()
            wrapper.setLayout(grid)
            group.add_widget(wrapper)
            layout.addWidget(group)
        close = primary_button("閉じる")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)


def _open_third_party_notices() -> None:
    """第三者ライセンスの一覧を開く（配布物では licenses/README.txt、開発時は THIRD_PARTY_NOTICES.md）"""
    from src.common.paths import app_dir, resource_dir
    from src.ui.platform import open_file
    
    for candidate in (
        app_dir() / "licenses" / "README.txt",
        app_dir() / "THIRD_PARTY_NOTICES.md",
        resource_dir() / "THIRD_PARTY_NOTICES.md",
    ):
        if candidate.exists():
            open_file(candidate)
            return


class AboutDialog(QDialog):
    def __init__(self, parent=None, license_state=None):
        super().__init__(parent)
        self.setWindowTitle("バージョン情報")
        self.setFixedWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(QSize(72, 72)))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        title = label("Unified File Search", "DialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        version = label(f"バージョン {APP_VERSION}", "Secondary")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        if license_state is not None:
            licensed = label(license_state.summary(), "")
            licensed.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(licensed)
        backends = available_backends()
        engine = {"msoffice": "Microsoft Office", "libreoffice": "LibreOffice"}.get(
            backends[0] if backends else "", "なし（テキスト表示）"
        )
        description = label(
            "フォルダ内の Excel・Word・PowerPoint・PDF・テキストを横断検索し、"
            "ヒットした箇所をファイルを開いたときと同じ見た目で確認できます。"
            f"<br><br>原本表示の変換: {engine}",
            "Secondary",
            wrap=True,
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)
        notices = QPushButton("第三者ソフトウェアのライセンス")
        notices.setObjectName("Ghost")
        notices.setCursor(Qt.CursorShape.PointingHandCursor)
        notices.clicked.connect(_open_third_party_notices)
        notice_row = QHBoxLayout()
        notice_row.addStretch(1)
        notice_row.addWidget(notices)
        notice_row.addStretch(1)
        layout.addLayout(notice_row)
        close = primary_button("閉じる")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        row.addStretch(1)
        layout.addLayout(row)

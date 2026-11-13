"""結果一覧（画面左）

検索前はフォルダ内のファイル一覧、検索後はヒットしたファイルを、
アイコン・件数・ヒット箇所の抜粋（検索語をマーカー表示）つきのカードで並べる。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QMenu,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.common.utils import format_file_size
from src.enumeration import FileInfo
from src.search import SearchResult
from src.ui import icons
from src.ui.platform import file_manager_name, open_file, reveal_in_explorer
from src.ui.theme import palette, theme, ui_font
from src.ui.widgets.common import EmptyState, card, ghost_button, label

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1

SORT_OPTIONS = [
    ("path", "フォルダ順"),
    ("name", "ファイル名順"),
    ("count", "ヒット数の多い順"),
    ("modified", "更新日の新しい順"),
]


@dataclass
class Entry:
    """一覧の1行"""
    file_info: FileInfo
    result: Optional[SearchResult] = None
    
    @property
    def is_error(self) -> bool:
        return self.result is not None and self.result.error is not None
    
    @property
    def count(self) -> int:
        return self.result.match_count if self.result else 0


class ResultModel(QAbstractListModel):
    """一覧のデータ"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[Entry] = []
        self.root: Optional[Path] = None
        self.searched = False  # 検索結果を表示中か（False ならファイル一覧）
    
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role == ENTRY_ROLE:
            return entry
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.file_info.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry)
        return None
    
    def _tooltip(self, entry: Entry) -> str:
        info = entry.file_info
        lines = [
            str(info.path),
            f"サイズ: {format_file_size(info.size)}　更新: {info.modified_time:%Y/%m/%d %H:%M}",
        ]
        if entry.result and entry.result.error:
            lines.append(f"読み込みエラー: {entry.result.error}")
        elif entry.result and entry.result.matches:
            lines.append(f"{entry.result.match_count}件のヒット" + ("（上限で打ち切り）" if entry.result.truncated else ""))
        return "\n".join(lines)
    
    def relative_folder(self, entry: Entry) -> str:
        folder = entry.file_info.path.parent
        if self.root is not None:
            try:
                relative = folder.relative_to(self.root)
                return "（検索フォルダ直下）" if str(relative) == "." else str(relative)
            except ValueError:
                pass
        return str(folder)
    
    def clear(self, searched: bool) -> None:
        self.beginResetModel()
        self._entries = []
        self.searched = searched
        self.endResetModel()
    
    def set_files(self, files: list[FileInfo], root: Path) -> None:
        self.beginResetModel()
        self.root = root
        self.searched = False
        self._entries = [Entry(f) for f in files]
        self.endResetModel()
    
    def add_result(self, result: SearchResult) -> None:
        row = len(self._entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self._entries.append(Entry(result.file_info, result))
        self.endInsertRows()
    
    def entries(self) -> list[Entry]:
        return self._entries


class ResultProxy(QSortFilterProxyModel):
    """並べ替えと絞り込み"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sort_key = "path"
        self.text_filter = ""
        self.extensions: Optional[set[str]] = None
        self.setDynamicSortFilter(True)
    
    def set_sort_key(self, key: str) -> None:
        self.sort_key = key
        self.invalidate()
        self.sort(0)
    
    def set_text_filter(self, text: str) -> None:
        self.text_filter = text.strip().lower()
        self.invalidateFilter()
    
    def set_extensions(self, extensions: Optional[set[str]]) -> None:
        self.extensions = extensions
        self.invalidateFilter()
    
    def filterAcceptsRow(self, row: int, parent) -> bool:  # noqa: N802
        entry: Entry = self.sourceModel().index(row, 0, parent).data(ENTRY_ROLE)
        if entry is None:
            return False
        if self.extensions is not None and entry.result is None:
            if entry.file_info.extension not in self.extensions:
                return False
        if self.text_filter:
            haystack = str(entry.file_info.path).lower()
            if entry.result and entry.result.matches:
                haystack += " " + entry.result.matches[0].snippet.lower()
            return all(part in haystack for part in self.text_filter.split())
        return True
    
    def lessThan(self, left, right) -> bool:  # noqa: N802
        a: Entry = left.data(ENTRY_ROLE)
        b: Entry = right.data(ENTRY_ROLE)
        if self.sort_key == "name":
            return (a.file_info.name.lower(), str(a.file_info.path)) < (b.file_info.name.lower(), str(b.file_info.path))
        if self.sort_key == "count":
            return (-a.count, str(a.file_info.path).lower()) < (-b.count, str(b.file_info.path).lower())
        if self.sort_key == "modified":
            return a.file_info.mtime_ns > b.file_info.mtime_ns
        return str(a.file_info.path).lower() < str(b.file_info.path).lower()


class ResultDelegate(QStyledItemDelegate):
    """1行（カード）の描画"""
    
    PAD_X = 10
    ICON = 32
    
    def __init__(self, model: ResultModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._name_font = ui_font(10, QFont.Weight.DemiBold)
        self._small_font = ui_font(8.8)
        self._snippet_font = ui_font(9.2)
        self._badge_font = ui_font(8.5, QFont.Weight.DemiBold)
    
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        entry: Entry = index.data(ENTRY_ROLE)
        has_snippet = entry is not None and entry.result is not None
        return QSize(200, 74 if has_snippet else 54)
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry: Entry = index.data(ENTRY_ROLE)
        if entry is None:
            return
        p = palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        
        # 背景
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), 8, 8)
            painter.fillPath(path, QColor(p.accent_soft if selected else p.hover))
        if selected:
            bar = QRectF(rect.left() + 1, rect.top() + rect.height() * 0.28, 3, rect.height() * 0.44)
            path = QPainterPath()
            path.addRoundedRect(bar, 1.5, 1.5)
            painter.fillPath(path, QColor(p.accent))
        
        # アイコン
        icon_rect = QRect(rect.left() + self.PAD_X, rect.top() + 9, self.ICON, self.ICON)
        icons.file_icon(entry.file_info.extension, self.ICON).paint(painter, icon_rect)
        if entry.is_error:
            warn = QRect(icon_rect.right() - 13, icon_rect.bottom() - 13, 16, 16)
            painter.setBrush(QColor(p.surface))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(warn.adjusted(-1, -1, 1, 1))
            painter.drawPixmap(warn, icons.pixmap("warning", p.danger, 16))
        
        left = icon_rect.right() + 12
        right = rect.right() - 10
        top = rect.top() + 7
        
        # 件数バッジ
        badge_width = 0
        if entry.result is not None and not entry.is_error:
            text = f"{entry.count}+" if entry.result.truncated else str(entry.count)
            painter.setFont(self._badge_font)
            metrics = QFontMetrics(self._badge_font)
            badge_width = metrics.horizontalAdvance(text) + 16
            badge = QRectF(right - badge_width, top + 1, badge_width, 19)
            path = QPainterPath()
            path.addRoundedRect(badge, 9.5, 9.5)
            painter.fillPath(path, QColor(p.accent if selected else p.accent_soft))
            painter.setPen(QColor(p.accent_text if selected else p.accent_fg))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
            badge_width += 8
        elif entry.result is None:
            # ファイル一覧では更新日を右に出す
            painter.setFont(self._small_font)
            date_text = f"{entry.file_info.modified_time:%Y/%m/%d}"
            metrics = QFontMetrics(self._small_font)
            badge_width = metrics.horizontalAdvance(date_text) + 8
            painter.setPen(QColor(p.text_tertiary))
            painter.drawText(
                QRect(right - badge_width, top, badge_width, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                date_text,
            )
        
        # ファイル名
        painter.setFont(self._name_font)
        painter.setPen(QColor(p.danger if entry.is_error else p.text))
        name_rect = QRect(left, top, right - left - badge_width, 20)
        name = QFontMetrics(self._name_font).elidedText(
            entry.file_info.name, Qt.TextElideMode.ElideMiddle, name_rect.width()
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        
        # フォルダ
        painter.setFont(self._small_font)
        painter.setPen(QColor(p.text_secondary))
        folder_rect = QRect(left, top + 21, right - left, 17)
        folder = self._model.relative_folder(entry)
        if entry.result is None:
            folder = f"{folder}　·　{format_file_size(entry.file_info.size)}"
        painter.drawText(
            folder_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(self._small_font).elidedText(folder, Qt.TextElideMode.ElideMiddle, folder_rect.width()),
        )
        
        # ヒット箇所の抜粋
        if entry.result is not None:
            snippet_rect = QRect(left, top + 40, right - left, 20)
            if entry.is_error:
                painter.setPen(QColor(p.danger))
                painter.drawText(
                    snippet_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    QFontMetrics(self._small_font).elidedText(
                        f"読み込めませんでした: {entry.result.error}", Qt.TextElideMode.ElideRight, snippet_rect.width()
                    ),
                )
            elif entry.result.matches:
                self._paint_snippet(painter, snippet_rect, entry, p)
        
        painter.restore()
    
    def _paint_snippet(self, painter: QPainter, rect: QRect, entry: Entry, p) -> None:
        match = entry.result.matches[0]
        x = rect.left()
        limit = rect.right()
        
        # 位置（例: セル A4）
        painter.setFont(self._small_font)
        small = QFontMetrics(self._small_font)
        location = match.location.split(", ")[-1] if match.location else ""
        if location:
            loc_text = location
            width = min(small.horizontalAdvance(loc_text) + 6, (limit - x) // 2)
            painter.setPen(QColor(p.text_tertiary))
            painter.drawText(
                QRect(x, rect.top(), width, rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                small.elidedText(loc_text, Qt.TextElideMode.ElideRight, width - 4),
            )
            x += width + 4
        
        painter.setFont(self._snippet_font)
        metrics = QFontMetrics(self._snippet_font)
        before = " ".join(match.before.split())[-24:]
        if before and before != match.before.strip():
            before = "…" + before.lstrip("…")
        matched = " ".join(match.matched_text.split())
        after = " ".join(match.after.split())
        
        def draw(text: str, color: str, highlight: bool = False) -> int:
            nonlocal x
            available = limit - x
            if available <= 8 or not text:
                return 0
            shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available)
            width = metrics.horizontalAdvance(shown)
            if highlight:
                box = QRectF(x - 1, rect.top() + 1, width + 2, rect.height() - 2)
                path = QPainterPath()
                path.addRoundedRect(box, 3, 3)
                painter.fillPath(path, QColor(p.match_bg))
            painter.setPen(QColor(color))
            painter.drawText(QRect(x, rect.top(), width + 2, rect.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, shown)
            x += width
            return width
        
        draw(before, p.text_secondary)
        draw(matched, p.match_text, highlight=True)
        draw(after, p.text_secondary)


class ResultsPanel(QWidget):
    """結果一覧のパネル"""
    
    file_selected = Signal(object)  # Entry
    back_to_listing = Signal()
    export_requested = Signal()
    browse_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = ResultModel(self)
        self._proxy = ResultProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.sort(0)
        self._total_matches = 0
        self._error_count = 0
        self._select_timer = QTimer(self, singleShot=True, interval=140)
        self._select_timer.timeout.connect(self._emit_selection)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = card()
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        
        # 見出し
        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 0, 0)
        header.setSpacing(6)
        self._title = label("ファイル", "SectionTitle")
        header.addWidget(self._title)
        self._summary = label("", "Secondary")
        header.addWidget(self._summary, 1)
        
        self._export_btn = ghost_button("export", "検索結果を Excel に書き出す (Ctrl+S)", size=16)
        self._export_btn.clicked.connect(self.export_requested.emit)
        self._export_btn.hide()
        header.addWidget(self._export_btn)
        
        self._back_btn = ghost_button("list", "フォルダ内のファイル一覧に戻す", size=16)
        self._back_btn.clicked.connect(self.back_to_listing.emit)
        self._back_btn.hide()
        header.addWidget(self._back_btn)
        
        self._sort_btn = ghost_button("sort", "並べ替え", size=16)
        self._sort_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sort_menu = QMenu(self._sort_btn)
        self._sort_actions: dict[str, QAction] = {}
        for key, text in SORT_OPTIONS:
            action = sort_menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(key == "path")
            action.triggered.connect(lambda _=False, k=key: self.set_sort_key(k))
            self._sort_actions[key] = action
        self._sort_btn.setMenu(sort_menu)
        header.addWidget(self._sort_btn)
        layout.addLayout(header)
        
        # 絞り込み
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("一覧を絞り込む（ファイル名・フォルダ）")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.addAction(icons.icon("filter", "secondary"), QLineEdit.ActionPosition.LeadingPosition)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter_edit)
        
        # 一覧 / 空の案内
        self._stack = QStackedWidget()
        self._list = QListView()
        self._list.setModel(self._proxy)
        self._list.setItemDelegate(ResultDelegate(self._model, self._list))
        self._list.setUniformItemSizes(False)
        self._list.setMouseTracking(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.verticalScrollBar().setSingleStep(24)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.doubleClicked.connect(lambda index: self._open(index.data(ENTRY_ROLE)))
        self._list.selectionModel().currentChanged.connect(lambda *_: self._select_timer.start())
        self._list.activated.connect(lambda index: self._open(index.data(ENTRY_ROLE)))
        self._stack.addWidget(self._list)
        
        self._empty = EmptyState(
            "folder-open",
            "検索するフォルダを選んでください",
            "上の「参照…」で選ぶか、フォルダをこのウィンドウにドラッグ＆ドロップします。",
            "フォルダを選ぶ…",
        )
        self._empty.action_clicked.connect(self.browse_requested.emit)
        self._stack.addWidget(self._empty)
        self._stack.setCurrentWidget(self._empty)
        layout.addWidget(self._stack, 1)
        
        theme().changed.connect(lambda _: self._list.viewport().update())
    
    # ------------------------------------------------------------------
    # 内容の設定
    # ------------------------------------------------------------------
    
    def show_placeholder(self, icon_name: str, title: str, text: str = "", action: str = "") -> None:
        self._empty.set_content(icon_name, title, text, action)
        self._stack.setCurrentWidget(self._empty)
    
    def set_listing(self, files: list[FileInfo], root: Path) -> None:
        """検索前: フォルダ内のファイル一覧"""
        self._model.set_files(files, root)
        self._title.setText("ファイル")
        self._back_btn.hide()
        self._export_btn.hide()
        self._update_listing_summary()
        if files:
            self._stack.setCurrentWidget(self._list)
        else:
            self.show_placeholder("document", "対象のファイルがありません", "ファイルの種類やサブフォルダの設定を確認してください。")
    
    def set_extension_filter(self, extensions: Optional[set[str]]) -> None:
        self._proxy.set_extensions(extensions)
        if not self._model.searched:
            self._update_listing_summary()
    
    def _update_listing_summary(self) -> None:
        self._summary.setText(f"{self._proxy.rowCount():,} 件")
    
    def begin_search(self, root: Path) -> None:
        self._model.root = root
        self._model.clear(searched=True)
        self._total_matches = 0
        self._error_count = 0
        self._title.setText("検索結果")
        self._summary.setText("検索中…")
        self._back_btn.show()
        self.show_placeholder("search", "検索しています…", "見つかったファイルから順に表示します。")
    
    def add_result(self, result: SearchResult) -> None:
        first = self._model.rowCount() == 0
        self._model.add_result(result)
        if result.error:
            self._error_count += 1
        else:
            self._total_matches += result.match_count
        if first:
            self._stack.setCurrentWidget(self._list)
        self._update_search_summary()
        # 最初にヒットしたファイルを自動で表示する
        if not self._list.currentIndex().isValid() and not result.error:
            self.select_first()
    
    def _update_search_summary(self, running: bool = True) -> None:
        files = self._model.rowCount() - self._error_count
        text = f"{files:,} ファイル · {self._total_matches:,} 件"
        if self._error_count:
            text += f" · エラー {self._error_count}"
        if running:
            text += " …"
        self._summary.setText(text)
    
    def finish_search(self, cancelled: bool) -> None:
        self._update_search_summary(running=False)
        self._export_btn.setVisible(self._model.rowCount() > 0)
        if self._model.rowCount() == 0:
            if cancelled:
                self.show_placeholder("stop", "検索を中断しました")
            else:
                self.show_placeholder(
                    "search",
                    "見つかりませんでした",
                    "・語のつづりや、全角/半角・大文字/小文字の区別を確認<br>"
                    "・「すべての語を含む」を「いずれかの語を含む」に変更<br>"
                    "・ファイルの種類とサブフォルダの設定を確認",
                )
    
    def results(self) -> list:
        """表示中の検索結果（並べ替え・絞り込みの順）"""
        out = []
        for row in range(self._proxy.rowCount()):
            entry = self._proxy.index(row, 0).data(ENTRY_ROLE)
            if entry is not None and entry.result is not None:
                out.append(entry.result)
        return out
    
    def is_showing_results(self) -> bool:
        return self._model.searched
    
    # ------------------------------------------------------------------
    # 選択
    # ------------------------------------------------------------------
    
    def select_first(self) -> None:
        if self._proxy.rowCount() > 0:
            self._list.setCurrentIndex(self._proxy.index(0, 0))
    
    def _emit_selection(self) -> None:
        index = self._list.currentIndex()
        if index.isValid():
            self.file_selected.emit(index.data(ENTRY_ROLE))
    
    def current_entry(self) -> Optional[Entry]:
        index = self._list.currentIndex()
        return index.data(ENTRY_ROLE) if index.isValid() else None
    
    def focus_list(self) -> None:
        self._list.setFocus()
    
    def set_sort_key(self, key: str) -> None:
        for k, action in self._sort_actions.items():
            action.setChecked(k == key)
        self._proxy.set_sort_key(key)
    
    def sort_key(self) -> str:
        return self._proxy.sort_key
    
    def _on_filter_changed(self, text: str) -> None:
        self._proxy.set_text_filter(text)
        if not self._model.searched:
            self._update_listing_summary()
    
    # ------------------------------------------------------------------
    # 右クリックメニュー
    # ------------------------------------------------------------------
    
    def _show_context_menu(self, pos) -> None:
        index = self._list.indexAt(pos)
        entry: Optional[Entry] = index.data(ENTRY_ROLE) if index.isValid() else None
        if entry is None:
            return
        path = entry.file_info.path
        clipboard = QGuiApplication.clipboard()
        menu = QMenu(self)
        menu.addAction(icons.icon("external"), "開く\tEnter", lambda: open_file(path))
        menu.addAction(icons.icon("folder"), f"{file_manager_name()}で表示\tCtrl+E", lambda: reveal_in_explorer(path))
        menu.addSeparator()
        menu.addAction(icons.icon("copy"), "パスをコピー\tCtrl+Shift+C", lambda: clipboard.setText(str(path)))
        menu.addAction("ファイル名をコピー", lambda: clipboard.setText(path.name))
        menu.addAction("フォルダのパスをコピー", lambda: clipboard.setText(str(path.parent)))
        menu.exec(self._list.viewport().mapToGlobal(pos))
    
    @staticmethod
    def _open(entry: Optional[Entry]) -> None:
        if entry is not None:
            open_file(entry.file_info.path)

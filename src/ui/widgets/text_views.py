"""テキスト表示（Office/PDF の再構成表示と、テキストファイルの行番号つき表示）"""


from PySide6.QtCore import QRect, QSize, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTextBrowser, QTextEdit, QWidget

from src.ui.theme import palette, ui_font

BASE_POINT_SIZE = 10.0
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "BIZ UDGothic", "MS Gothic", "Noto Sans Mono CJK JP", "monospace"]


def _current_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setBackground(QColor("#FF9F1C"))
    fmt.setForeground(QColor("#1A1C20"))
    fmt.setFontWeight(QFont.Weight.DemiBold)
    return fmt


def _colors() -> dict[str, str]:
    p = palette()
    return {
        "TEXT": p.text, "TEXT2": p.text_secondary, "TEXT3": p.text_tertiary,
        "SURFACE": p.surface, "SURFACE_ALT": p.surface_alt, "BORDER": p.border_strong,
        "HEADER": p.surface_alt, "MARK": p.match_bg, "MARK_TEXT": p.match_text,
    }


class RichTextView(QTextBrowser):
    """Office/PDF のテキスト表示（表・シートを再構成したもの）"""
    
    hit_clicked = Signal(int)
    section_changed = Signal(int)
    zoom_step_requested = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._on_anchor)
        self.document().setDocumentMargin(18)
        self._template = ""
        self._hit_spans: dict[int, tuple[int, int]] = {}
        self._section_positions: list[int] = []
        self._current = -1
        self._last_section = -1
        self._zoom = 1.0
        self.verticalScrollBar().valueChanged.connect(self._update_section)
        self._apply_font()
    
    # ------------------------------------------------------------------
    
    def set_content(self, template: str) -> None:
        self._template = template
        self._current = -1
        self._render(keep_scroll=False)
    
    def apply_theme(self) -> None:
        if self._template:
            self._render(keep_scroll=True)
    
    def _render(self, keep_scroll: bool) -> None:
        scroll = self.verticalScrollBar().value()
        text = self._template
        for name, color in _colors().items():
            text = text.replace(f"@@{name}@@", color)
        p = palette()
        self.setStyleSheet(f"QTextBrowser {{ background: {p.surface}; color: {p.text}; border: none; }}")
        self.setHtml(text)
        self._apply_font()
        self._index_anchors()
        self._update_current()
        self.verticalScrollBar().setValue(scroll if keep_scroll else 0)
        self._last_section = -1
        self._update_section()
    
    def _apply_font(self) -> None:
        font = ui_font(BASE_POINT_SIZE * self._zoom)
        self.document().setDefaultFont(font)
    
    def _index_anchors(self) -> None:
        """マッチ箇所（hit-N）とセクション（sec-N）の文字位置を調べる"""
        self._hit_spans = {}
        sections: dict[int, int] = {}
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    for name in fragment.charFormat().anchorNames():
                        start = fragment.position()
                        end = start + fragment.length()
                        if name.startswith("hit-"):
                            index = int(name[4:])
                            old = self._hit_spans.get(index)
                            self._hit_spans[index] = (min(start, old[0]), max(end, old[1])) if old else (start, end)
                        elif name.startswith("sec-"):
                            sections.setdefault(int(name[4:]), start)
                iterator += 1
            block = block.next()
        self._section_positions = [sections[i] for i in sorted(sections)]
    
    # ------------------------------------------------------------------
    
    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self._apply_font()
    
    def goto_hit(self, index: int) -> None:
        self._current = index
        self._update_current()
        span = self._hit_spans.get(index)
        if span is None:
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(span[0])
        rect = self.cursorRect(cursor)
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + rect.center().y() - self.viewport().height() // 2)
        hbar = self.horizontalScrollBar()
        if rect.x() < 0 or rect.x() > self.viewport().width():
            hbar.setValue(hbar.value() + rect.x() - self.viewport().width() // 2)
    
    def _update_current(self) -> None:
        selections = []
        span = self._hit_spans.get(self._current)
        if span is not None:
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.document())
            cursor.setPosition(span[0])
            cursor.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selection.format = _current_format()
            selections.append(selection)
        self.setExtraSelections(selections)
    
    def goto_section(self, index: int) -> None:
        self.scrollToAnchor(f"sec-{index}")
    
    def _update_section(self, *_args) -> None:
        if not self._section_positions:
            return
        position = self.cursorForPosition(self.viewport().rect().topLeft()).position()
        position = self.cursorForPosition(self.viewport().rect().center()).position() if position == 0 else position
        current = 0
        for index, start in enumerate(self._section_positions):
            if start <= position:
                current = index
        if current != self._last_section:
            self._last_section = current
            self.section_changed.emit(current)
    
    def _on_anchor(self, url: QUrl) -> None:
        text = url.toString()
        if text.startswith("hit:"):
            try:
                self.hit_clicked.emit(int(text[4:]))
            except ValueError:
                pass
    
    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_step_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class _LineNumbers(QWidget):
    def __init__(self, editor: "PlainTextView"):
        super().__init__(editor)
        self._editor = editor
    
    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.gutter_width(), 0)
    
    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_gutter(event)


class PlainTextView(QPlainTextEdit):
    """テキストファイル（行番号つき）"""
    
    hit_clicked = Signal(int)
    section_changed = Signal(int)
    zoom_step_requested = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self._gutter = _LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self._update_margins())
        self.updateRequest.connect(self._update_gutter)
        self._spans: list[tuple[int, int]] = []
        self._current = -1
        self._zoom = 1.0
        self._apply_font()
        self.apply_theme()
    
    def _apply_font(self) -> None:
        font = QFont()
        font.setFamilies(MONO_FAMILIES)
        font.setPointSizeF(BASE_POINT_SIZE * self._zoom)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self._update_margins()
    
    def apply_theme(self) -> None:
        p = palette()
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {p.surface}; color: {p.text}; border: none; "
            f"selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}"
        )
        self._update_selections()
        self._gutter.update()
    
    def set_content(self, text: str, spans: list[tuple[int, int]]) -> None:
        self._spans = spans
        self._current = -1
        self.setPlainText(text)
        self._update_selections()
        self.verticalScrollBar().setValue(0)
    
    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self._apply_font()
    
    def goto_hit(self, index: int) -> None:
        if not 0 <= index < len(self._spans):
            return
        self._current = index
        self._update_selections()
        cursor = self.textCursor()
        cursor.setPosition(self._spans[index][0])
        self.setTextCursor(cursor)
        self.centerCursor()
        self.ensureCursorVisible()
    
    def goto_section(self, index: int) -> None:
        pass
    
    def _update_selections(self) -> None:
        p = palette()
        mark = QTextCharFormat()
        mark.setBackground(QColor(p.match_bg))
        mark.setForeground(QColor(p.match_text))
        selections = []
        for index, (start, end) in enumerate(self._spans):
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selection.format = _current_format() if index == self._current else mark
            selections.append(selection)
        self.setExtraSelections(selections)
    
    # --- 行番号 ---
    
    def gutter_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits
    
    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
    
    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
    
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))
    
    def paint_gutter(self, event) -> None:
        p = palette()
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(p.surface_alt))
        painter.setPen(QColor(p.text_tertiary))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        width = self._gutter.width() - 8
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
    
    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_step_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

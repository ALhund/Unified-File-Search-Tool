"""正規表現ヘルプダイアログ"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QTabWidget,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
)


class RegexHelpDialog(QDialog):
    """正規表現ヘルプダイアログ"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("正規表現ヘルプ")
        self.setMinimumSize(500, 400)
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        
        # タブウィジェット
        tabs = QTabWidget()
        
        # 基本パターン
        basic_tab = self._create_table([
            (".", "任意の1文字（改行以外）"),
            ("*", "直前の文字が0回以上繰り返し"),
            ("+", "直前の文字が1回以上繰り返し"),
            ("?", "直前の文字が0回または1回"),
            ("^", "行頭"),
            ("$", "行末"),
            ("|", "または（OR）"),
            ("\\", "特殊文字のエスケープ"),
        ])
        tabs.addTab(basic_tab, "基本")
        
        # 文字クラス
        class_tab = self._create_table([
            ("[abc]", "a, b, cのいずれか1文字"),
            ("[^abc]", "a, b, c以外の1文字"),
            ("[a-z]", "aからzまでの1文字"),
            ("\\d", "数字 [0-9]"),
            ("\\D", "数字以外"),
            ("\\w", "単語構成文字 [a-zA-Z0-9_]"),
            ("\\W", "単語構成文字以外"),
            ("\\s", "空白文字（スペース、タブ、改行）"),
            ("\\S", "空白文字以外"),
        ])
        tabs.addTab(class_tab, "文字クラス")
        
        # グループと参照
        group_tab = self._create_table([
            ("(abc)", "グループ化（キャプチャ）"),
            ("(?:abc)", "グループ化（非キャプチャ）"),
            ("(?=abc)", "先読み（abcが続く）"),
            ("(?!abc)", "否定先読み（abcが続かない）"),
            ("\\1", "後方参照（1番目のグループ）"),
        ])
        tabs.addTab(group_tab, "グループ")
        
        # 量指定子
        quantifier_tab = self._create_table([
            ("{n}", "n回繰り返し"),
            ("{n,}", "n回以上繰り返し"),
            ("{n,m}", "n回以上m回以下繰り返し"),
            ("*?", "最短マッチ（0回以上）"),
            ("+?", "最短マッチ（1回以上）"),
            ("??", "最短マッチ（0回または1回）"),
        ])
        tabs.addTab(quantifier_tab, "量指定子")
        
        # 使用例
        example_tab = self._create_table([
            ("\\d{3}-\\d{4}", "郵便番号（123-4567）"),
            ("\\d{4}/\\d{2}/\\d{2}", "日付（2024/01/01）"),
            ("[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", "メールアドレス"),
            ("https?://[^\\s]+", "URL"),
            ("「[^」]*」", "カギ括弧内の文字列"),
            ("^#.*$", "行頭が#で始まるコメント"),
        ])
        tabs.addTab(example_tab, "使用例")
        
        layout.addWidget(tabs)
        
        # 閉じるボタン
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _create_table(self, items: list[tuple[str, str]]) -> QWidget:
        """テーブルを作成"""
        table = QTableWidget(len(items), 2)
        table.setHorizontalHeaderLabels(["パターン", "説明"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        for row, (pattern, desc) in enumerate(items):
            table.setItem(row, 0, QTableWidgetItem(pattern))
            table.setItem(row, 1, QTableWidgetItem(desc))
        
        return table

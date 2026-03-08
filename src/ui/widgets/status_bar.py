"""ステータスバー。

検索の進捗・処理時間・ステータスメッセージを表示するウィジェット。
"""

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)


class StatusBar(QWidget):
    """ステータスバー。

    メッセージラベル・プログレスバー・処理時間ラベルを横並びで表示する。
    検索開始時に :meth:`show_progress` でプログレスバーを表示し、
    終了時に :meth:`set_ready` で準備完了状態に戻す。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェットの UI を構築する。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(16)

        # ステータスメッセージ
        self._message_label = QLabel("準備完了")
        layout.addWidget(self._message_label)

        layout.addStretch()

        # プログレスバー
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        # 進捗情報
        self._progress_label = QLabel("")
        self._progress_label.hide()
        layout.addWidget(self._progress_label)

        # 処理時間
        self._time_label = QLabel("")
        layout.addWidget(self._time_label)

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def set_message(self, message: str) -> None:
        """ステータスメッセージを設定する。

        Args:
            message: 表示するメッセージ文字列。
        """
        self._message_label.setText(message)

    def show_progress(self, visible: bool = True) -> None:
        """プログレスバーと進捗ラベルの表示/非表示を切り替える。

        非表示にするとプログレスバーの値と進捗ラベルテキストもリセットする。

        Args:
            visible: ``True`` で表示、``False`` で非表示。
        """
        self._progress_bar.setVisible(visible)
        self._progress_label.setVisible(visible)
        if not visible:
            self._progress_bar.setValue(0)
            self._progress_label.setText("")

    def set_progress(
        self,
        value: int,
        maximum: int = 100,
        text: str | None = None,
    ) -> None:
        """プログレスバーの現在値と最大値を設定する。

        Args:
            value: 現在値。
            maximum: 最大値（デフォルト 100）。
            text: 進捗ラベルに表示するテキスト（例: ``"10/100 ファイル処理中"``）。
                ``None`` の場合はラベルを更新しない。
        """
        self._progress_bar.setMaximum(maximum)
        self._progress_bar.setValue(value)

        if text is not None:
            self._progress_label.setText(text)

    def set_indeterminate(self, indeterminate: bool = True) -> None:
        """不定進捗モードを設定する。

        ``True`` にするとプログレスバーがアニメーションする。
        ``False`` にすると範囲を 0–100 にリセットする。

        Args:
            indeterminate: ``True`` で不定進捗モード、``False`` で通常モード。
        """
        if indeterminate:
            self._progress_bar.setRange(0, 0)
        else:
            self._progress_bar.setRange(0, 100)

    def set_time(self, seconds: float) -> None:
        """処理時間を人間が読める形式でラベルに表示する。

        Args:
            seconds: 処理時間（秒）。
                1 秒未満はミリ秒表示、60 秒未満は秒表示、それ以上は分秒表示。
        """
        if seconds < 1:
            text = f"{seconds * 1000:.0f}ms"
        elif seconds < 60:
            text = f"{seconds:.1f}秒"
        else:
            minutes = int(seconds // 60)
            secs = seconds % 60
            text = f"{minutes}分{secs:.0f}秒"

        self._time_label.setText(f"処理時間: {text}")

    def clear_time(self) -> None:
        """処理時間ラベルをクリアする。"""
        self._time_label.setText("")

    def set_ready(self) -> None:
        """準備完了状態にリセットする。

        メッセージを「準備完了」に戻し、プログレスバーを非表示にする。
        """
        self.set_message("準備完了")
        self.show_progress(False)

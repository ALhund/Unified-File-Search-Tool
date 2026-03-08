"""ロギングモジュール。

機能別のログファイルを JSONL 形式で出力する。
1 ファイルあたり最大 :attr:`Logger.max_lines` 行を FIFO 方式で管理する。

使用例::

    logger = get_logger("search")
    logger.info("start", "Search started", query="foo")
    logger.exception("error", "Failed", exc, file_path="/tmp/a.pdf")
"""

import json
import uuid
from collections import deque
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from threading import Lock


class LogLevel(IntEnum):
    """ログレベルを表す列挙型。

    値が大きいほど深刻度が高い。
    """

    DEBUG = 10
    INFORMATION = 20
    WARNING = 30
    CRITICAL = 40

    @classmethod
    def from_string(cls, level_str: str) -> "LogLevel":
        """文字列からログレベルに変換する。

        大文字小文字を区別しない。認識できない文字列は
        :attr:`INFORMATION` を返す。

        Args:
            level_str: "Debug" / "Information" / "Warning" / "Critical"
                       またはその短縮形。

        Returns:
            対応する LogLevel 値。
        """
        mapping: dict[str, "LogLevel"] = {
            "debug": cls.DEBUG,
            "information": cls.INFORMATION,
            "info": cls.INFORMATION,
            "warning": cls.WARNING,
            "warn": cls.WARNING,
            "critical": cls.CRITICAL,
            "error": cls.CRITICAL,
        }
        return mapping.get(level_str.lower(), cls.INFORMATION)

    def to_string(self) -> str:
        """ログレベルを先頭大文字の文字列で返す（例: "Information"）。"""
        return self.name.capitalize()


class Logger:
    """機能別ログ出力クラス。

    各機能ごとに独立した JSONL ログファイルへ書き込む。
    スレッドセーフ（内部で :class:`threading.Lock` を使用）。

    Args:
        feature: 機能名（ログファイル名のベース）。
        logs_path: ログファイルを格納するディレクトリ。
        max_lines: ログファイルの最大行数。超えると古い行が削除される。
        min_level: この値以上のレベルのみ書き込む。
    """

    def __init__(
        self,
        feature: str,
        logs_path: Path,
        max_lines: int = 1000,
        min_level: LogLevel = LogLevel.INFORMATION,
    ) -> None:
        self.feature = feature
        self.log_file = logs_path / f"{feature}.log"
        self.max_lines = max_lines
        self.min_level = min_level
        self._lock = Lock()
        self._correlation_id: str | None = None

        logs_path.mkdir(parents=True, exist_ok=True)

    def set_correlation_id(self, correlation_id: str | None = None) -> str:
        """相関 ID を設定する（一連の処理を追跡するため）。

        Args:
            correlation_id: 使用する相関 ID。
                            ``None`` の場合は UUID の先頭 8 文字を自動生成する。

        Returns:
            設定された相関 ID。
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())[:8]
        self._correlation_id = correlation_id
        return correlation_id

    def clear_correlation_id(self) -> None:
        """相関 ID をクリアする。"""
        self._correlation_id = None

    def debug(
        self,
        event: str,
        message: str,
        file_path: str | None = None,
        elapsed_ms: int | None = None,
        **extra: object,
    ) -> None:
        """DEBUG レベルのログを書き込む。

        Args:
            event: イベント名（例: "start", "extract"）。
            message: 人間が読める説明文。
            file_path: 対象ファイルのパス（省略可）。
            elapsed_ms: 処理時間（ミリ秒、省略可）。
            **extra: ログエントリに追加する任意のフィールド。
        """
        self._write_log(
            LogLevel.DEBUG, event, message, file_path, elapsed_ms,
            extra or None,
        )

    def info(
        self,
        event: str,
        message: str,
        file_path: str | None = None,
        elapsed_ms: int | None = None,
        **extra: object,
    ) -> None:
        """INFORMATION レベルのログを書き込む。

        Args:
            event: イベント名。
            message: 人間が読める説明文。
            file_path: 対象ファイルのパス（省略可）。
            elapsed_ms: 処理時間（ミリ秒、省略可）。
            **extra: ログエントリに追加する任意のフィールド。
        """
        self._write_log(
            LogLevel.INFORMATION, event, message, file_path, elapsed_ms,
            extra or None,
        )

    def warning(
        self,
        event: str,
        message: str,
        file_path: str | None = None,
        elapsed_ms: int | None = None,
        **extra: object,
    ) -> None:
        """WARNING レベルのログを書き込む。

        Args:
            event: イベント名。
            message: 人間が読める説明文。
            file_path: 対象ファイルのパス（省略可）。
            elapsed_ms: 処理時間（ミリ秒、省略可）。
            **extra: ログエントリに追加する任意のフィールド。
        """
        self._write_log(
            LogLevel.WARNING, event, message, file_path, elapsed_ms,
            extra or None,
        )

    def critical(
        self,
        event: str,
        message: str,
        file_path: str | None = None,
        elapsed_ms: int | None = None,
        **extra: object,
    ) -> None:
        """CRITICAL レベルのログを書き込む。

        Args:
            event: イベント名。
            message: 人間が読める説明文。
            file_path: 対象ファイルのパス（省略可）。
            elapsed_ms: 処理時間（ミリ秒、省略可）。
            **extra: ログエントリに追加する任意のフィールド。
        """
        self._write_log(
            LogLevel.CRITICAL, event, message, file_path, elapsed_ms,
            extra or None,
        )

    def exception(
        self,
        event: str,
        message: str,
        exception: Exception,
        file_path: str | None = None,
        **extra: object,
    ) -> None:
        """例外情報付きの CRITICAL ログを書き込む。

        例外の型名と文字列表現を自動でログエントリに付加する。

        Args:
            event: イベント名。
            message: 人間が読める説明文。
            exception: 記録する例外オブジェクト。
            file_path: 対象ファイルのパス（省略可）。
            **extra: ログエントリに追加する任意のフィールド。
        """
        extra_data = dict(extra)
        extra_data["exception_type"] = type(exception).__name__
        extra_data["exception_message"] = str(exception)
        self._write_log(
            LogLevel.CRITICAL, event, message, file_path, extra=extra_data,
        )

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _write_log(
        self,
        level: LogLevel,
        event: str,
        message: str,
        file_path: str | None = None,
        elapsed_ms: int | None = None,
        extra: dict | None = None,
    ) -> None:
        """ログエントリを構築してファイルに書き込む。

        min_level 未満の場合は何もしない。

        Args:
            level: ログレベル。
            event: イベント名。
            message: 説明文。
            file_path: 対象ファイルパス（省略可）。
            elapsed_ms: 処理時間ミリ秒（省略可）。
            extra: 追加フィールドの辞書（省略可）。
        """
        if level < self.min_level:
            return

        log_entry: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.to_string(),
            "feature": self.feature,
            "event": event,
            "message": message,
        }

        if self._correlation_id:
            log_entry["correlation_id"] = self._correlation_id
        if file_path:
            log_entry["file_path"] = file_path
        if elapsed_ms is not None:
            log_entry["elapsed_ms"] = elapsed_ms
        if extra:
            log_entry.update(extra)

        log_line = json.dumps(log_entry, ensure_ascii=False)

        with self._lock:
            self._append_with_rotation(log_line)

    def _append_with_rotation(self, log_line: str) -> None:
        """FIFO 方式でログ行を追加する（max_lines 上限）。

        既存ファイルを読み込んで deque に格納し、末尾に追加後に書き直す。
        書き込み失敗時は UI をブロックしないよう例外を握りつぶす。

        Args:
            log_line: 追加する JSONL 文字列（改行なし）。
        """
        try:
            lines: deque[str] = deque(maxlen=self.max_lines)
            if self.log_file.exists():
                with open(self.log_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped:
                            lines.append(stripped)

            lines.append(log_line)

            with open(self.log_file, "w", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")

        except (IOError, OSError) as exc:
            # ログ書き込み失敗は UI を固めないよう無視する
            print(f"Warning: Failed to write log: {exc}", flush=True)


# ---------------------------------------------------------------------------
# グローバルキャッシュとファクトリ関数
# ---------------------------------------------------------------------------

_loggers: dict[str, Logger] = {}
_logger_lock = Lock()


def get_logger(feature: str) -> Logger:
    """機能別のロガーインスタンスを取得する（スレッドセーフ）。

    同じ feature 名に対しては常に同一インスタンスを返す。

    Args:
        feature: 機能名（例: "search", "extraction", "ui"）。

    Returns:
        対応する Logger インスタンス。
    """
    from src.common.config import get_config  # 循環依存を回避するため遅延インポート

    with _logger_lock:
        if feature not in _loggers:
            config = get_config()
            _loggers[feature] = Logger(
                feature=feature,
                logs_path=config.logs_path,
                max_lines=config.logs_max_lines_per_file,
                min_level=LogLevel.from_string(config.logging_level),
            )
        return _loggers[feature]

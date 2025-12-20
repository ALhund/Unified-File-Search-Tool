"""ロギングモジュール

機能別のログファイルを出力し、JSONL形式で統一する。
1000行上限のFIFO方式で管理。
"""

import json
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from threading import Lock
from typing import Optional
from collections import deque


class LogLevel(IntEnum):
    """ログレベル"""
    DEBUG = 10
    INFORMATION = 20
    WARNING = 30
    CRITICAL = 40
    
    @classmethod
    def from_string(cls, level_str: str) -> "LogLevel":
        mapping = {
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
        return self.name.capitalize()


class Logger:
    """機能別ログ出力クラス"""
    
    def __init__(
        self,
        feature: str,
        logs_path: Path,
        max_lines: int = 1000,
        min_level: LogLevel = LogLevel.INFORMATION,
    ):
        self.feature = feature
        self.log_file = logs_path / f"{feature}.log"
        self.max_lines = max_lines
        self.min_level = min_level
        self._lock = Lock()
        self._correlation_id: Optional[str] = None
        
        # ログフォルダが存在しない場合は作成
        logs_path.mkdir(parents=True, exist_ok=True)
    
    def set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """相関IDを設定（処理の追跡用）"""
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())[:8]
        self._correlation_id = correlation_id
        return correlation_id
    
    def clear_correlation_id(self) -> None:
        """相関IDをクリア"""
        self._correlation_id = None
    
    def _write_log(
        self,
        level: LogLevel,
        event: str,
        message: str,
        file_path: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """ログを書き込む"""
        if level < self.min_level:
            return
        
        log_entry = {
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
        """FIFO方式でログを追加（1000行上限）"""
        try:
            # 既存のログを読み込み
            lines: deque[str] = deque(maxlen=self.max_lines)
            if self.log_file.exists():
                with open(self.log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            lines.append(line)
            
            # 新しいログを追加
            lines.append(log_line)
            
            # 書き込み
            with open(self.log_file, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        
        except (IOError, OSError) as e:
            # ログ書き込み失敗は無視（UIを固めない）
            print(f"Warning: Failed to write log: {e}")
    
    def debug(
        self,
        event: str,
        message: str,
        file_path: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        **extra,
    ) -> None:
        """DEBUGレベルのログ"""
        self._write_log(LogLevel.DEBUG, event, message, file_path, elapsed_ms, extra or None)
    
    def info(
        self,
        event: str,
        message: str,
        file_path: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        **extra,
    ) -> None:
        """INFORMATIONレベルのログ"""
        self._write_log(LogLevel.INFORMATION, event, message, file_path, elapsed_ms, extra or None)
    
    def warning(
        self,
        event: str,
        message: str,
        file_path: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        **extra,
    ) -> None:
        """WARNINGレベルのログ"""
        self._write_log(LogLevel.WARNING, event, message, file_path, elapsed_ms, extra or None)
    
    def critical(
        self,
        event: str,
        message: str,
        file_path: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        **extra,
    ) -> None:
        """CRITICALレベルのログ"""
        self._write_log(LogLevel.CRITICAL, event, message, file_path, elapsed_ms, extra or None)
    
    def exception(
        self,
        event: str,
        message: str,
        exception: Exception,
        file_path: Optional[str] = None,
        **extra,
    ) -> None:
        """例外情報付きのCRITICALログ"""
        extra_data = extra or {}
        extra_data["exception_type"] = type(exception).__name__
        extra_data["exception_message"] = str(exception)
        self._write_log(LogLevel.CRITICAL, event, message, file_path, extra=extra_data)


# ロガーキャッシュ
_loggers: dict[str, Logger] = {}
_logger_lock = Lock()


def get_logger(feature: str) -> Logger:
    """機能別のロガーを取得"""
    from src.common.config import get_config
    
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
